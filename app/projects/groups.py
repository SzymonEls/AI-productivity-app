"""
Groups of projects: several projects planned as one session.

A group is a ``Project`` with ``is_group`` set, so everything the schedule does
with a project - booking, moving, the red !, deadlines, the health score - it
does with a group unchanged. What is new is the session itself: a group's
booking is worked through member by member, and ``done_member_ids`` on it says
which members are finished, which is the "2/3" the blocks print. The session is
done once every member is.

A member stays an ordinary project. It can still have a session of its own,
booked from its page; it is only left out of the places that would otherwise
nag about it - the Not scheduled list and the picker - because the group is
what gets planned.
"""

from sqlalchemy import func

from ..extensions import db
from ..models import Project, ProjectDaySlot


def done_member_ids(booking):
    """The members finished in a group's session, as a set of ids."""
    if booking is None:
        return set()
    return {int(value) for value in (booking.done_member_ids or [])}


def group_progress(booking):
    """``(done, total)`` for a group's session, or None for any other booking.

    Counted over the group's active members only, so a member archived or
    taken out of the group since does not hold the count below its total.
    """
    if booking is None or booking.project is None or not booking.project.is_group:
        return None
    members = booking.project.active_members
    ids = {member.id for member in members}
    if booking.is_done:
        return len(ids), len(ids)
    return len(done_member_ids(booking) & ids), len(ids)


def group_progress_label(booking):
    """ "2/3" for a group's session, or "" for anything else."""
    progress = group_progress(booking)
    if progress is None or not progress[1]:
        return ""
    return f"{progress[0]}/{progress[1]}"


def group_heading(project):
    """What a group's block says under its title: its members, by name.

    A group's own plan is rarely where its session's work is, so the block
    names what the session is made of instead.
    """
    if project is None or not project.is_group:
        return ""
    members = project.active_members
    if not members:
        return "Group · no projects yet"
    return "Group · " + ", ".join(member.title for member in members)


def sync_members_with_done(booking):
    """Tick or clear every member when a group's whole session is ticked or reopened.

    The block's own done switch means the whole session, so it carries all the
    members with it - otherwise a session marked done could still read 1/3.
    """
    if booking is None or booking.project is None or not booking.project.is_group:
        return
    if booking.is_done:
        booking.done_member_ids = sorted(member.id for member in booking.project.active_members)
    else:
        booking.done_member_ids = []


def _meet_member_deadline(member):
    """A member finished in a group's session has had its session, as far as
    its own deadline and problematic flag are concerned - the same as
    ``meet_deadline`` does for a booking of its own."""
    member.session_deadline = None
    member.session_deadline_time = None
    member.session_deadline_day_before = False
    member.is_problematic = False


def set_member_done(user_id, group, member, day, done):
    """Mark one member finished in the group's session on ``day``, or not.

    Returns ``(ok, message, state)``; the caller commits. ``state`` carries
    ``member_done``, ``group_done`` and the ``progress`` label. The last member
    ticked finishes the group's session; unticking one reopens it.
    """
    from .slots import meet_deadline

    if not group.is_group:
        return False, "That project is not a group.", {}
    if member.group_id != group.id:
        return False, f"{member.title} is not in this group.", {}

    booking = ProjectDaySlot.query.filter_by(
        user_id=user_id, project_id=group.id, slot_date=day
    ).first()
    if booking is None:
        return False, "This group has no session today.", {}
    if booking.is_failed:
        return False, "Today's session of this group was marked failed.", {}

    member_ids = {project.id for project in group.active_members}
    finished = done_member_ids(booking) & member_ids
    if booking.is_done:
        # A session ticked done as a whole has every member finished.
        finished = set(member_ids)
    if done:
        finished.add(member.id)
        _meet_member_deadline(member)
    else:
        finished.discard(member.id)

    booking.done_member_ids = sorted(finished)
    was_done = bool(booking.is_done)
    booking.is_done = bool(member_ids) and finished >= member_ids
    if booking.is_done and not was_done:
        meet_deadline(booking)

    label = group_progress_label(booking)
    if booking.is_done and not was_done:
        message = f"{member.title} done — the group's session is finished."
    elif done:
        message = f"{member.title} done ({label})."
    else:
        message = f"{member.title} reopened ({label})."
    return True, message, {
        "member_done": member.id in finished,
        "group_done": bool(booking.is_done),
        "progress": label,
    }


def group_tabs(user_id, project, today):
    """The tab strip a group's page and its members' pages share, or None.

    Shown on a group and on a member of an active group. ``session`` is the
    group's booking today, when there is one: the tabs then say which members
    are finished in it, and the page offers to tick the one it is showing.
    """
    group = project if project.is_group else project.active_group
    if group is None:
        return None

    booking = ProjectDaySlot.query.filter_by(
        user_id=user_id, project_id=group.id, slot_date=today
    ).first()
    finished = done_member_ids(booking)
    if booking is not None and booking.is_done:
        finished = {member.id for member in group.active_members}

    return {
        "group": group,
        "current_id": project.id,
        "is_group_page": project.id == group.id,
        "session": booking,
        "session_open": booking is not None and not booking.is_failed,
        "progress": group_progress_label(booking) if booking is not None else "",
        "members": [
            {
                "project": member,
                "is_done": member.id in finished,
            }
            for member in group.active_members
        ],
        "current_done": project.id in finished,
    }


def first_open_member(user_id, group, today):
    """Where starting a group's session lands: the first member not yet finished.

    None when there is nothing left to work through - no session today, all
    of it done, or no members - and the group's own page is the place to be.
    """
    booking = ProjectDaySlot.query.filter_by(
        user_id=user_id, project_id=group.id, slot_date=today
    ).first()
    if booking is None or booking.is_done or booking.is_failed:
        return None
    finished = done_member_ids(booking)
    return next((member for member in group.active_members if member.id not in finished), None)


def member_choices(group):
    """The projects a group could take in: active, not groups, not already in it.

    A project in another group is offered too - adding it moves it - and says
    which group it would leave.
    """
    return (
        Project.query.filter(
            Project.user_id == group.user_id,
            Project.id != group.id,
            Project.is_archived.is_(False),
            Project.is_group.is_(False),
            db.or_(Project.group_id.is_(None), Project.group_id != group.id),
        )
        .order_by(func.lower(Project.title).asc())
        .all()
    )


def add_member(group, project):
    """Put ``project`` into ``group``. Returns ``(ok, message)``; the caller commits."""
    if not group.is_group:
        return False, "That project is not a group."
    if project.id == group.id:
        return False, "A group cannot contain itself."
    if project.is_group:
        return False, "A group cannot be put into another group."
    if project.is_archived:
        return False, "Archived projects cannot join a group."
    if project.group_id == group.id:
        return True, f"{project.title} is already in this group."
    project.group_id = group.id
    return True, f"{project.title} added to {group.title}."


def remove_member(group, project):
    """Take ``project`` out of ``group``. Returns ``(ok, message)``; the caller commits."""
    if project.group_id != group.id:
        return False, f"{project.title} is not in this group."
    project.group_id = None
    return True, f"{project.title} removed from {group.title}."


def active_group_member_ids(user_id):
    """Ids of every project planned through an active group.

    These are the projects the Not scheduled list and the picker leave out:
    the group is what gets planned for them.
    """
    group_ids = (
        db.session.query(Project.id)
        .filter(
            Project.user_id == user_id,
            Project.is_group.is_(True),
            Project.is_archived.is_(False),
        )
    )
    return {
        project_id
        for (project_id,) in db.session.query(Project.id).filter(
            Project.user_id == user_id, Project.group_id.in_(group_ids)
        )
    }
