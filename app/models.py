import secrets
from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db, login_manager
from .ulid import new_ulid


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
    sync_state = db.relationship(
        "SyncState",
        back_populates="owner",
        cascade="all, delete-orphan",
        lazy=True,
        uselist=False,
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

    def get_id(self):
        """Identify the session by user *and* password generation.

        UserMixin would return the bare primary key, which stays the same for
        the life of the account and so keeps every cookie ever issued valid.
        """
        return f"{self.id}:{self.session_token}"


def sync_table_args(table_name, *extra):
    """The constraints every synchronised table needs, named after the table."""
    return (
        db.UniqueConstraint("user_id", "uid", name=f"uq_{table_name}_user_uid"),
        # Pull asks for "everything above this counter", which is this index.
        db.Index(f"ix_{table_name}_user_rev", "user_id", "rev"),
        # Partial, so it holds only tombstones: pruning then seeks a handful of
        # rows instead of scanning a table of live ones.
        db.Index(
            f"ix_{table_name}_user_deleted",
            "user_id",
            "deleted_at",
            sqlite_where=db.text("deleted_at IS NOT NULL"),
        ),
    ) + extra


class SyncMixin:
    """What a table needs before it can be synchronised with a local copy.

    The integer primary key stays exactly where it is - foreign keys and every
    relationship below still run on it. These three columns live alongside it
    and are what the protocol speaks, because the primary key cannot answer any
    of the three questions synchronisation asks.
    """

    # Who am I, when SQLite has not assigned anything yet? Minted by whoever
    # creates the row, so a browser with no network can still make one.
    uid = db.Column(db.String(26), nullable=False, default=new_ulid)
    # Have you seen this version? A per-user counter stamped by the server, not
    # a clock: two devices disagree about the time, but not about an ordering.
    rev = db.Column(db.Integer, nullable=False, default=0)
    # Am I gone? A deletion has to be a fact the next pull can carry. A row that
    # simply vanished is indistinguishable from one that never changed, and the
    # other device would push it back.
    deleted_at = db.Column(db.DateTime, nullable=True)

    # Columns holding what the user actually wrote. Cleared the moment the row
    # is deleted - the tombstone only has to say "this uid is gone", and keeping
    # the text would mean a deleted private plan still sat on the server.
    __sync_payload__ = ()


class Project(SyncMixin, db.Model):
    """Project model kept intentionally small for easy expansion later."""

    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    short_goal = db.Column(db.Text, nullable=False)
    frequency = db.Column(db.String(255), nullable=False)
    long_goal = db.Column(db.Text, nullable=False)
    archived_long_goal = db.Column(db.Text, nullable=False, default="")
    # Minutes to aim for on a day this project sits in slot A or B. None = no target.
    daily_target_minutes = db.Column(db.Integer, nullable=True)
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

    __sync_payload__ = (
        "title",
        "short_goal",
        "frequency",
        "long_goal",
        "archived_long_goal",
    )

    __table_args__ = sync_table_args("projects")


class ProjectTimeEntry(SyncMixin, db.Model):
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

    __sync_payload__ = ("description", "project_title_snapshot")

    __table_args__ = sync_table_args("project_time_entries")


class ProjectTimelineGroup(SyncMixin, db.Model):
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

    __sync_payload__ = ("name",)

    __table_args__ = sync_table_args("project_timeline_groups")


class ProjectTimelineItem(SyncMixin, db.Model):
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

    __sync_payload__ = ("title", "body")

    __table_args__ = sync_table_args("project_timeline_items")


class ProjectDaySlot(SyncMixin, db.Model):
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
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    owner = db.relationship("User", back_populates="day_slots")
    project = db.relationship("Project", back_populates="day_slots")

    # A booking carries nothing the user typed - freeing a slot has nothing to
    # clear beyond the row itself.
    __sync_payload__ = ()

    __table_args__ = sync_table_args(
        "project_day_slots",
        # Was a plain UniqueConstraint. It has to skip tombstones, or a freed
        # slot would stay unbookable: the dead row still occupies the key.
        db.Index(
            "uq_project_day_slot",
            "user_id",
            "slot_date",
            "slot",
            unique=True,
            sqlite_where=db.text("deleted_at IS NULL"),
        ),
        db.Index("ix_project_day_slots_user_date", "user_id", "slot_date"),
        db.Index("ix_project_day_slots_project_date", "project_id", "slot_date"),
    )


class SyncState(db.Model):
    """Per-user bookkeeping for synchronisation.

    ``last_rev`` is the counter every write draws from, and the reason a client
    can ask for "everything above 412" and get an exact answer.

    ``tombstone_floor`` is what makes pruning safe: it records how far the
    deletions have already been cleared away, so a client whose cursor sits
    below it is told to fetch the whole set instead of a difference it can no
    longer be given correctly.
    """

    __tablename__ = "sync_states"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True)
    last_rev = db.Column(db.Integer, nullable=False, default=0)
    tombstone_floor = db.Column(db.Integer, nullable=False, default=0)
    last_pruned_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    owner = db.relationship("User", back_populates="sync_state")


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
