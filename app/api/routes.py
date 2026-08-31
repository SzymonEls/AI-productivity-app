"""The synchronisation API: what changed, and what I changed while I was away."""

import sqlalchemy as sa
from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from ..extensions import db
from ..models import Project, ProjectDaySlot, ProjectTimelineGroup, SyncState
from .auth import register_auth_api
from .protocol import ENTITIES, PUSH_ORDER, from_json, serialise, to_json
from .pruning import prune_tombstones
from .revisions import INCLUDE_TOMBSTONES, soft_delete, touch, utc_now
from .security import attach_token_cookie, check_token, issue_token

api_bp = Blueprint("api", __name__, url_prefix="/api")

register_auth_api(api_bp)


@api_bp.before_request
def _verify_write():
    return check_token()


@api_bp.after_request
def _publish_token(response):
    return attach_token_cookie(response)


def _all_rows(statement):
    """Run a select that is allowed to see tombstones."""
    return db.session.execute(
        statement.execution_options(**{INCLUDE_TOMBSTONES: True})
    ).scalars().all()


def _reference_maps(user_id):
    """id -> uid for every table another table can point at."""
    maps = {}
    for column_name, model in (("project_id", Project), ("group_id", ProjectTimelineGroup)):
        rows = db.session.execute(
            sa.select(model.id, model.uid)
            .where(model.user_id == user_id)
            .execution_options(**{INCLUDE_TOMBSTONES: True})
        ).all()
        maps[column_name] = dict(rows)
    return maps


def _sync_state(user_id):
    state = db.session.execute(
        sa.select(SyncState).where(SyncState.user_id == user_id)
    ).scalar_one_or_none()
    if state is None:
        state = SyncState(user_id=user_id, last_rev=0, tombstone_floor=0)
        db.session.add(state)
        db.session.flush()
    return state


@api_bp.route("/me")
@login_required
def me():
    from flask import current_app

    state = _sync_state(current_user.id)
    db.session.commit()
    return jsonify(
        {
            "ok": True,
            "csrf_token": issue_token(),
            "user": {"username": current_user.username, "email": current_user.email},
            "app_version": current_app.config.get("APP_VERSION"),
            "demo_mode": bool(current_app.config.get("DEMO_MODE")),
            "timezone": current_app.config.get("CALENDAR_TIMEZONE"),
            "rev": state.last_rev,
        }
    )


@api_bp.route("/sync/changes")
@login_required
def changes():
    """Everything above the client's cursor, deletions included.

    A cursor below tombstone_floor cannot be answered with a difference: the
    deletions it would need have already been cleared away. Saying so, rather
    than sending an incomplete answer, is what stops a deleted project from
    quietly reappearing on a device that was away for a season.
    """
    try:
        since = int(request.args.get("since", 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "since must be a number."}), 400

    state = _sync_state(current_user.id)
    db.session.commit()

    if since > 0 and since < state.tombstone_floor:
        return (
            jsonify(
                {
                    "ok": False,
                    "reason": "cursor_too_old",
                    "message": "Too much has been cleared away to send a difference.",
                    "tombstone_floor": state.tombstone_floor,
                }
            ),
            409,
        )

    uid_by_id = _reference_maps(current_user.id)
    payload = {}
    for name in PUSH_ORDER:
        entity = ENTITIES[name]
        rows = _all_rows(
            sa.select(entity.model)
            .where(entity.model.user_id == current_user.id, entity.model.rev > since)
            .order_by(entity.model.rev)
        )
        payload[name] = [serialise(entity, row, uid_by_id) for row in rows]

    return jsonify({"ok": True, "rev": state.last_rev, "changes": payload})


