"""One status vocabulary: a course is visible alike on the site, in /courses and in the app."""
import pytest

from app.models import Enrollment


def _on_site(client, course):
    return client.get(f"/classroom-courses/{course.id}").status_code == 200


def _in_courses(client, course):
    return course.slug in str(client.get("/courses").get_json())


@pytest.mark.parametrize("status,site,courses", [
    ("open", True, True),       # on sale: everywhere
    ("closed", False, True),    # finished: still browsable, no longer sold
    ("draft", False, False),    # nowhere
])
def test_status_means_the_same_everywhere(client, make_course, status, site, courses):
    course = make_course(status=status)
    assert _on_site(client, course) is site
    assert _in_courses(client, course) is courses


def test_open_course_reaches_the_mobile_app(client, db, make_student, make_course, make_cohort):
    account, headers = make_student()
    course = make_course(status="open")
    cohort = make_cohort(course=course)
    db.session.add(Enrollment(cohort_id=cohort.id, student_id=account.actor_id,
                              course_id=course.id, status="active"))
    db.session.commit()
    assert client.get(f"/me/courses/{course.slug}/learning", headers=headers).status_code == 200


def test_admin_cannot_set_the_retired_published_status(client, admin_headers, make_course):
    course = make_course()
    resp = client.patch(f"/courses/{course.slug}", headers=admin_headers,
                        json={"status": "published"})
    assert (resp.status_code, resp.get_json()["error"]) == (400, "invalid_status")
