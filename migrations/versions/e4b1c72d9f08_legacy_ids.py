"""Legacy ids on courses and cohorts

The marketing site's programme cards carry the ids the previous system used
(`backendCourseId` / `backendScheduleId`) and send them at checkout. Storing
them lets the public API answer to those ids as well as to our own, so the
front-end's existing cards work without a translation table that would have to
be kept in sync by hand.

Revision ID: e4b1c72d9f08
Revises: d9a41c07e5b2
Create Date: 2026-08-06

"""
import sqlalchemy as sa
from alembic import op

revision = "e4b1c72d9f08"
down_revision = "d9a41c07e5b2"
branch_labels = None
depends_on = None


def upgrade():
    # Not unique: one legacy course covered several programmes we model apart
    # (legacy 49 spans "AI 101 Adult Online", "AI 101 Online" and the QPay test).
    op.add_column("courses", sa.Column("legacy_course_id", sa.Integer(), nullable=True))
    op.create_index("ix_courses_legacy_course_id", "courses", ["legacy_course_id"])

    # Unique — every run had its own schedule id, and that is what a booking
    # keys on, so it is the reliable identifier of the two.
    op.add_column("cohorts", sa.Column("legacy_schedule_id", sa.Integer(), nullable=True))
    op.create_index(
        "ix_cohorts_legacy_schedule_id", "cohorts", ["legacy_schedule_id"], unique=True
    )
    # Also per-run: runs we group into one course did not always share one
    # legacy course id, so the course-level column alone leaves ids unresolvable.
    op.add_column("cohorts", sa.Column("legacy_course_id", sa.Integer(), nullable=True))
    op.create_index("ix_cohorts_legacy_course_id", "cohorts", ["legacy_course_id"])


def downgrade():
    op.drop_index("ix_cohorts_legacy_course_id", table_name="cohorts")
    op.drop_column("cohorts", "legacy_course_id")
    op.drop_index("ix_cohorts_legacy_schedule_id", table_name="cohorts")
    op.drop_column("cohorts", "legacy_schedule_id")
    op.drop_index("ix_courses_legacy_course_id", table_name="courses")
    op.drop_column("courses", "legacy_course_id")
