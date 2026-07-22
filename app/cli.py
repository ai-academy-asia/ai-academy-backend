"""Flask CLI commands for auth administration.

Bootstrap the first admin (no other way to log in on a fresh DB):

    flask auth create-staff --email admin@ai-academy.asia --password 'secret123' \
        --first-name Admin --role super_admin
"""
import click
from flask.cli import AppGroup

from app.auth.service import (
    AccountError,
    create_staff_account,
    create_student_account,
    create_teacher_account,
)
from app.models import STAFF_ROLES

auth_cli = AppGroup("auth", help="Auth account administration")


def _echo_account(account, profile):
    click.echo(
        f"created {account.actor_type} account #{account.id} "
        f"<{account.email}> role={account.role} profile_id={profile.id}"
    )


@auth_cli.command("create-staff")
@click.option("--email", required=True)
@click.option("--password", required=True)
@click.option("--first-name", required=True)
@click.option("--last-name", default=None)
@click.option("--phone", default=None)
@click.option("--role", default="super_admin", type=click.Choice(STAFF_ROLES))
@click.option("--no-force-pw-change", is_flag=True,
              help="Do not require a password change on first login.")
def create_staff(email, password, first_name, last_name, phone, role, no_force_pw_change):
    try:
        account, staff = create_staff_account(
            email=email, password=password, first_name=first_name,
            last_name=last_name, phone=phone, role=role,
            must_change_password=not no_force_pw_change,
        )
    except AccountError as exc:
        raise click.ClickException(str(exc))
    _echo_account(account, staff)


@auth_cli.command("create-teacher")
@click.option("--email", required=True)
@click.option("--password", required=True)
@click.option("--first-name", required=True)
@click.option("--last-name", default=None)
@click.option("--phone", default=None)
@click.option("--no-force-pw-change", is_flag=True)
def create_teacher(email, password, first_name, last_name, phone, no_force_pw_change):
    try:
        account, teacher = create_teacher_account(
            email=email, password=password, first_name=first_name,
            last_name=last_name, phone=phone,
            must_change_password=not no_force_pw_change,
        )
    except AccountError as exc:
        raise click.ClickException(str(exc))
    _echo_account(account, teacher)


@auth_cli.command("create-student")
@click.option("--email", required=True)
@click.option("--password", required=True)
@click.option("--first-name", required=True)
@click.option("--last-name", default=None)
@click.option("--phone", default=None)
@click.option("--no-force-pw-change", is_flag=True)
def create_student(email, password, first_name, last_name, phone, no_force_pw_change):
    try:
        account, student = create_student_account(
            email=email, password=password, first_name=first_name,
            last_name=last_name, phone=phone,
            must_change_password=not no_force_pw_change,
        )
    except AccountError as exc:
        raise click.ClickException(str(exc))
    _echo_account(account, student)


def register_cli(app) -> None:
    app.cli.add_command(auth_cli)
