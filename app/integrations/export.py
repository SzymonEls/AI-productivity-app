"""
Everything on the account as a zip of Markdown files, one per project.

The "Export everything" button on the Integrations page. The zip is for reading
the data somewhere else - choosing which parts to hand to an assistant, keeping
a copy to look through - not a backup: nothing in it can be imported back.

Each project is one file with its data on top - front matter, then its sessions
ahead and behind and the time tracked on it - and its plan underneath, exactly as
written. What belongs to no project has a file of its own: tasks, day notes, the
inbox, mood, the timeline, and every tracked entry in one list.

Calendar addresses are left out on purpose. A private iCal URL is a password to
that calendar, and a zip made to be passed around must not carry one; the
calendars are listed by name only.
"""

import io
import re
import unicodedata
import zipfile
from collections import defaultdict
from datetime import datetime, timezone

from ..models import (
    CalendarFeed,
    DayNote,
    InboxItem,
    MoodRating,
    Project,
    ProjectDaySlot,
    ProjectTimeEntry,
    ProjectTimelineGroup,
    Task,
)
from ..projects.slots import (
    DEADLINE_RULE_DAY_BEFORE,
    DEADLINE_RULE_LABELS,
    DEADLINE_RULE_SAME_DAY,
    sessions_per_week_label,
    today_local,
)
from ..tasks.routes import repeat_label
from ..time_tracking.service import app_timezone, ensure_utc, entry_elapsed_seconds


SLUG_MAX_LENGTH = 60


def build_export(user):
    """The zip as bytes, and the name it is downloaded under."""
    today = today_local()
    root = f"productivity-export-{today.isoformat()}"
    data = _ExportData(user.id)

    files = {"README.md": _readme(user, today, data)}
    slugs = _project_slugs(data.projects)
    for project in data.projects:
        folder = "projects/archived" if project.is_archived else "projects"
        files[f"{folder}/{slugs[project.id]}.md"] = _project_file(project, data, today)
    files["tasks.md"] = _tasks_file(data.tasks, today)
    files["day-notes.md"] = _day_notes_file(data.notes)
    files["inbox.md"] = _inbox_file(data.inbox)
    files["mood.md"] = _mood_file(data.moods)
    files["time-tracking.md"] = _time_file(data.entries)
    files["timeline.md"] = _timeline_file(data.timeline_groups)
    files["calendars.md"] = _calendars_file(data.feeds)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(f"{root}/{path}", content)
    return f"{root}.zip", buffer.getvalue()


class _ExportData:
    """Every row the export reads, fetched once per table."""

    def __init__(self, user_id):
        self.projects = (
            Project.query.filter_by(user_id=user_id)
            .order_by(Project.is_archived, Project.title)
            .all()
        )
        self.slots_by_project = defaultdict(list)
        for slot in (
            ProjectDaySlot.query.filter_by(user_id=user_id)
            .order_by(ProjectDaySlot.slot_date, ProjectDaySlot.slot)
            .all()
        ):
            self.slots_by_project[slot.project_id].append(slot)
        self.entries = (
            ProjectTimeEntry.query.filter_by(user_id=user_id)
            .order_by(ProjectTimeEntry.started_at.desc())
            .all()
        )
        self.entries_by_project = defaultdict(list)
        for entry in self.entries:
            if entry.project_id is not None:
                self.entries_by_project[entry.project_id].append(entry)
        self.tasks = Task.query.filter_by(user_id=user_id).all()
        self.notes = (
            DayNote.query.filter_by(user_id=user_id)
            .order_by(DayNote.note_date, DayNote.id)
            .all()
        )
        self.inbox = (
            InboxItem.query.filter_by(user_id=user_id).order_by(InboxItem.created_at).all()
        )
        self.moods = (
            MoodRating.query.filter_by(user_id=user_id).order_by(MoodRating.rating_date).all()
        )
        self.timeline_groups = (
            ProjectTimelineGroup.query.filter_by(user_id=user_id)
            .order_by(ProjectTimelineGroup.is_backlog, ProjectTimelineGroup.position)
            .all()
        )
        self.feeds = CalendarFeed.query.filter_by(user_id=user_id).order_by(CalendarFeed.name).all()


# --- projects ---------------------------------------------------------------