@api_bp.route("/sync/push", methods=["POST"])
@login_required
def push():
    """Apply what the client did offline, and report what could not be applied.

    Nothing is merged silently. An operation built on a version the server has
    since moved past comes straight back, with both sides attached, for the
    person to settle - the one rule the whole design turns on.
    """
    body = request.get_json(silent=True) or {}
    operations = body.get("ops")
    if not isinstance(operations, list):
        return jsonify({"ok": False, "message": "ops must be a list."}), 400

    by_entity = {name: [] for name in PUSH_ORDER}
    for operation in operations:
        name = (operation or {}).get("entity")
        if name not in by_entity:
            return jsonify({"ok": False, "message": f"Unknown entity: {name!r}."}), 400
        by_entity[name].append(operation)

    applied, conflicts = [], []

    # Two bookings swapping places arrive as two updates. Checked one at a time,
    # the first would collide with the second, which has not moved yet - so a
    # row that is itself on its way somewhere else in this same batch cannot
    # count as a blocker. What remains is caught by the sweep after the loop.
    moving = {
        operation.get("uid")
        for operation in by_entity["day_slot"]
        if operation.get("op") in {"update", "delete"}
    }

    try:
        # Every booking that is changing places steps aside before any of them
        # is put down. One at a time is not enough: the first would land on the
        # spot the second has not left yet, and the partial unique index refuses
        # that halfway through - the same collision move_booking() works around
        # in the Jinja path. Marking them deleted frees the key, because the
        # index only counts live rows.
        parked = _park_moving_bookings(by_entity["day_slot"])
        for name in PUSH_ORDER:
            entity = ENTITIES[name]
            for operation in by_entity[name]:
                outcome = _apply(entity, operation, moving)
                (applied if outcome is True else conflicts).append(
                    operation.get("uid") if outcome is True else outcome
                )

        for row in parked:
            row.deleted_at = None

        db.session.flush()
        duplicate = _duplicate_booking()
        if duplicate is not None:
            db.session.rollback()
            return (
                jsonify(
                    {
                        "ok": False,
                        "reason": "slot_taken",
                        "message": (
                            f"Two bookings would share slot {duplicate.slot} on "
                            f"{duplicate.slot_date}. Nothing was saved."
                        ),
                    }
                ),
                409,
            )

        state = _sync_state(current_user.id)
        db.session.commit()
    except IntegrityError:
        # Two bookings genuinely wanting one spot. A refusal the person can act
        # on, not a server fault.
        db.session.rollback()
        return (
            jsonify(
                {
                    "ok": False,
                    "reason": "slot_taken",
                    "message": "Two bookings would share one slot. Nothing was saved.",
                }
            ),
            409,
        )
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "Could not save the changes."}), 500

    prune_tombstones(current_user.id)

    return jsonify(
        {"ok": True, "rev": state.last_rev, "applied": applied, "conflicts": conflicts}
    )


def _existing(entity, uid):
    return db.session.execute(
        sa.select(entity.model)
        .where(entity.model.user_id == current_user.id, entity.model.uid == uid)
        .execution_options(**{INCLUDE_TOMBSTONES: True})
    ).scalar_one_or_none()


def _conflict(entity, uid, reason, row=None, operation=None):
    uid_by_id = _reference_maps(current_user.id)
    return {
        "entity": entity.name,
        "uid": uid,
        "reason": reason,
        "server": serialise(entity, row, uid_by_id) if row is not None else None,
        "client": operation,
    }


def _apply(entity, operation, moving=frozenset()):
    """Apply one operation. Returns True, or a conflict to report back."""
    uid = operation.get("uid")
    if not uid:
        return _conflict(entity, uid, "missing_uid", operation=operation)

    kind = operation.get("op")
    base_rev = operation.get("base_rev")
    row = _existing(entity, uid)

    if kind == "create" and row is not None:
        return _conflict(entity, uid, "already_exists", row, operation)

    if kind != "create":
        if row is None:
            return _conflict(entity, uid, "gone", None, operation)
        # The row moved on after the client last read it. Everything the client
        # wrote on top of the older version is now a question, not an answer.
        if base_rev is None or row.rev > base_rev:
            return _conflict(entity, uid, "stale", row, operation)

    if kind == "delete":
        soft_delete(row)
        return True

    # Every read below is a SELECT, and a SELECT autoflushes. A half-built row
    # sitting in the session would be flushed with its NOT NULL columns still
    # empty, so the values are worked out in full before anything is added.
    columns = entity.model.__table__.columns
    values = {}

    with db.session.no_autoflush:
        for key, value in (operation.get("fields") or {}).items():
            if key in entity.references:
                column_name, model = entity.references[key]
                values[column_name] = _resolve_uid(model, value)
            elif key in entity.fields:
                values[key] = from_json(columns[key], value)

        if entity.model is ProjectDaySlot:
            clash = _slot_clash(
                values.get("slot_date", getattr(row, "slot_date", None)),
                values.get("slot", getattr(row, "slot", None)),
                uid,
                moving,
            )
            if clash is not None:
                return _conflict(entity, uid, "slot_taken", clash, operation)

    if row is None:
        row = entity.model(user_id=current_user.id, uid=uid)
        db.session.add(row)

    for key, value in values.items():
        setattr(row, key, value)

    touch(row)
    return True


