"""One status vocabulary for courses and cohorts: draft / open / closed

``flask seed courses --publish`` wrote ``published``, a value the admin API
rejects and the student/mobile side does not treat as visible — so a seeded
course showed on the marketing site but answered 404 in the app, while a course
an admin opened showed in the app but not on the site. ``published`` meant
"on sale", which is what ``open`` means everywhere else.

Downgrade is a no-op: once merged, the rows that said ``published`` cannot be
told apart from ones that always said ``open``.

Revision ID: 3b8e1d2c4f60
Revises: 2a7c0f6b1ac3
Create Date: 2026-09-29

"""
from alembic import op

revision = "3b8e1d2c4f60"
down_revision = "2a7c0f6b1ac3"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE courses SET status = 'open' WHERE status = 'published'")
    op.execute("UPDATE cohorts SET status = 'open' WHERE status = 'published'")


def downgrade():
    pass
