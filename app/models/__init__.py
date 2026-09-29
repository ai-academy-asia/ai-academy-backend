"""Import all models here so Flask-Migrate/Alembic can autodetect them."""
from .assignment import (  # noqa: F401
    SUBMISSION_STATUSES,
    Assignment,
    AssignmentSubmission,
    StudentFile,
)
from .auth_account import (  # noqa: F401
    ACTOR_STAFF,
    ACTOR_STUDENT,
    ACTOR_TEACHER,
    ACTOR_TYPES,
    AuthAccount,
)
from .certificate import Certificate, OtpVerification  # noqa: F401
from .classroom import Classroom  # noqa: F401
from .cohort import (  # noqa: F401
    COHORT_STATUSES,
    LEGACY_SCHEDULE_KINDS,
    Cohort,
    CohortLegacySchedule,
)
from .course import COURSE_LEVELS, COURSE_STATUSES, Course  # noqa: F401
from .ebarimt import EBARIMT_STATUSES, EBARIMT_TYPES, EBarimtReceipt  # noqa: F401
from .engagement import (  # noqa: F401
    ATTENDANCE_METHODS,
    ATTENDANCE_STATUSES,
    PUSH_PLATFORMS,
    Attendance,
    ClassSession,
    FirebaseToken,
    Notification,
)
from .enrollment import ENROLLMENT_STATUSES, Enrollment  # noqa: F401
from .enrolment import (  # noqa: F401
    BOOKING_STATUSES,
    DISCOUNT_TYPES,
    REQUEST_STATUSES,
    ClassroomRequest,
    Promotion,
    SeatBooking,
    new_payment_token,
)
from .exam import (  # noqa: F401
    Exam,
    ExamOption,
    ExamQuestion,
    StudentExam,
    StudentExamAnswer,
)
from .invoice import INVOICE_PROVIDERS, INVOICE_STATUSES, Invoice  # noqa: F401
from .learning import (  # noqa: F401
    LESSON_TYPES,
    MATERIAL_TYPES,
    CourseLesson,
    CourseTopic,
    LessonMaterial,
    LessonNote,
    LessonProgress,
)
from .ledger import (  # noqa: F401
    INSTALLMENT_STATUSES,
    PaymentInstallment,
    StudentLedger,
)
from .payment import PAYMENT_METHODS, PAYMENT_STATUSES, Payment  # noqa: F401
from .refresh_token import RefreshToken  # noqa: F401
from .staff import STAFF_ROLES, Staff  # noqa: F401
from .student import Student  # noqa: F401
from .teacher import Teacher  # noqa: F401

# Maps an auth account's actor_type to its profile model.
PROFILE_MODEL_BY_ACTOR = {
    ACTOR_STUDENT: Student,
    ACTOR_TEACHER: Teacher,
    ACTOR_STAFF: Staff,
}


def get_profile_model(actor_type: str):
    """Return the profile model class for an actor_type, or None if unknown."""
    return PROFILE_MODEL_BY_ACTOR.get(actor_type)