def _project_file(project, data, today):
    slots = data.slots_by_project.get(project.id, [])
    ahead = [slot for slot in slots if slot.slot_date >= today]
    behind = [slot for slot in reversed(slots) if slot.slot_date < today]
    names = {member.id: member.title for member in project.members} if project.is_group else {}

    lines = ["---"]
    lines += _front_matter(_project_meta(project))
    lines += ["---", "", f"# {project.title}", ""]
    if project.short_goal.strip():
        lines += [project.short_goal.strip(), ""]

    group = project.group if project.group_id else None
    if group is not None:
        lines += [
            f'Planned through the group "{group.title}": its sessions are listed in that '
            "group's file, not here.",
            "",
        ]

    lines += ["## Sessions ahead", ""]
    lines += _sessions_table(ahead, names, today) if ahead else ["None planned.", ""]
    lines += ["## Sessions behind", ""]
    lines += _sessions_table(behind, names, today) if behind else ["None yet.", ""]

    lines += ["## Tracked time", ""]
    lines += _project_time(data.entries_by_project.get(project.id, []))

    lines += ["---", "", "# Plan", ""]
    lines += [project.long_goal.strip() or "(empty)", ""]
    if project.archived_long_goal.strip():
        lines += ["---", "", "# Archived plan sections", "", project.archived_long_goal.strip(), ""]
    return "\n".join(lines)


def _project_meta(project):
    """The front matter of a project's file, in the order it is written."""
    meta = {
        "title": project.title,
        "status": "archived" if project.is_archived else "active",
        "starred": project.is_starred,
        "private": project.is_private,
        "problematic": project.is_problematic,
        "sessions_per_week": project.sessions_per_week,
        "rhythm": sessions_per_week_label(project.sessions_per_week),
    }
    if project.session_deadline is not None:
        meta["deadline"] = project.session_deadline
        if project.session_deadline_time is not None:
            meta["deadline_time"] = project.session_deadline_time.strftime("%H:%M")
        rule = DEADLINE_RULE_DAY_BEFORE if project.session_deadline_day_before else DEADLINE_RULE_SAME_DAY
        meta["deadline_session"] = DEADLINE_RULE_LABELS[rule]
    if project.waiting_for is not None:
        meta["waiting_for"] = project.waiting_for.title
        if project.waiting_for_note:
            meta["waiting_for_milestone"] = project.waiting_for_note
    if project.is_group:
        meta["group"] = True
        meta["members"] = [member.title for member in project.members]
    elif project.group is not None:
        meta["in_group"] = project.group.title
    meta["created"] = _local(project.created_at).date()
    return meta


def _sessions_table(slots, member_names, today):
    head = "| Date | Day | Block | Status |"
    rule = "|---|---|---|---|"
    if member_names:
        head = "| Date | Day | Block | Status | Projects done |"
        rule = "|---|---|---|---|---|"
    rows = [head, rule]
    for slot in slots:
        cells = [
            slot.slot_date.isoformat(),
            slot.slot_date.strftime("%a"),
            slot.slot,
            _session_status(slot, today),
        ]
        if member_names:
            done = [member_names[i] for i in (slot.done_member_ids or []) if i in member_names]
            cells.append(", ".join(done))
        rows.append("| " + " | ".join(_cell(cell) for cell in cells) + " |")
    return rows + [""]


def _session_status(slot, today):
    if slot.is_done:
        return "done"
    if slot.is_failed:
        return "failed"
    return "planned" if slot.slot_date >= today else "not ticked off"


def _project_time(entries):
    if not entries:
        return ["None.", ""]
    total = sum(entry_elapsed_seconds(entry) for entry in entries)
    lines = [f"{_duration(total)} in {len(entries)} entries.", ""]
    lines += ["| Date | Start | End | Time | Note |", "|---|---|---|---|---|"]
    for entry in entries:
        lines.append(_entry_row(entry, with_project=False))
    return lines + [""]


def _project_slugs(projects):
    """A file name per project: its title in plain ASCII, unique within the zip."""
    taken = set()
    slugs = {}
    for project in projects:
        base = _slug(project.title) or f"project-{project.id}"
        slug, number = base, 2
        while slug in taken:
            slug = f"{base}-{number}"
            number += 1
        taken.add(slug)
        slugs[project.id] = slug
    return slugs


