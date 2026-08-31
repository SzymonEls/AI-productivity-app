"""The synchronisation API, from the outside."""

from datetime import date, timedelta

from tests.conftest import op


PROJECT_FIELDS = dict(
    title="Offline project",
    short_goal="made without a network",
    frequency="daily",
    long_goal="# Plan\n\n- a step\n",
    archived_long_goal="",
)


def test_a_row_created_offline_arrives_with_its_own_identity(app, sync):
    from app.models import Project

    response = sync.push(op("project", "01OFFLINEPROJECTAAAAAAAAAA", **PROJECT_FIELDS))
    body = response.get_json()

    assert response.status_code == 200, body
    assert body["applied"] == ["01OFFLINEPROJECTAAAAAAAAAA"]
    assert body["conflicts"] == []

    stored = Project.query.filter_by(uid="01OFFLINEPROJECTAAAAAAAAAA").one()
    assert stored.title == "Offline project"
    assert stored.rev == body["rev"]


def test_a_child_can_name_a_parent_from_the_same_batch(app, sync):
    """The whole reason references travel as uid: neither row has an id yet."""
    from app.models import ProjectDaySlot

    when = (date.today() + timedelta(days=2)).isoformat()
    response = sync.push(
        op("project", "01PARENTAAAAAAAAAAAAAAAAAA", **PROJECT_FIELDS),
        op(
            "day_slot",
            "01CHILDAAAAAAAAAAAAAAAAAAA",
            project_uid="01PARENTAAAAAAAAAAAAAAAAAA",
            slot_date=when,
            slot="B",
        ),
    )
    body = response.get_json()

    assert body["conflicts"] == [], body
    booking = ProjectDaySlot.query.filter_by(uid="01CHILDAAAAAAAAAAAAAAAAAAA").one()
    assert booking.project.title == "Offline project"


def test_pull_reports_what_push_stored(app, sync):
    sync.push(op("project", "01PULLMEAAAAAAAAAAAAAAAAAA", **PROJECT_FIELDS))

    body = sync.changes(since=0).get_json()
    projects = body["changes"]["project"]

    assert [p["uid"] for p in projects] == ["01PULLMEAAAAAAAAAAAAAAAAAA"]
    assert projects[0]["title"] == "Offline project"
    assert projects[0]["deleted"] is False
    # Raw values, not sentences the server built.
    assert projects[0]["is_starred"] is False


def test_pull_is_incremental(app, sync):
    first = sync.push(op("project", "01FIRSTAAAAAAAAAAAAAAAAAAA", **PROJECT_FIELDS))
    cursor = first.get_json()["rev"]

    sync.push(op("project", "01SECONDAAAAAAAAAAAAAAAAAA", **PROJECT_FIELDS))

    body = sync.changes(since=cursor).get_json()
    assert [p["uid"] for p in body["changes"]["project"]] == ["01SECONDAAAAAAAAAAAAAAAAAA"]


def test_a_deletion_travels_as_a_tombstone(app, sync):
    created = sync.push(op("project", "01GONEAAAAAAAAAAAAAAAAAAAA", **PROJECT_FIELDS))
    cursor = created.get_json()["rev"]

    sync.push(op("project", "01GONEAAAAAAAAAAAAAAAAAAAA", kind="delete", base_rev=cursor))

    body = sync.changes(since=cursor).get_json()
    tombstone = body["changes"]["project"][0]

    assert tombstone["uid"] == "01GONEAAAAAAAAAAAAAAAAAAAA"
    assert tombstone["deleted"] is True
    assert "title" not in tombstone, "a tombstone carries nothing that was written"


def test_an_edit_on_a_version_the_server_moved_past_is_a_conflict(app, sync):
    created = sync.push(op("project", "01RACEAAAAAAAAAAAAAAAAAAAA", **PROJECT_FIELDS))
    first_rev = created.get_json()["rev"]

    # Another device gets there first.
    sync.push(op("project", "01RACEAAAAAAAAAAAAAAAAAAAA", kind="update",
                 base_rev=first_rev, title="Renamed elsewhere"))

    # This one was still looking at the older version.
    response = sync.push(op("project", "01RACEAAAAAAAAAAAAAAAAAAAA", kind="update",
                            base_rev=first_rev, title="Renamed here"))
    body = response.get_json()

    assert body["applied"] == []
    conflict = body["conflicts"][0]
    assert conflict["reason"] == "stale"
    assert conflict["server"]["title"] == "Renamed elsewhere"
    assert conflict["client"]["fields"]["title"] == "Renamed here"

    from app.models import Project
    assert Project.query.filter_by(uid="01RACEAAAAAAAAAAAAAAAAAAAA").one().title == "Renamed elsewhere"


