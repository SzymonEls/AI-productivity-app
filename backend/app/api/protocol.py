"""What the wire carries, and how it maps onto the tables.

Two rules shape everything here.

References travel as uid, never as a primary key. A client that has been
offline invented its own identifiers; it has never seen a row id and must never
depend on one, or a booking created offline could not name the project it
belongs to until after the project had reached the server.

Values travel raw. Today's JSON endpoints hand back finished sentences -
"2 h 15 m", "Booked for Tuesday", rendered Markdown - because a server-rendered
page had no use for anything else. A local copy has to compute those itself, in
its own locale and time zone, so what crosses is the date and the integer.
"""

from datetime import date, datetime, timezone

from ..models import (
    Project,
    ProjectDaySlot,
    ProjectTimeEntry,
    ProjectTimelineGroup,
    ProjectTimelineItem,
)


class Entity:
    """One synchronised table, described once for both directions."""

    def __init__(self, name, model, fields, references=None):
        self.name = name
        self.model = model
        self.fields = fields
        # Incoming key -> (column on the row, model the uid belongs to)
        self.references = references or {}


ENTITIES = {
    entity.name: entity
    for entity in (
        Entity(
            "project",
            Project,
            (
                "title",
                "short_goal",
                "frequency",
                "long_goal",
                "archived_long_goal",
                "daily_target_minutes",
                "is_starred",
                "is_private",
                "is_archived",
            ),
        ),
        Entity(
            "timeline_group",
            ProjectTimelineGroup,
            ("name", "position", "is_backlog"),
        ),
        Entity(
            "timeline_item",
            ProjectTimelineItem,
            ("item_type", "title", "body", "is_private", "position"),
            {
                "group_uid": ("group_id", ProjectTimelineGroup),
                "project_uid": ("project_id", Project),
            },
        ),
        Entity(
            "day_slot",
            ProjectDaySlot,
            ("slot_date", "slot", "is_done"),
            {"project_uid": ("project_id", Project)},
        ),
        Entity(
            "time_entry",
            ProjectTimeEntry,
            ("started_at", "ended_at", "description", "project_title_snapshot"),
            {"project_uid": ("project_id", Project)},
        ),
    )
}

# Parents before children. A push may carry a project and the booking that
# names it in the same batch, created seconds apart on a device with no
# network; the project has to exist before the booking can resolve it.
PUSH_ORDER = ("project", "timeline_group", "timeline_item", "day_slot", "time_entry")


def to_json(value):
    """Render one stored value for the wire."""
    if isinstance(value, datetime):
        # Stored naive UTC throughout - say so explicitly rather than letting
        # the client guess at a bare timestamp.
        return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    return value


def from_json(column, value):
    """Turn one incoming value into what the column stores."""
    if value is None:
        return None

    python_type = getattr(column.type, "python_type", None)

    if python_type is datetime:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        # Naive UTC in the database; anything offset-aware is converted, not
        # truncated, or an hour would go missing twice a year.
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed

    if python_type is date:
        return date.fromisoformat(str(value))

    if python_type is bool:
        return bool(value)

    if python_type is int:
        return int(value)

    return value


def serialise(entity, row, uid_by_id):
    """Describe one row the way the client stores it."""
    payload = {
        "uid": row.uid,
        "rev": row.rev,
        "deleted": row.deleted_at is not None,
        "updated_at": to_json(row.updated_at),
    }

    if row.deleted_at is not None:
        # A tombstone carries nothing else. The content columns were emptied
        # when it was deleted, and the client only needs to know it is gone.
        return payload

    for field in entity.fields:
        payload[field] = to_json(getattr(row, field))

    for key, (column_name, _model) in entity.references.items():
        payload[key] = uid_by_id.get(column_name, {}).get(getattr(row, column_name))

    return payload
