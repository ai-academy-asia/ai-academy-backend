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

Mobile learning surface (docs/course_learning_api_contract_v1.md), each with a
student side and a staff/teacher side:
- learning / learning_admin       : modules, lessons, materials, notes, progress
- assignments / assignments_staff : homework, submissions, uploads, review
- quizzes / quizzes_staff         : quiz attempts graded per answer, authoring
- account                         : /me money, receipts, profile; password reset
- certificates                    : student certificates, staff issuing
- attendance                      : class sessions, QR check-in, rosters
- notifications                   : push tokens, in-app notifications
"""


def register_blueprints(app):
    from .account import bp as account_bp
    from .admin import bp as admin_bp
    from .assignments import bp as assignments_bp
    from .assignments_staff import bp as assignments_staff_bp
    from .attendance import bp as attendance_bp
    from .auth import bp as auth_bp
    from .certificates import bp as certificates_bp
    from .ebarimt import bp as ebarimt_bp
    from .health import bp as health_bp
    from .learning import bp as learning_bp
    from .learning_admin import bp as learning_admin_bp
    from .notifications import bp as notifications_bp
    from .payments import bp as payments_bp
    from .public import bp as public_bp
    from .quizzes import bp as quizzes_bp
    from .quizzes_staff import bp as quizzes_staff_bp
    from .student import bp as student_bp
    from .teacher import bp as teacher_bp

    for blueprint in (health_bp, auth_bp, public_bp, student_bp, teacher_bp,
                      admin_bp, payments_bp, ebarimt_bp,
                      learning_bp, learning_admin_bp, assignments_bp, assignments_staff_bp,
                      quizzes_bp, quizzes_staff_bp, account_bp, certificates_bp,
                      attendance_bp, notifications_bp):
        app.register_blueprint(blueprint)