def _resolve_uid(model, uid):
    if uid is None:
        return None
    return db.session.execute(
        sa.select(model.id)
        .where(model.user_id == current_user.id, model.uid == uid)
        .execution_options(**{INCLUDE_TOMBSTONES: True})
    ).scalar_one_or_none()


def _slot_clash(slot_date, slot, uid, moving=frozenset()):
    """A different project already holds this slot.

    Not a stale revision - both devices were working from the same picture and
    both were entitled to book. Only one row can hold (user, date, slot), so the
    other comes back as a question.
    """
    if slot_date is None or slot is None:
        return None

    clash = db.session.execute(
        sa.select(ProjectDaySlot).where(
            ProjectDaySlot.user_id == current_user.id,
            ProjectDaySlot.slot_date == slot_date,
            ProjectDaySlot.slot == slot,
            ProjectDaySlot.uid != uid,
            ProjectDaySlot.deleted_at.is_(None),
        )
    ).scalars().first()

    # A row leaving this spot in the same push is not in the way.
    if clash is not None and clash.uid in moving:
        return None
    return clash


def _park_moving_bookings(operations):
    """Mark every booking that is changing places as deleted, for now.

    Returns the rows to bring back once all of them have been put down.
    """
    entity = ENTITIES["day_slot"]
    parked = []

    for operation in operations:
        if operation.get("op") != "update":
            continue

        row = _existing(entity, operation.get("uid"))
        if row is None or row.deleted_at is not None:
            continue

        fields = operation.get("fields") or {}
        moves = (
            "slot_date" in fields and str(fields["slot_date"]) != str(row.slot_date)
        ) or ("slot" in fields and fields["slot"] != row.slot)

        if moves:
            row.deleted_at = utc_now()
            parked.append(row)

    if parked:
        db.session.flush()
    return parked


def _duplicate_booking():
    """A live (date, slot) held twice, after everything in the push was applied.

    The per-operation check lets a swap through by design; this is what still
    refuses two bookings that genuinely want the same spot. The database's
    partial unique index would catch it too, but as an IntegrityError - a 500
    where the client needs to be told which booking to settle.
    """
    duplicate = db.session.execute(
        sa.select(ProjectDaySlot.slot_date, ProjectDaySlot.slot)
        .where(
            ProjectDaySlot.user_id == current_user.id,
            ProjectDaySlot.deleted_at.is_(None),
        )
        .group_by(ProjectDaySlot.slot_date, ProjectDaySlot.slot)
        .having(sa.func.count() > 1)
    ).first()

    return duplicate


@api_bp.route("/export")
@login_required
def export():
    """Everything this account holds, in one response.

    Insurance rather than a feature: once the server stops rendering pages, this
    is the only way to reach the data without a shell on the machine.
    """
    uid_by_id = _reference_maps(current_user.id)
    payload = {}
    for name in PUSH_ORDER:
        entity = ENTITIES[name]
        rows = db.session.execute(
            sa.select(entity.model).where(entity.model.user_id == current_user.id)
        ).scalars().all()
        payload[name] = [serialise(entity, row, uid_by_id) for row in rows]

    return jsonify(
        {
            "ok": True,
            "user": {"username": current_user.username, "email": current_user.email},
            "exported_at": to_json(db.session.execute(sa.select(sa.func.now())).scalar()),
            "data": payload,
        }
    )
