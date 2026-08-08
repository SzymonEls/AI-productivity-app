"""
Read-only public demo mode, switched on with DEMO_MODE in the environment.

Everything here is wired up once, while `create_app()` runs. When DEMO_MODE is
off, `register_demo_mode` returns immediately after setting a single Jinja
global, so a normal installation registers no request hook, no context
processor and reads no file - request handling is byte-for-byte what it was
before this module existed.
"""

import os
import random
import re
from datetime import datetime, timedelta, timezone

import click
from flask import flash, jsonify, redirect, request, url_for
from markupsafe import Markup
from sqlalchemy.exc import SQLAlchemyError

from config import BASE_DIR

from .extensions import db
from .markdown_utils import render_markdown
from .models import (
    DailyPlan,
    Project,
    ProjectDaySlot,
    ProjectTimeEntry,
    ProjectTimelineGroup,
    ProjectTimelineItem,
    User,
)


# Requests that may still write while the demo is read-only. The login POST has
# to go through; logout is a GET and never reaches the guard.
DEMO_ALLOWED_ENDPOINTS = frozenset({"auth.login"})
DEMO_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Relative link in the rendered document, e.g. href="docs/ARCHITECTURE.md".
# Anything already absolute, protocol-relative or an anchor is left alone.
RELATIVE_LINK_PATTERN = re.compile(r'\b(href|src)="(?!\w+:|//|/|#)([^"]+)"')


def register_demo_mode(app):
    """Install demo mode, or get out of the way entirely when it is off."""

    if not app.config.get("DEMO_MODE"):
        app.jinja_env.globals["demo_mode"] = False
        return

    app.jinja_env.globals["demo_mode"] = True
    app.jinja_env.globals["demo_banner_message"] = app.config.get("DEMO_BANNER_MESSAGE", "")
    app.jinja_env.globals["demo_doc_html"] = _render_demo_doc(app)
    _register_write_guard(app)
    _register_seed_command(app)


def _render_demo_doc(app):
    """
    Render the Markdown file advertised on the login page.

    Read and converted once per process: the login page only ever interpolates
    the finished Markup.
    """
    document_path = app.config.get("DEMO_DOC_PATH", "README.md")
    if not os.path.isabs(document_path):
        document_path = os.path.join(BASE_DIR, document_path)

    try:
        with open(document_path, encoding="utf-8") as document:
            content = document.read()
    except OSError:
        # A missing or unreadable file must not take the login page down.
        app.logger.warning("Demo document not found: %s", document_path)
        return ""

    html = render_markdown(content)
    return _absolutize_links(html, app.config.get("DEMO_DOC_BASE_URL", ""))


def _absolutize_links(html, base_url):
    """
    Point the document's relative links at the repository.

    Markdown docs link to sibling files (``docs/ARCHITECTURE.md``). Those paths
    mean nothing to a browser sitting on the login page, so without this every
    such link is a dead end.
    """
    if not html or not base_url:
        return html

    base_url = base_url.rstrip("/") + "/"
    rewritten = RELATIVE_LINK_PATTERN.sub(
        lambda match: f'{match.group(1)}="{base_url}{match.group(2)}"', str(html)
    )
    return Markup(rewritten)


def _register_write_guard(app):
    """Reject every state-changing request with the app's usual error shape."""

    from . import wants_json_response

    message = app.config.get("DEMO_BLOCK_MESSAGE", "Demo mode - changes are disabled.")

    @app.before_request
    def block_demo_writes():
        if request.method not in DEMO_WRITE_METHODS:
            return None
        if request.endpoint in DEMO_ALLOWED_ENDPOINTS:
            return None

        if wants_json_response():
            return jsonify({"ok": False, "message": message}), 403

        flash(message, "warning")
        return redirect(request.referrer or url_for("projects.dashboard"))


def _register_seed_command(app):
    @app.cli.command("seed-demo")
    @click.option("--reset", is_flag=True, help="Delete the demo account first and seed it again.")
    def seed_demo_command(reset):
        """Fill the demo database with sample content."""
        seed_demo_data(app, reset=reset)