def test_two_devices_booking_the_same_slot_is_a_conflict(app, sync):
    """Neither is stale - both were entitled to book. Only one row can win."""
    when = (date.today() + timedelta(days=3)).isoformat()

    sync.push(
        op("project", "01AAAAAAAAAAAAAAAAAAAAAAAA", **dict(PROJECT_FIELDS, title="alpha")),
        op("project", "01BBBBBBBBBBBBBBBBBBBBBBBB", **dict(PROJECT_FIELDS, title="beta")),
        op("day_slot", "01SLOTONEAAAAAAAAAAAAAAAAA",
           project_uid="01AAAAAAAAAAAAAAAAAAAAAAAA", slot_date=when, slot="A"),
    )

    response = sync.push(
        op("day_slot", "01SLOTTWOAAAAAAAAAAAAAAAAA",
           project_uid="01BBBBBBBBBBBBBBBBBBBBBBBB", slot_date=when, slot="A")
    )
    body = response.get_json()

    assert body["applied"] == []
    conflict = body["conflicts"][0]
    assert conflict["reason"] == "slot_taken"
    assert conflict["server"]["uid"] == "01SLOTONEAAAAAAAAAAAAAAAAA"


def test_one_conflict_does_not_hold_up_the_rest_of_the_queue(app, sync):
    created = sync.push(op("project", "01KEEPAAAAAAAAAAAAAAAAAAAA", **PROJECT_FIELDS))
    rev = created.get_json()["rev"]
    sync.push(op("project", "01KEEPAAAAAAAAAAAAAAAAAAAA", kind="update",
                 base_rev=rev, title="moved on"))

    response = sync.push(
        op("project", "01KEEPAAAAAAAAAAAAAAAAAAAA", kind="update", base_rev=rev, title="stale"),
        op("project", "01FRESHAAAAAAAAAAAAAAAAAAA", **PROJECT_FIELDS),
    )
    body = response.get_json()

    assert body["applied"] == ["01FRESHAAAAAAAAAAAAAAAAAAA"]
    assert [c["uid"] for c in body["conflicts"]] == ["01KEEPAAAAAAAAAAAAAAAAAAAA"]


def test_a_cursor_below_the_floor_is_told_to_start_over(app, client, sync):
    from app.api.pruning import prune_tombstones
    from app.extensions import db
    from app.models import SyncState
    import sqlalchemy as sa

    created = sync.push(op("project", "01OLDAAAAAAAAAAAAAAAAAAAAA", **PROJECT_FIELDS))
    stale_cursor = created.get_json()["rev"]
    sync.push(op("project", "01OLDAAAAAAAAAAAAAAAAAAAAA", kind="delete", base_rev=stale_cursor))

    user_id = db.session.execute(sa.select(SyncState.user_id)).scalar_one()
    # Retention decides when a tombstone expires; force only skips the throttle.
    app.config["TOMBSTONE_RETENTION_DAYS"] = 0
    assert prune_tombstones(user_id, force=True) == 1

    refused = sync.changes(since=stale_cursor)
    assert refused.status_code == 409
    assert refused.get_json()["reason"] == "cursor_too_old"

    # Starting over is always allowed, and the deleted project is simply absent.
    fresh = sync.changes(since=0).get_json()
    assert fresh["changes"]["project"] == []


def test_a_write_without_the_token_is_refused(app, sync):
    from app.models import Project

    response = sync.push(
        op("project", "01FORGEDAAAAAAAAAAAAAAAAAA", **PROJECT_FIELDS), token=False
    )

    assert response.status_code == 403
    assert response.get_json()["reason"] == "csrf"
    assert Project.query.filter_by(uid="01FORGEDAAAAAAAAAAAAAAAAAA").first() is None


def test_a_write_with_the_wrong_token_is_refused(app, sync):
    response = sync.push(
        op("project", "01WRONGAAAAAAAAAAAAAAAAAAA", **PROJECT_FIELDS),
        token="not-the-right-token",
    )
    assert response.status_code == 403