# --- everything else ----------------------------------------------------------


def _tasks_file(tasks, today):
    open_dated = sorted((t for t in tasks if not t.is_done and t.due_date), key=lambda t: t.due_date)
    open_undated = sorted((t for t in tasks if not t.is_done and not t.due_date), key=lambda t: t.id)
    done = sorted(
        (t for t in tasks if t.is_done),
        key=lambda t: t.done_at or datetime.min,
        reverse=True,
    )

    lines = ["# Tasks", ""]
    lines += ["## Open", ""]
    if open_dated or open_undated:
        lines += ["| Due | Day | Block | Task | Repeats | Note |", "|---|---|---|---|---|---|"]
        for task in open_dated + open_undated:
            due = task.due_date
            lines.append(
                "| "
                + " | ".join(
                    _cell(value)
                    for value in (
                        due.isoformat() if due else "",
                        due.strftime("%a") if due else "",
                        task.slot or "",
                        task.title,
                        repeat_label(task.repeat_rule) if task.repeat_rule else "",
                        "overdue" if due and due < today else "",
                    )
                )
                + " |"
            )
        lines.append("")
    else:
        lines += ["None.", ""]

    lines += ["## Done", ""]
    if done:
        lines += ["| Done on | Due | Task | Repeats |", "|---|---|---|---|"]
        for task in done:
            lines.append(
                "| "
                + " | ".join(
                    _cell(value)
                    for value in (
                        _local(task.done_at).date().isoformat() if task.done_at else "",
                        task.due_date.isoformat() if task.due_date else "",
                        task.title,
                        repeat_label(task.repeat_rule) if task.repeat_rule else "",
                    )
                )
                + " |"
            )
        lines.append("")
    else:
        lines += ["None.", ""]
    return "\n".join(lines)


def _day_notes_file(notes):
    lines = ["# Day notes", "", "The lines written under each day on the schedule.", ""]
    if not notes:
        return "\n".join(lines + ["None.", ""])
    by_day = defaultdict(list)
    for note in notes:
        by_day[note.note_date].append(note.body)
    for day in sorted(by_day):
        lines += [f"## {day.isoformat()} ({day.strftime('%a')})", ""]
        lines += [f"- {_one_line(body)}" for body in by_day[day]]
        lines.append("")
    return "\n".join(lines)


def _inbox_file(items):
    lines = ["# Inbox", "", "Thoughts captured and not yet filed into a project.", ""]
    if not items:
        return "\n".join(lines + ["Empty.", ""])
    for item in items:
        lines.append(f"- {_local(item.created_at).strftime('%Y-%m-%d %H:%M')} — {_one_line(item.body)}")
    return "\n".join(lines + [""])


def _mood_file(moods):
    lines = ["# Mood", "", "How each day felt, 1 (worst) to 5 (best).", ""]
    if not moods:
        return "\n".join(lines + ["Nothing rated.", ""])
    lines += ["| Date | Day | Mood |", "|---|---|---|"]
    for mood in moods:
        lines.append(f"| {mood.rating_date.isoformat()} | {mood.rating_date.strftime('%a')} | {mood.score} |")
    return "\n".join(lines + [""])


def _time_file(entries):
    lines = ["# Tracked time", ""]
    if not entries:
        return "\n".join(lines + ["Nothing tracked.", ""])
    totals = defaultdict(int)
    for entry in entries:
        totals[_entry_project(entry)] += entry_elapsed_seconds(entry)
    lines += ["## Totals", "", "| Project | Time |", "|---|---|"]
    for name, seconds in sorted(totals.items(), key=lambda item: -item[1]):
        lines.append(f"| {_cell(name)} | {_duration(seconds)} |")
    lines += ["", "## Entries", "", "| Date | Start | End | Time | Project | Note |", "|---|---|---|---|---|---|"]
    for entry in entries:
        lines.append(_entry_row(entry, with_project=True))
    return "\n".join(lines + [""])


