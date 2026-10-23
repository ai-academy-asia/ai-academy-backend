"""Class session -> lesson link

Revision ID: a3f7c2d9e1b4
Revises: 8e4a1c6f2d90
Create Date: 2026-10-22

"""
import sqlalchemy as sa
from alembic import op

revision = "a3f7c2d9e1b4"
down_revision = "8e4a1c6f2d90"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("class_sessions", sa.Column("lesson_id", sa.Integer(), nullable=True))
    op.create_index("ix_class_sessions_lesson_id", "class_sessions", ["lesson_id"])
    op.create_foreign_key("fk_class_sessions_lesson_id", "class_sessions", "course_lessons",
                          ["lesson_id"], ["id"], ondelete="SET NULL")


def downgrade():
    op.drop_constraint("fk_class_sessions_lesson_id", "class_sessions", type_="foreignkey")
    op.drop_index("ix_class_sessions_lesson_id", table_name="class_sessions")
    op.drop_column("class_sessions", "lesson_id")
