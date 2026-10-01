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
        raise click.ClickException(str(exc)) from exc
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
        raise click.ClickException(str(exc)) from exc
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
        raise click.ClickException(str(exc)) from exc
    _echo_account(account, student)


ebarimt_cli = AppGroup("ebarimt", help="eBarimt / PosAPI operations")


@ebarimt_cli.command("send-data")
def send_data():
    """Flush issued receipts to the tax authority (PosAPI sendData).

    Run on a schedule — the ``ebarimt-sender`` container calls this hourly.
    Exits non-zero when PosAPI is unreachable or rejects, so a scheduler can
    tell a real failure from a quiet success.

    It also releases expired seat holds, because this is the platform's only
    periodic tick and an unreleased hold makes a cohort read "sold out" forever.
    That runs first and separately: a PosAPI outage must not keep seats locked.
    """
    from app.services import ebarimt as svc
    from app.services import enrolment as enrol_svc
    from app.services.errors import ServiceError

    freed = enrol_svc.release_expired_holds()
    if freed:
        click.echo(f"[enrolment] released {freed} expired seat hold(s)")

    try:
        result = svc.flush_to_tax_authority()
    except ServiceError as exc:
        raise click.ClickException(
            f"sendData failed: {exc.code} {exc.extra.get('detail') or ''}".strip()
        ) from exc
    click.echo(
        f"[ebarimt] sendData ok · last_sent={result['last_sent_date']} "
        f"· lotteries_left={result['left_lotteries']} "
        f"· merchants={','.join(result['merchants']) or 'none'}"
    )


mail_cli = AppGroup("mail", help="Outbound email")


@mail_cli.command("test")
@click.option("--to", required=True, help="Where to send the probe.")
def mail_test(to):
    """Send a probe email to verify SMTP settings.

    Reports the resolved settings first, so a failure points at the wrong knob
    instead of just 'authentication failed'.
    """
    from flask import current_app

    from app import mail

    cfg = current_app.config
    click.echo(
        f"host={cfg.get('MAIL_HOST')}:{cfg.get('MAIL_PORT')} "
        f"tls={cfg.get('MAIL_USE_TLS')} ssl={cfg.get('MAIL_USE_SSL')}\n"
        f"user={cfg.get('MAIL_USERNAME') or '(none — IP-authenticated relay)'}\n"
        f"from={cfg.get('MAIL_FROM')}"
    )
    if not mail.is_configured():
        raise click.ClickException("MAIL_HOST is empty — nothing to test.")

    from email.message import EmailMessage

    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = "AIAA — SMTP тест"
    msg.set_content(
        "Энэ бол AIAA backend-ийн SMTP тохиргоог шалгах захидал.\n"
        "Хүлээн авсан бол баримт илгээх тохиргоо ажиллаж байна."
    )
    try:
        mail.send_message(msg)
    except mail.MailError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"sent -> {to}")
    click.echo(
        "Ирсэн захидлын From хаяг MAIL_FROM-той таарч байгаа эсэхийг шалгаарай — "
        "Gmail нь баталгаажаагүй хаягийг нэвтэрсэн хаягаар дардаг."
    )


seed_cli = AppGroup("seed", help="Reference / initial data")


@seed_cli.command("courses")
@click.option("--publish", is_flag=True,
              help="Mark the seeded courses and their cohorts open (on sale).")
@click.option("--file", "path", default=None, help="Override the seed JSON path.")
def seed_courses(publish, path):
    """Load the marketing site's static catalogue into courses + cohorts.

    Idempotent: re-running updates the same rows instead of duplicating them.
    Without --publish nothing becomes visible on /programmes, so seeding a live
    database cannot accidentally put a programme on sale.
    """
    from pathlib import Path

    from app.seeds import seed_courses as run

    result = run(path=Path(path) if path else None, publish=publish)
    click.echo(
        f"courses: +{result['courses']} new, {result['updated']} updated · "
        f"cohorts: +{result['cohorts']} new"
        + ("  [open]" if publish else "  [draft — use --publish to expose]")
    )
    for item in result["converted_from_usd"]:
        click.echo(f"  · quoted in USD, stored in MNT at USD_MNT_RATE: {item}")


@seed_cli.command("programme")
@click.argument("keys", nargs=-1, required=True)
@click.option("--reset", is_flag=True,
              help="First delete what a previous run created, then seed again.")
@click.option("--remove", is_flag=True, help="Only delete what a previous run created.")
def seed_programme(keys, reset, remove):
    """Test data for a running programme: engineering, corporate, online, agentic,
    business (or all).

    Creates logins like eng.s01@test.ai-academy.asia (one shared password) and a
    course whose cohort is mid-way through, with sessions, attendance, progress,
    quizzes, homework and payments.
    """
    from app.seeds_programmes import PROGRAMMES, SeedExists, run
    from app.seeds_programmes import remove as remove_programme
    from app.services.learning.path import today

    keys = list(PROGRAMMES) if "all" in keys else list(keys)
    unknown = [k for k in keys if k not in PROGRAMMES]
    if unknown:
        raise click.BadParameter(f"{unknown}; choose from {list(PROGRAMMES)} or all")
    for key in keys:
        if remove:
            remove_programme(key)
            click.echo(f"{key}: removed")
            continue
        try:
            result = run(key, today=today(), reset=reset)
        except SeedExists as exc:
            raise click.ClickException(f"{exc} — re-run with --reset") from exc
        click.echo(
            f"{key}: course #{result['course_id']} {result['slug']} · "
            f"cohort #{result['cohort_id']} · {result['lessons']} lessons "
            f"{result['start']} → {result['end']}"
        )
        click.echo("  teachers: " + ", ".join(result["teachers"]))
        click.echo(f"  students: {result['students'][0]} … {result['students'][-1]}"
                   f"  (dropped out: {result['dropped']})")
    if not remove:
        click.echo(f"password for every login: {result['password']}")


def register_cli(app) -> None:
    from app.services.assignments.cleanup import files_cli

    app.cli.add_command(auth_cli)
    app.cli.add_command(files_cli)
    app.cli.add_command(ebarimt_cli)
    app.cli.add_command(mail_cli)
    app.cli.add_command(seed_cli)
