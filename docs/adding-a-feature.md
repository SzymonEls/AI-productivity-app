# How to add a simple feature (a new model field + an endpoint)

This tutorial shows the full path using an example that **already exists in the code**:
the `is_archived` flag on a project plus the archive/restore endpoints.
Follow these files as the reference:

- the model field: [app/models.py:74](../app/models.py#L74) (`is_archived`)
- the migration: [20260704_0012_add_project_archived_flag.py](../migrations/versions/20260704_0012_add_project_archived_flag.py)
- the endpoints: [app/projects/routes.py:55-74](../app/projects/routes.py#L55-L74) (`archive_project`, `unarchive_project`)

Below we repeat that path step by step for a new, hypothetical field `is_pinned`
("pinned project"). The order matters.

## 1. Add the field to the model

File: [app/models.py](../app/models.py), the `Project` class. Add the column next to the other flags
(follow `is_archived` on line 74 exactly):

```python
is_pinned = db.Column(db.Boolean, default=False, nullable=False)
```

Convention in this repo: boolean flags are named `is_*`, are `nullable=False` with `default=False`.

## 2. Generate the migration

After saving the model, generate the migration and apply it right away:

```bash
flask --app run.py db migrate -m "Add project is_pinned flag"
flask --app run.py db upgrade
```

Open the generated file in [migrations/versions/](../migrations/versions/) and **review it**.
A reference migration for adding a column looks like this (see migration `0012`):

```python
def upgrade():
    op.add_column(
        "projects",
        sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

def downgrade():
    op.drop_column("projects", "is_pinned")
```

> Note: the column is `nullable=False`, so it **must** have a `server_default` (here `sa.false()`),
> otherwise the migration fails on existing rows. The autogenerator usually adds it —
> make sure it's there.
>
> Separately: if you want the field to also be handled by old local databases without migrations,
> this repo has a second (older) mechanism in [app/__init__.py:314-484](../app/__init__.py#L314-L484).
> **Do not extend it** — the migration from this step is the source of truth.

## 3. Add the endpoint

File: [app/projects/routes.py](../app/projects/routes.py). Add a function next to the existing ones,
following `archive_project` ([line 55](../app/projects/routes.py#L55)):

```python
@projects_bp.route("/<int:project_id>/pin", methods=["POST"])
@login_required
def pin_project(project_id):
    project = _get_user_project_or_404(project_id)   # checks it's the current user's project
    project.is_pinned = True
    db.session.commit()
    flash("Project pinned.", "info")
    return redirect(url_for("projects.dashboard"))
```

Conventions that apply here:
- the decorators `@<blueprint>_bp.route(...)` **and** `@login_required`,
- access to other users' data is blocked by the helper `_get_user_project_or_404`
  ([app/projects/routes.py:15](../app/projects/routes.py#L15)),
- save with `db.session.commit()`; for operations that may fail, wrap it in
  `try/except SQLAlchemyError` with `db.session.rollback()` (like in `create_project`, [line 99](../app/projects/routes.py#L99)).

## 4. Register the route (usually nothing to do)

The route belongs to the `projects_bp` blueprint, which is already registered in
[app/__init__.py:41](../app/__init__.py#L41). You add a **new file/blueprint** only when creating
an entirely new feature module — then create `app/<name>/routes.py` with
`<name>_bp = Blueprint("<name>", __name__, url_prefix="/<name>")` and add
`app.register_blueprint(<name>_bp)` in [app/__init__.py:38-42](../app/__init__.py#L38-L42)
(along with the import next to the others, [lines 32-36](../app/__init__.py#L32-L36)).

## 5. Wire it into the view

You add the form that calls the endpoint in a template. See how the archive button is
embedded in the list/dashboard ([app/templates/projects/dashboard.html](../app/templates/projects/dashboard.html)
and [app/templates/projects/project_detail.html](../app/templates/projects/project_detail.html)) —
it's a `method="post"` form pointing at `url_for("projects.archive_project", ...)`.

## 6. Verify the whole thing

```bash
flask --app run.py db upgrade      # database up to date
flask --app run.py run             # click the new action in the UI
```

Finally, go through the relevant sections in
[CHANGE-CHECKLIST.md](CHANGE-CHECKLIST.md) ("Model change" and "New endpoint").