def test_reading_needs_no_token(app, client):
    """Pull is a GET and changes nothing; requiring a token there buys nothing."""
    assert client.get("/api/sync/changes?since=0").status_code == 200


def test_logout_is_not_a_link(app, client):
    """A GET that signs the user out is a link another site can aim at."""
    assert client.get("/auth/logout").status_code == 405
    assert client.post("/auth/logout").status_code in (302, 303)


def test_two_bookings_can_swap_places_in_one_push(app, sync):
    """A swap is two updates that each land where the other is leaving.

    Checked one at a time they collide; the row on its way out is not a blocker.
    """
    from app.models import ProjectDaySlot

    when = (date.today() + timedelta(days=6)).isoformat()
    sync.push(
        op("project", "01SWAPAAAAAAAAAAAAAAAAAAAA", **dict(PROJECT_FIELDS, title="alpha")),
        op("project", "01SWAPBBBBBBBBBBBBBBBBBBBB", **dict(PROJECT_FIELDS, title="beta")),
        op("day_slot", "01SWAPSLOTAAAAAAAAAAAAAAAA",
           project_uid="01SWAPAAAAAAAAAAAAAAAAAAAA", slot_date=when, slot="A"),
        op("day_slot", "01SWAPSLOTBBBBBBBBBBBBBBBB",
           project_uid="01SWAPBBBBBBBBBBBBBBBBBBBB", slot_date=when, slot="B"),
    )

    first = ProjectDaySlot.query.filter_by(uid="01SWAPSLOTAAAAAAAAAAAAAAAA").one()
    second = ProjectDaySlot.query.filter_by(uid="01SWAPSLOTBBBBBBBBBBBBBBBB").one()

    response = sync.push(
        op("day_slot", "01SWAPSLOTAAAAAAAAAAAAAAAA", kind="update",
           base_rev=first.rev, slot="B"),
        op("day_slot", "01SWAPSLOTBBBBBBBBBBBBBBBB", kind="update",
           base_rev=second.rev, slot="A"),
    )
    body = response.get_json()

    assert body["conflicts"] == [], body
    assert len(body["applied"]) == 2

    from app.extensions import db
    db.session.expire_all()
    assert ProjectDaySlot.query.filter_by(uid="01SWAPSLOTAAAAAAAAAAAAAAAA").one().slot == "B"
    assert ProjectDaySlot.query.filter_by(uid="01SWAPSLOTBBBBBBBBBBBBBBBB").one().slot == "A"


def test_a_push_that_would_double_book_saves_nothing(app, sync):
    """The sweep after the loop: a swap is fine, two rows wanting one spot is not."""
    from app.models import ProjectDaySlot

    when = (date.today() + timedelta(days=7)).isoformat()
    sync.push(
        op("project", "01DUPEAAAAAAAAAAAAAAAAAAAA", **dict(PROJECT_FIELDS, title="alpha")),
        op("project", "01DUPEBBBBBBBBBBBBBBBBBBBB", **dict(PROJECT_FIELDS, title="beta")),
        op("day_slot", "01DUPESLOTAAAAAAAAAAAAAAAA",
           project_uid="01DUPEAAAAAAAAAAAAAAAAAAAA", slot_date=when, slot="A"),
        op("day_slot", "01DUPESLOTBBBBBBBBBBBBBBBB",
           project_uid="01DUPEBBBBBBBBBBBBBBBBBBBB", slot_date=when, slot="B"),
    )

    first = ProjectDaySlot.query.filter_by(uid="01DUPESLOTAAAAAAAAAAAAAAAA").one()
    second = ProjectDaySlot.query.filter_by(uid="01DUPESLOTBBBBBBBBBBBBBBBB").one()
    original = second.slot

    # Both want slot A, and neither is leaving it.
    response = sync.push(
        op("day_slot", "01DUPESLOTBBBBBBBBBBBBBBBB", kind="update",
           base_rev=second.rev, slot="A"),
        op("day_slot", "01DUPESLOTAAAAAAAAAAAAAAAA", kind="update",
           base_rev=first.rev, slot="A"),
    )

    assert response.status_code == 409
    assert response.get_json()["reason"] == "slot_taken"

    from app.extensions import db
    db.session.expire_all()
    assert ProjectDaySlot.query.filter_by(uid="01DUPESLOTBBBBBBBBBBBBBBBB").one().slot == original
