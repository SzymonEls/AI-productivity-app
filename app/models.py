import secrets
from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db, login_manager


# Half an hour is the default a new account gets; the bounds are what the
# Integrations page will accept, with five minutes low enough to feel live and a
# day high enough to mean "only when I ask".
DEFAULT_REFRESH_MINUTES = 30
MIN_REFRESH_MINUTES = 5
MAX_REFRESH_MINUTES = 1440


class User(UserMixin, db.Model):
    """Authenticated user model."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    # Part of what the session and "remember me" cookies carry, so replacing it
    # invalidates every cookie already handed out. See get_id() below.
    session_token = db.Column(
        db.String(64), nullable=False, default=lambda: secrets.token_hex(32)
    )
    # Bearer credential for the JSON API the menu bar app talks to. Separate
    # from session_token on purpose: changing a password throws the browsers
    # out, and a desktop app that keeps working through that is the point.
    api_token = db.Column(
        db.String(64), nullable=False, default=lambda: secrets.token_urlsafe(32)
    )
    # How stale a subscribed calendar may get before the schedule page goes and
    # re-reads it. On the user rather than in the config file: it is a taste
    # ("how live does this have to feel") and it is set from the Integrations
    # page, not by whoever deploys the app.
    calendar_refresh_minutes = db.Column(
        db.Integer, nullable=False, default=DEFAULT_REFRESH_MINUTES
    )
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    projects = db.relationship(
        "Project",
        back_populates="owner",
        cascade="all, delete-orphan",
        lazy=True,
    )
    timeline_groups = db.relationship(
        "ProjectTimelineGroup",
        back_populates="owner",
        cascade="all, delete-orphan",
        lazy=True,
        order_by=lambda: ProjectTimelineGroup.position,
    )
    timeline_items = db.relationship(
        "ProjectTimelineItem",
        back_populates="owner",
        cascade="all, delete-orphan",
        lazy=True,
    )
    time_entries = db.relationship(
        "ProjectTimeEntry",
        back_populates="owner",
        cascade="all, delete-orphan",
        lazy=True,
        order_by=lambda: ProjectTimeEntry.started_at.desc(),
    )
    day_slots = db.relationship(
        "ProjectDaySlot",
        back_populates="owner",
        cascade="all, delete-orphan",
        lazy=True,
        order_by=lambda: (ProjectDaySlot.slot_date, ProjectDaySlot.slot),
    )
    day_notes = db.relationship(
        "DayNote",
        back_populates="owner",
        cascade="all, delete-orphan",
        lazy=True,
        order_by=lambda: (DayNote.note_date, DayNote.created_at, DayNote.id),
    )
    inbox_items = db.relationship(
        "InboxItem",
        back_populates="owner",
        cascade="all, delete-orphan",
        lazy=True,
        # Newest first: the inbox is a queue you empty from the top, and the
        # thought you just dictated is the one you are still thinking about.
        order_by=lambda: (InboxItem.created_at.desc(), InboxItem.id.desc()),
    )
    calendar_feeds = db.relationship(
        "CalendarFeed",
        back_populates="owner",
        cascade="all, delete-orphan",
        lazy=True,
        order_by=lambda: (CalendarFeed.created_at, CalendarFeed.id),
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        # A new password must not leave the old sessions signed in - on a shared
        # or stolen device, changing the password is exactly how you throw the
        # other party out. Flask-Login writes get_id() into both cookies, so a
        # fresh token here is enough to make every one of them fail to load.
        self.session_token = secrets.token_hex(32)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def regenerate_api_token(self):
        """Issue a new API token, which retires the one handed out before it.

        The old value is overwritten rather than kept alongside, so a token
        that leaked stops working the moment this is called.
        """
        self.api_token = secrets.token_urlsafe(32)
        return self.api_token

    def get_id(self):
        """Identify the session by user *and* password generation.

        UserMixin would return the bare primary key, which stays the same for
        the life of the account and so keeps every cookie ever issued valid.
        """
        return f"{self.id}:{self.session_token}"


class Project(db.Model):
    """Project model kept intentionally small for easy expansion later."""

    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    short_goal = db.Column(db.Text, nullable=False)
    long_goal = db.Column(db.Text, nullable=False)
    archived_long_goal = db.Column(db.Text, nullable=False, default="")
    is_starred = db.Column(db.Boolean, default=False, nullable=False)
    is_private = db.Column(db.Boolean, default=False, nullable=False)
    is_archived = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    owner = db.relationship("User", back_populates="projects")
    timeline_items = db.relationship(
        "ProjectTimelineItem",
        back_populates="project",
        cascade="all, delete-orphan",
        lazy=True,
    )
    time_entries = db.relationship(
        "ProjectTimeEntry",
        back_populates="project",
        lazy=True,
        order_by=lambda: ProjectTimeEntry.started_at.desc(),
    )
    day_slots = db.relationship(
        "ProjectDaySlot",
        back_populates="project",
        cascade="all, delete-orphan",
        lazy=True,
    )


class ProjectTimeEntry(db.Model):
    """A server-side work timer session for a project.

    ``project_id`` is nullable and has no delete cascade: deleting a project
    orphans its time entries instead of destroying them, so tracked history
    survives. ``project_title_snapshot`` preserves the project's name for
    display once the link is gone.
    """

    __tablename__ = "project_time_entries"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=True)
    started_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    ended_at = db.Column(db.DateTime, nullable=True)
    description = db.Column(db.Text, nullable=True)
    project_title_snapshot = db.Column(db.String(150), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    owner = db.relationship("User", back_populates="time_entries")
    project = db.relationship("Project", back_populates="time_entries")

    @property
    def display_project_title(self):
        if self.project:
            return self.project.title
        return self.project_title_snapshot or "Unknown project"


class ProjectTimelineGroup(db.Model):
    """User-owned group on the project timeline."""

    __tablename__ = "project_timeline_groups"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name = db.Column(db.String(150), nullable=True)
    position = db.Column(db.Integer, default=0, nullable=False)
    is_backlog = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    owner = db.relationship("User", back_populates="timeline_groups")
    items = db.relationship(
        "ProjectTimelineItem",
        back_populates="group",
        cascade="all, delete-orphan",
        lazy=True,
        order_by=lambda: ProjectTimelineItem.position,
    )


class ProjectTimelineItem(db.Model):
    """Project or custom note placed inside a project timeline group."""

    __tablename__ = "project_timeline_items"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey("project_timeline_groups.id"), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=True)
    item_type = db.Column(db.String(20), nullable=False)
    title = db.Column(db.String(180), nullable=True)
    body = db.Column(db.Text, nullable=True)
    is_private = db.Column(db.Boolean, default=False, nullable=False)
    position = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    owner = db.relationship("User", back_populates="timeline_items")
    group = db.relationship("ProjectTimelineGroup", back_populates="items")
    project = db.relationship("Project", back_populates="timeline_items")


class ProjectDaySlot(db.Model):
    """One project booked into one of a day's three slots.

    Slots are A, B and the optional C. The unique constraint is what actually
    guarantees "at most one project per slot"; the service layer only adds the
    rule that a project may hold at most one slot today and one in the future.
    Unlike ``ProjectTimeEntry``, this cascades from ``Project``: a slot left
    behind by a deleted project is an empty booking, not history worth keeping.
    """

    __tablename__ = "project_day_slots"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False)
    slot_date = db.Column(db.Date, nullable=False)
    slot = db.Column(db.String(1), nullable=False)
    # Marks that day's session as finished. It lives on the slot, not the
    # project, so it resets by itself tomorrow - that is a different row.
    is_done = db.Column(db.Boolean, default=False, nullable=False)
    # How often this session has been pushed onto a later day, which is what
    # colours the block on the schedule. It belongs to the booking rather than
    # to the project on purpose: freeing the block and booking the project again
    # is a new plan, and a new plan starts from nothing being late.
    postponed_count = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    owner = db.relationship("User", back_populates="day_slots")
    project = db.relationship("Project", back_populates="day_slots")

    __table_args__ = (
        db.UniqueConstraint("user_id", "slot_date", "slot", name="uq_project_day_slot"),
        db.Index("ix_project_day_slots_user_date", "user_id", "slot_date"),
        db.Index("ix_project_day_slots_project_date", "project_id", "slot_date"),
    )


# A day sheet is narrow and a note is a line on it rather than a paragraph; the
# limit is on the column and checked again when a note is saved.
DAY_NOTE_MAX_LENGTH = 200


class DayNote(db.Model):
    """One line of notes against one day, kept under that day's three blocks.

    A day holds a list of these rather than one block of free text: the sheet
    renders them as a list, and a single row is what the + adds and the × takes
    away. Nothing about a note is unique - a day takes as many as get written -
    so their order is the order they were written in.

    Unlike a booking, a note belongs to no project and so is never cascaded away
    by one: it describes the day, not the work planned on it, and outlives
    whatever was booked there. It goes when it is deleted, or with the account.
    """

    __tablename__ = "day_notes"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    note_date = db.Column(db.Date, nullable=False)
    body = db.Column(db.String(DAY_NOTE_MAX_LENGTH), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    owner = db.relationship("User", back_populates="day_notes")

    __table_args__ = (
        db.Index("ix_day_notes_user_date", "user_id", "note_date"),
    )


# A captured thought is a sentence or two dictated on the way somewhere, not an
# essay: long enough for a paragraph, short enough that the widget stays a list.
# Checked on the column and again where an item is saved.
INBOX_ITEM_MAX_LENGTH = 2000


class InboxItem(db.Model):
    """One thought captured before it was decided which project it belongs to.

    The whole point is that capturing and filing are separate moments. Phone in
    hand you have a sentence and no patience for picking a project; at the desk
    you have the list in front of you and the choice is obvious. So an item
    holds nothing but the text and waits on the home page until a project is
    chosen for it.

    Deliberately not a project's field and not a DayNote: it belongs to no
    project yet - that is its defining state - and to no day either, since when
    a thought was had says nothing about where it goes. Filing one appends the
    text to ``Project.short_goal`` and deletes the row, so the inbox is only
    ever a queue: nothing that has been filed is kept here as well.
    """

    __tablename__ = "inbox_items"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    body = db.Column(db.String(INBOX_ITEM_MAX_LENGTH), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    owner = db.relationship("User", back_populates="inbox_items")

    __table_args__ = (
        db.Index("ix_inbox_items_user", "user_id"),
    )


class CalendarFeed(db.Model):
    """One subscribed iCal URL, and the last copy of it we managed to fetch.

    The whole integration: a URL the user pastes in, read on a timer and mirrored
    into the day sheets. Nothing is ever sent back to the calendar, so a "public"
    and a "private" iCal address are the same thing here - the secret one just
    shows more.

    The body is cached rather than the events parsed out of it. Which occurrences
    a page needs depends on the days it is showing, so the text is kept as it
    arrived and expanded per page; it also means a feed that stops answering
    keeps showing what it last said instead of emptying the sheets.

    ``checked_at`` is every attempt and ``fetched_at`` only the ones that worked:
    a feed that 404s must not be retried on every page render, and the page has
    to be able to say how old what it is showing really is.
    """

    __tablename__ = "calendar_feeds"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    url = db.Column(db.String(2000), nullable=False)
    is_enabled = db.Column(db.Boolean, default=True, nullable=False)
    cached_ics = db.Column(db.Text, nullable=False, default="")
    checked_at = db.Column(db.DateTime, nullable=True)
    fetched_at = db.Column(db.DateTime, nullable=True)
    last_error = db.Column(db.String(255), nullable=False, default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    owner = db.relationship("User", back_populates="calendar_feeds")

    __table_args__ = (
        db.Index("ix_calendar_feeds_user", "user_id"),
    )


class LoginAttempt(db.Model):
    """One failed sign-in, remembered only for as long as it locks the door.

    Kept in the database rather than in the process on purpose. Gunicorn runs
    several workers, and a counter held in memory belongs to one of them: a
    limit of three would really be three per worker, and which worker answers
    is up to the operating system. A table is the one place all of them share.
    """

    __tablename__ = "login_attempts"

    id = db.Column(db.Integer, primary_key=True)
    # "ip:203.0.113.1" or "email:someone@example.com". One failure writes a row
    # for both, so a single wrong password spends the caller's budget and the
    # account's at the same time.
    scope = db.Column(db.String(255), nullable=False)
    failed_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        db.Index("ix_login_attempts_scope_failed_at", "scope", "failed_at"),
    )


@login_manager.user_loader
def load_user(session_id):
    """Load the user only if the cookie's token still matches the stored one.

    Cookies written before this field existed carry a bare id and no token;
    they fail the comparison below, which signs those sessions out once.
    """
    raw_id, _, token = str(session_id).partition(":")
    try:
        user = User.query.get(int(raw_id))
    except ValueError:
        return None

    if user is None or not secrets.compare_digest(token, user.session_token or ""):
        return None

    return user
