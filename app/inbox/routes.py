"""
The inbox: thoughts captured before it was decided where they belong.

Capturing and filing are two moments, and the app now keeps them apart. An item
arrives with nothing but its text - from the box the PWA shortcut opens, or from
the + beside "Today" - and waits on the home page until a project is chosen for
it. Choosing appends the text to that project's thoughts
and deletes the row, so the inbox is a queue rather than a second copy of
anything.

The other way out is the ×, which throws the item away without filing it. It is
not a nicety: capture is deliberately careless - one tap and a sentence, with
nothing asked and nothing checked - so there has to be somewhere for the
misfires to go. Without it a stray item would sit in the widget forever, since
the only alternative would be filing nonsense into a real project.

capture_page() is the odd one out here: it is not the inbox, it is the page the
Android launcher opens from the app icon's shortcut menu. All it holds is the
box and the button, because the shortcut exists to skip the rest - landing on
the field rather than on the home page is the whole of what it buys. See point
19 in ARCHITECTURE.md.
"""

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..models import INBOX_ITEM_MAX_LENGTH, InboxItem, Project


inbox_bp = Blueprint("inbox", __name__, url_prefix="/inbox")


def _get_user_item_or_404(item_id):
    """Ensure users can only reach their own inbox items."""

    return InboxItem.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()


def _payload():
    """Read the body whether it arrives as JSON or as a form.

    The pages post JSON; a form is what one without JavaScript would send. Both
    are cheap to accept, and it keeps the endpoint usable from curl or from a
    shortcut app on the phone.
    """
    return request.get_json(silent=True) or request.form


def serialize_item(item):
    """One item as the home page's widget wants it."""

    return {"id": item.id, "body": item.body}


def items_for(user_id):
    """Everything waiting in one user's inbox, newest first.

    Newest first because the inbox is emptied from the top: the thought you
    dictated on the way home is the one you still remember the context of.
    """
    return (
        InboxItem.query.filter_by(user_id=user_id)
        .order_by(InboxItem.created_at.desc(), InboxItem.id.desc())
        .all()
    )


def filing_projects(user_id):
    """The projects an item may be filed into, in the order the picker shows them.

    Archived ones are left out for the same reason they are out of the block
    picker: you file a thought against something you are still taking on. A
    thought about a project you have put down is one you no longer need to have.
    """
    return (
        Project.query.filter_by(user_id=user_id, is_archived=False)
        .order_by(Project.title.asc())
        .all()
    )


@inbox_bp.route("/capture")
@login_required
def capture_page():
    """The target of the "Add to inbox" shortcut in the app icon's menu.

    Deliberately almost empty: a box, a button, and no plan to read first. The
    shortcut is worth having because it opens here rather than on the home page,
    and because the keyboard it raises has a mic on it.
    """
    return render_template("inbox/capture.html")


@inbox_bp.route("", methods=["POST"])
@login_required
def add_item():
    """Put one captured thought in the inbox.

    Answers the box on the capture page and the + on the home page alike; they
    differ only in how you got to them.
    """
    body = (_payload().get("body") or "").strip()
    if not body:
        return jsonify({"ok": False, "message": "Write something first."}), 400
    if len(body) > INBOX_ITEM_MAX_LENGTH:
        return (
            jsonify(
                {
                    "ok": False,
                    "message": f"A thought is at most {INBOX_ITEM_MAX_LENGTH} characters.",
                }
            ),
            400,
        )

    item = InboxItem(user_id=current_user.id, body=body)
    db.session.add(item)

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "Failed to save the thought."}), 500

    return jsonify({"ok": True, "message": "Added to the inbox.", "item": serialize_item(item)})


@inbox_bp.route("/<int:item_id>/file", methods=["POST"])
@login_required
def file_item(item_id):
    """Append one inbox item to a project's thoughts and drop it from the inbox.

    A blank line goes in between, so a filed thought reads as its own paragraph
    rather than running into the last sentence of whatever was there. It is
    still only text: ``short_goal`` has no structure to respect, and this
    deliberately does not invent one - no date stamp, no bullet, nothing that
    would have to be parsed back out later.

    The row goes in the same transaction as the append. Filing is a move, and
    the one outcome worth ruling out is a thought that is in a project and still
    in the inbox - or in neither.
    """
    item = _get_user_item_or_404(item_id)

    project_id = _payload().get("project_id")
    try:
        project_id = int(project_id)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "Pick a project."}), 400

    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    if project is None:
        return jsonify({"ok": False, "message": "Unknown project."}), 404

    existing = (project.short_goal or "").rstrip()
    project.short_goal = f"{existing}\n\n{item.body}" if existing else item.body
    db.session.delete(item)

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "Failed to file the thought."}), 500

    return jsonify(
        {
            "ok": True,
            "message": f"Filed under {project.title}.",
            "project": {"id": project.id, "title": project.title},
        }
    )


@inbox_bp.route("/<int:item_id>/delete", methods=["POST"])
@login_required
def delete_item(item_id):
    """Throw one item away without filing it anywhere.

    An item that has already gone counts as deleted rather than as an error.
    The × is applied to the page before the request goes out, the way the day
    notes' is, so a second click must not produce a failure the page then has to
    undo - and the outcome the caller asked for is true either way.
    """
    item = InboxItem.query.filter_by(id=item_id, user_id=current_user.id).first()
    if item is None:
        return jsonify({"ok": True, "message": "That thought is already gone."})

    db.session.delete(item)

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "Failed to remove the thought."}), 500

    return jsonify({"ok": True, "message": "Removed from the inbox."})
