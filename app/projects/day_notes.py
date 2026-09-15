"""
A day's notes: the short list under the three blocks on a calendar sheet.

Kept beside slots.py rather than inside it. A note shares the sheet with the
blocks and travels with them when a day is taken off, but it is not a booking:
it belongs to no project, obeys none of the "one block today and one later"
arithmetic, and a day takes as many as get written.

Unlike the blocks, the list is live on a past sheet too. The archive refuses
every booking change because nothing about a day that has been can still be
planned - but a note about that day is a record of it, and a record is often
written afterwards. It is the same reason the archive keeps its ✓.
"""

from datetime import timedelta

from ..extensions import db
from ..models import DAY_NOTE_MAX_LENGTH, DayNote


def notes_from(user_id, start_day, end_day):
    """``{date: [DayNote, ...]}`` across a range of days, in one query.

    The calendar pages draw weeks at a time, so they ask once for the whole
    window the way they already do for the bookings - see slots_from().
    """
    entries = (
        DayNote.query.filter(
            DayNote.user_id == user_id,
            DayNote.note_date >= start_day,
            DayNote.note_date <= end_day,
        )
        .order_by(DayNote.note_date.asc(), DayNote.created_at.asc(), DayNote.id.asc())
        .all()
    )

    by_date = {}
    for entry in entries:
        by_date.setdefault(entry.note_date, []).append(entry)
    return by_date


def add_note(user_id, day, body):
    """Write one note against a day. Returns ``(note, message)``; the caller commits.

    ``note`` is None when there was nothing to save. Any day may be noted,
    including one long gone: see the module docstring.
    """
    body = (body or "").strip()
    if not body:
        return None, "Write something first."
    if len(body) > DAY_NOTE_MAX_LENGTH:
        return None, f"A note is at most {DAY_NOTE_MAX_LENGTH} characters."

    note = DayNote(user_id=user_id, note_date=day, body=body)
    db.session.add(note)
    return note, "Note added."


def update_note(user_id, note_id, body):
    """Rewrite one note. Returns ``(note, message)``; the caller commits.

    ``note`` is None when nothing was written or the note has gone. Emptying a
    note leaves it as it was rather than deleting it: a line cleared by accident
    is not the same gesture as reaching for the ×, and only one of the two is
    meant to lose the text.
    """
    body = (body or "").strip()
    if not body:
        return None, "Write something first."
    if len(body) > DAY_NOTE_MAX_LENGTH:
        return None, f"A note is at most {DAY_NOTE_MAX_LENGTH} characters."

    note = DayNote.query.filter_by(id=note_id, user_id=user_id).first()
    if note is None:
        return None, "That note is gone."

    note.body = body
    return note, "Note saved."


def delete_note(user_id, note_id):
    """Remove one note. Returns ``(ok, message)``; the caller commits.

    A note that is already gone counts as removed: the × is applied to the page
    before the request goes out, so a double click must not turn into an error
    the page then has to undo.
    """
    note = DayNote.query.filter_by(id=note_id, user_id=user_id).first()
    if note is None:
        return True, "That note is already gone."

    db.session.delete(note)
    return True, "Note removed."


def shift_notes_forward(user_id, from_day, days=1):
    """Move the notes from ``from_day`` on ``days`` days later, and count them.

    The other half of a day off. A note on a day still to come is part of that
    day's plan, so it follows the blocks rather than staying behind on a day
    that no longer happens. The caller commits.

    Nothing holds a note back the way a finished session holds its block back -
    a note has no such state, and two notes may share a day - so this is a plain
    date change with no collision to avoid.
    """
    if days < 1:
        return 0

    entries = DayNote.query.filter(
        DayNote.user_id == user_id, DayNote.note_date >= from_day
    ).all()
    for entry in entries:
        entry.note_date = entry.note_date + timedelta(days=days)
    return len(entries)

