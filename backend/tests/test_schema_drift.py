"""The model and the migrations have to describe the same schema.

This drifted once already and nothing noticed: two indexes on
``project_time_entries`` existed in every real database but were never declared
on the model, so autogenerate proposed dropping them on every run and the drops
had to be deleted by hand each time - see the docstring of
``20260808_0016_add_project_day_slots.py``. The cost was not the indexes, which
were fine, but that every genuine diff arrived buried in two false ones.
"""


def test_the_model_matches_the_migrated_schema(app):
    """The same comparison `flask --app run.py db check` runs."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app.extensions import db

    with db.engine.connect() as connection:
        context = MigrationContext.configure(connection)
        difference = compare_metadata(context, db.metadata)

    assert difference == [], (
        "Model and migrations disagree. Either add a migration, or declare on "
        "the model what the database already has."
    )


def test_the_time_entry_indexes_are_declared(app):
    """Named explicitly, because these two are the pair that went missing."""
    from app.models import ProjectTimeEntry

    declared = {
        index.name: tuple(column.name for column in index.columns)
        for index in ProjectTimeEntry.__table__.indexes
    }

    assert declared["ix_project_time_entries_user_project_started"] == (
        "user_id",
        "project_id",
        "started_at",
    )
    assert declared["ix_project_time_entries_user_ended"] == ("user_id", "ended_at")
