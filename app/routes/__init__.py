"""Actor-oriented routers. `register_blueprints(app)` wires them all up.

- health : /, /health
- auth   : /auth/*                         (shared — all actors authenticate)
- student: public browse + student self-service (enroll / my cohorts)
- teacher: a teacher's own schedule
- admin  : back-office CRUD (students, teachers, classrooms, cohorts,
           course content, schedules)
"""


def register_blueprints(app):
    from .admin import bp as admin_bp
    from .auth import bp as auth_bp
    from .health import bp as health_bp
    from .student import bp as student_bp
    from .teacher import bp as teacher_bp

    for blueprint in (health_bp, auth_bp, student_bp, teacher_bp, admin_bp):
        app.register_blueprint(blueprint)
