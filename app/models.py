from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db, login_manager


class User(UserMixin, db.Model):
    """Authenticated user model."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    projects = db.relationship(
        "Project",
        back_populates="owner",
        cascade="all, delete-orphan",
        lazy=True,
    )
    calendar_subscriptions = db.relationship(
        "CalendarSubscription",
        back_populates="owner",
        cascade="all, delete-orphan",
        lazy=True,
        order_by="CalendarSubscription.name",
    )
    ai_plans = db.relationship(
        "AIPlan",
        back_populates="owner",
        cascade="all, delete-orphan",
        lazy=True,
        order_by=lambda: AIPlan.created_at.desc(),
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

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Project(db.Model):
    """Project model kept intentionally small for easy expansion later."""

    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    short_goal = db.Column(db.Text, nullable=False)
    frequency = db.Column(db.String(255), nullable=False)
    long_goal = db.Column(db.Text, nullable=False)
    is_starred = db.Column(db.Boolean, default=False, nullable=False)
    is_private = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    owner = db.relationship("User", back_populates="projects")
    ai_plans = db.relationship(
        "AIPlan",
        back_populates="project",
        lazy=True,
        order_by=lambda: AIPlan.created_at.desc(),
    )
    timeline_items = db.relationship(
        "ProjectTimelineItem",
        back_populates="project",
        cascade="all, delete-orphan",
        lazy=True,
    )


class ProjectTimelineGroup(db.Model):
    """User-owned group on the project timeline."""

    __tablename__ = "project_timeline_groups"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name = db.Column(db.String(150), nullable=True)
    position = db.Column(db.Integer, default=0, nullable=False)
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


class AIPlan(db.Model):
    """Saved AI-generated markdown or project organization result."""

    __tablename__ = "ai_plans"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=True)
    plan_type = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    user_prompt = db.Column(db.Text, nullable=False)
    target_date = db.Column(db.Date, nullable=True)
    project_title_snapshot = db.Column(db.String(150), nullable=True)
    content = db.Column(db.Text, nullable=False)
    request_payload = db.Column(db.Text, nullable=True)
    response_payload = db.Column(db.Text, nullable=False)
    is_pinned = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    owner = db.relationship("User", back_populates="ai_plans")
    project = db.relationship("Project", back_populates="ai_plans")


class CalendarSubscription(db.Model):
    """User-owned iCal subscription used to build the daily plan view."""

    __tablename__ = "calendar_subscriptions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    ical_url = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    owner = db.relationship("User", back_populates="calendar_subscriptions")


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