def seed_demo_data(app, reset=False):
    """
    Create the demo account and enough content for every screen to show
    something. Idempotent: an existing demo account is left alone unless
    ``reset`` is passed.
    """
    email = app.config.get("DEFAULT_LOGIN_EMAIL", "").strip().lower()
    password = app.config.get("DEFAULT_LOGIN_PASSWORD", "")
    if not email or not password:
        click.echo("Set DEFAULT_LOGIN_EMAIL and DEFAULT_LOGIN_PASSWORD before seeding.")
        return

    existing = User.query.filter_by(email=email).first()
    if existing and not reset:
        click.echo(f"Demo account {email} already exists; nothing to do.")
        return

    try:
        if existing:
            # Projects, timeline, time entries and the daily plan all cascade
            # off User, so deleting the account clears the whole demo.
            db.session.delete(existing)
            db.session.flush()

        user = User(username="demo", email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()

        projects = _seed_projects(user)
        _seed_timeline(user, projects)
        _seed_day_slots(user, projects)
        _seed_time_entries(user, projects)
        _seed_daily_plan(user, projects)

        db.session.commit()
    except SQLAlchemyError as error:
        db.session.rollback()
        click.echo(f"Seeding failed: {error}")
        return

    click.echo(f"Seeded demo account {email} with {len(projects)} projects.")


def _seed_projects(user):
    """Create sample projects covering every flag the UI can render."""

    definitions = [
        {
            "title": "Portfolio website",
            "short_goal": "Ship a personal site that gets me interviews.",
            "frequency": "Twice a week",
            "is_starred": True,
            "long_goal": (
                "# Content\n"
                "- [x] Pick the three projects worth showing\n"
                "- [x] Write the case study for this app\n"
                "- [ ] Record a 90-second walkthrough\n"
                "\n"
                "# Build\n"
                "- [x] Static layout, mobile first\n"
                "- [ ] Dark mode that respects the system setting\n"
                "- [ ] Lighthouse above 95 on every page\n"
                "\n"
                "# Launch\n"
                "- [ ] Custom domain and certificate\n"
                "- [ ] Share on LinkedIn\n"
            ),
            "archived_long_goal": (
                "# Research\n"
                "- [x] Look at fifteen developer portfolios\n"
                "- [x] Decide against a template\n"
            ),
        },
        {
            "title": "This productivity app",
            "short_goal": "Keep the tool I actually use every day in good shape.",
            "frequency": "Every day",
            "is_starred": True,
            "long_goal": (
                "# Now\n"
                "- [x] Block editor for project plans\n"
                "- [x] Timeline with drag and drop\n"
                "- [ ] Read-only demo for the portfolio\n"
                "\n"
                "# Next\n"
                "- [ ] Export a project plan to Markdown\n"
                "- [ ] Weekly summary of tracked time\n"
                "\n"
                "# Someday\n"
                "- [ ] Optional Postgres backend\n"
                "- [ ] Keyboard-only navigation\n"
            ),
        },
        {
            "title": "Learning Rust",
            "short_goal": "Get comfortable enough to write a small CLI tool.",
            "frequency": "Three times a week",
            "long_goal": (
                "# Fundamentals\n"
                "- [x] Ownership and borrowing\n"
                "- [x] Traits and generics\n"
                "- [ ] Lifetimes without guessing\n"
                "\n"
                "# Practice\n"
                "- [ ] Rewrite my log parser in Rust\n"
                "- [ ] Publish it on crates.io\n"
            ),
        },
        {
            "title": "Home server",
            "short_goal": "Self-host the services I would otherwise rent.",
            "frequency": "Once a week",
            "long_goal": (
                "# Infrastructure\n"
                "- [x] Docker Compose for every service\n"
                "- [x] nginx in front, certificates from certbot\n"
                "- [ ] Off-site backup that I have actually restored from\n"
                "\n"
                "# Services\n"
                "- [x] This app\n"
                "- [ ] Photo library\n"
            ),
        },
        {
            "title": "Health",
            "short_goal": "Move more, sleep at a sane hour.",
            "frequency": "Every day",
            "is_private": True,
            "long_goal": (
                "# Routine\n"
                "- [x] Walk after lunch\n"
                "- [ ] Strength training twice a week\n"
                "- [ ] Screens off by 23:00\n"
                "\n"
                "*Private projects are hidden behind a click in the interface.*\n"
            ),
        },
        {
            "title": "Conference talk",
            "short_goal": "Give the SQLite talk at the local meetup.",
            "frequency": "Once a month",
            "long_goal": (
                "# Talk\n"
                "- [x] Outline\n"
                "- [x] Slides\n"
                "- [x] Delivered on 14 May\n"
                "\n"
                "Went better than expected. Archived until the next call for papers.\n"
            ),
            "is_archived": True,
        },
    ]

    projects = []
    for definition in definitions:
        project = Project(
            owner=user,
            title=definition["title"],
            short_goal=definition["short_goal"],
            frequency=definition["frequency"],
            long_goal=definition["long_goal"],
            archived_long_goal=definition.get("archived_long_goal", ""),
            is_starred=definition.get("is_starred", False),
            is_private=definition.get("is_private", False),
            is_archived=definition.get("is_archived", False),
        )
        db.session.add(project)
        projects.append(project)

    db.session.flush()
    return projects


def _seed_timeline(user, projects):
    """
    Lay the active projects out on the timeline.

    The dashboard seeds a timeline itself on GET when none exists
    (``_get_or_create_timeline`` in app/projects/routes.py), which would still
    happen in demo mode because the guard only stops writes. Building the
    timeline here makes that a no-op.
    """
    active = [project for project in projects if not project.is_archived]

    backlog = ProjectTimelineGroup(owner=user, is_backlog=True, position=0)
    in_progress = ProjectTimelineGroup(owner=user, name="In progress", position=1)
    this_quarter = ProjectTimelineGroup(owner=user, name="This quarter", position=2)
    db.session.add_all([backlog, in_progress, this_quarter])
    db.session.flush()

    layout = [
        (in_progress, active[:2]),
        (this_quarter, active[2:4]),
        (backlog, active[4:]),
    ]
    for group, group_projects in layout:
        for position, project in enumerate(group_projects):
            db.session.add(
                ProjectTimelineItem(
                    owner=user,
                    group=group,
                    project=project,
                    item_type="project",
                    is_private=project.is_private,
                    position=position,
                )
            )

    db.session.add(
        ProjectTimelineItem(
            owner=user,
            group=in_progress,
            item_type="note",
            title="Reminder",
            body="Notes can sit on the timeline next to projects.",
            position=len(active[:2]),
        )
    )
    db.session.flush()


def _seed_day_slots(user, projects):
    """
    Book today's A/B/C and one future session.

    Deliberately leaves several projects without a future slot so the
    "Not scheduled" list on the dashboard has something in it.
    """
    from .projects.slots import today_local

    active = [project for project in projects if not project.is_archived]
    if len(active) < 3:
        return

    today = today_local()
    bookings = [
        (today, "A", active[0]),
        (today, "B", active[1]),
        (today, "C", active[2]),
        # A project in today's A slot may still hold one future slot.
        (today + timedelta(days=2), "A", active[0]),
        (today + timedelta(days=3), "B", active[3] if len(active) > 3 else active[1]),
    ]

    for day, slot, project in bookings:
        db.session.add(
            ProjectDaySlot(owner=user, project=project, slot_date=day, slot=slot)
        )

    # A target so the dashboard shows "45m / 2h" rather than just the elapsed time.
    active[0].daily_target_minutes = 120
    active[1].daily_target_minutes = 45

    db.session.flush()


def _seed_time_entries(user, projects):
    """
    Spread finished work sessions over the last two weeks so the time-tracking
    charts have something to draw.

    Dates are relative to now, so the demo never looks stale. No entry is left
    running: an open timer would look frozen when pause is blocked.
    """
    trackable = [project for project in projects if not project.is_archived][:4]
    if not trackable:
        return

    descriptions = [
        "Content pass",
        "Layout work",
        "Reading and notes",
        "Bug fixing",
        "Refactoring",
        "Planning the next step",
        "Reviewing yesterday's work",
    ]

    generator = random.Random(20260801)
    now = datetime.now(timezone.utc)

    for days_ago in range(14):
        day = now - timedelta(days=days_ago)
        for project in generator.sample(trackable, generator.randint(1, min(2, len(trackable)))):
            start_hour = generator.randint(9, 17)
            started_at = day.replace(
                hour=start_hour,
                minute=generator.choice((0, 15, 30, 45)),
                second=0,
                microsecond=0,
            )
            duration = timedelta(minutes=generator.choice((25, 40, 55, 70, 95)))
            if started_at + duration > now:
                continue

            db.session.add(
                ProjectTimeEntry(
                    owner=user,
                    project=project,
                    project_title_snapshot=project.title,
                    started_at=started_at,
                    ended_at=started_at + duration,
                    description=generator.choice(descriptions),
                )
            )

    db.session.flush()


def _seed_daily_plan(user, projects):
    """Save the single daily plan so the home page is not empty."""
    titles = [project.title for project in projects if not project.is_archived][:3]
    while len(titles) < 3:
        titles.append("Focus block")

    db.session.add(
        DailyPlan(
            owner=user,
            title=f"Plan for {datetime.now(timezone.utc).date().isoformat()}",
            target_date=datetime.now(timezone.utc).date(),
            content=(
                f"# {titles[0]}\n"
                "**Short goal:** ship the read-only demo\n\n"
                "- [x] Block writes behind one environment flag\n"
                "- [ ] Point the subdomain at the container\n"
                "\n"
                f"# {titles[1]}\n"
                "**Short goal:** one focused hour\n\n"
                "- [ ] Finish the chapter on lifetimes\n"
                "- [ ] Write down what did not click\n"
                "\n"
                f"# {titles[2]}\n"
                "**Short goal:** keep it ticking\n\n"
                "- [ ] Check the backup ran\n"
            ),
        )
    )
    db.session.flush()
