"""Actor-oriented routers. `register_blueprints(app)` wires them all up.

- health  : /, /health
- auth    : /auth/*                         (shared — all actors authenticate)
- public  : the anonymous visitor — programme catalogue, enrolment form, seat
            hold and token-keyed checkout. No Authorization header anywhere.
- student : public browse + student self-service (enroll / my cohorts)
- teacher : a teacher's own schedule
- admin   : back-office CRUD (students, teachers, classrooms, cohorts,
            course content, schedules)
- payments: gateway callbacks + student self-pay + finance/refunds/ledger
- ebarimt : finance's eBarimt receipt back-office (/admin/ebarimt/*)
"""


def register_blueprints(app):
    from .admin import bp as admin_bp
    from .auth import bp as auth_bp
    from .ebarimt import bp as ebarimt_bp
    from .health import bp as health_bp
    from .payments import bp as payments_bp
    from .public import bp as public_bp
    from .student import bp as student_bp
    from .teacher import bp as teacher_bp

    for blueprint in (health_bp, auth_bp, public_bp, student_bp, teacher_bp,
                      admin_bp, payments_bp, ebarimt_bp):
        app.register_blueprint(blueprint)