def _timeline_file(groups):
    lines = ["# Timeline", "", "The columns of the Projects timeline, left to right, then the backlog.", ""]
    if not groups:
        return "\n".join(lines + ["Empty.", ""])
    for group in groups:
        name = "Backlog" if group.is_backlog else (group.name or "Untitled column")
        lines += [f"## {name}", ""]
        items = sorted(group.items, key=lambda item: item.position)
        if not items:
            lines += ["Empty.", ""]
            continue
        for item in items:
            if item.item_type == "project" and item.project is not None:
                lines.append(f"- Project: {item.project.title}")
            else:
                title = (item.title or "").strip() or "Note"
                body = _one_line(item.body or "")
                lines.append(f"- Note: {title}" + (f" — {body}" if body else ""))
        lines.append("")
    return "\n".join(lines)


def _calendars_file(feeds):
    lines = [
        "# Calendars",
        "",
        "Subscribed calendars by name. Their addresses are left out: a private iCal",
        "address gives anyone who holds it the whole calendar.",
        "",
    ]
    if not feeds:
        return "\n".join(lines + ["None.", ""])
    lines += ["| Calendar | Shown | Grouped |", "|---|---|---|"]
    for feed in feeds:
        lines.append(
            f"| {_cell(feed.name)} | {'yes' if feed.is_enabled else 'no'} | {'yes' if feed.is_grouped else 'no'} |"
        )
    return "\n".join(lines + [""])


def _readme(user, today, data):
    active = sum(1 for project in data.projects if not project.is_archived)
    archived = len(data.projects) - active
    return "\n".join(
        [
            "# Productivity app export",
            "",
            f"Exported on {today.isoformat()} for {user.username}.",
            "",
            "- `projects/` — one file per project: its data on top (front matter, sessions",
            "  ahead and behind, tracked time), then its plan exactly as written.",
            f"  {active} active, {archived} archived (in `projects/archived/`).",
            "- `tasks.md` — open tasks by day, then the done ones.",
            "- `day-notes.md` — the notes under each day of the schedule.",
            "- `inbox.md` — thoughts not yet filed into a project.",
            "- `mood.md` — the daily 1–5 rating.",
            "- `time-tracking.md` — every tracked entry, with totals per project.",
            "- `timeline.md` — the columns of the Projects timeline.",
            "- `calendars.md` — subscribed calendars by name (no addresses).",
            "",
            "Dates are days in the app's timezone; times are local. A session's block is",
            "A, B or C of its day.",
            "",
        ]
    )


# --- formatting ---------------------------------------------------------------


def _entry_row(entry, with_project):
    start = _local(entry.started_at)
    end = _local(entry.ended_at) if entry.ended_at else None
    cells = [
        start.date().isoformat(),
        start.strftime("%H:%M"),
        end.strftime("%H:%M") if end else "running",
        _duration(entry_elapsed_seconds(entry)),
    ]
    if with_project:
        cells.append(_entry_project(entry))
    cells.append(_one_line(entry.description or ""))
    return "| " + " | ".join(_cell(cell) for cell in cells) + " |"


def _entry_project(entry):
    if entry.project is not None:
        return entry.project.title
    return entry.project_title_snapshot or "(deleted project)"


def _local(value):
    """A stored UTC datetime as local time in CALENDAR_TIMEZONE."""
    return ensure_utc(value or datetime.now(timezone.utc)).astimezone(app_timezone())


def _duration(seconds):
    minutes = max(int(seconds or 0), 0) // 60
    hours, minutes = divmod(minutes, 60)
    if hours and minutes:
        return f"{hours} h {minutes} min"
    if hours:
        return f"{hours} h"
    return f"{minutes} min"


def _one_line(text):
    return " ".join(str(text).split())


def _cell(value):
    """A value made safe for one cell of a Markdown table."""
    return _one_line(value).replace("|", "\\|")


def _slug(title):
    ascii_title = (
        unicodedata.normalize("NFKD", title.replace("ł", "l").replace("Ł", "L"))
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")
    return slug[:SLUG_MAX_LENGTH].strip("-")


def _front_matter(meta):
    """YAML front matter lines for a flat dict of simple values."""
    lines = []
    for key, value in meta.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            lines += [f"  - {_yaml_value(item)}" for item in value]
        else:
            lines.append(f"{key}: {_yaml_value(value)}")
    return lines


def _yaml_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return f"{value:g}" if isinstance(value, float) else str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    text = _one_line(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'
