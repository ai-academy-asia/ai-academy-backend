"""``flask files cleanup`` — drop uploads never attached to a submission (contract §2.8).

A student uploads first and submits second; a file that no submission points at
after 24 h was abandoned. The S3 object goes first: a failed delete keeps the
row, so the next run retries instead of leaving an orphan in the bucket.
"""
from __future__ import annotations

from datetime import timedelta

import click
from flask.cli import AppGroup

from app.extensions import db
from app.models import AssignmentSubmission, StudentFile
from app.storage import S3StorageError, delete_object
from app.timeutil import utcnow

UNATTACHED_TTL = timedelta(hours=24)

files_cli = AppGroup("files", help="Student upload housekeeping")


def stale_files(now=None) -> list:
    cutoff = (now or utcnow()) - UNATTACHED_TTL
    attached = db.session.query(AssignmentSubmission.file_id).filter(
        AssignmentSubmission.file_id.isnot(None))
    return (StudentFile.query
            .filter(StudentFile.created_at < cutoff, ~StudentFile.id.in_(attached))
            .order_by(StudentFile.id).all())


def cleanup_unattached(now=None) -> dict:
    deleted, failed = 0, 0
    for student_file in stale_files(now):
        try:
            delete_object(student_file.file_key)
        except S3StorageError:
            failed += 1
            continue
        db.session.delete(student_file)
        deleted += 1
    db.session.commit()
    return {"deleted": deleted, "failed": failed}


@files_cli.command("cleanup")
def cleanup_command():
    """Delete student uploads left unattached for more than 24 hours."""
    result = cleanup_unattached()
    click.echo(f"student files: {result['deleted']} deleted, {result['failed']} failed")
