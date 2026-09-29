# Mobile API V1 — endpoint index

Every endpoint the mobile app (student + teacher) integrates with, plus the staff endpoints
that feed it content. Base URL: `https://api.ai-academy.asia`.

- **Conventions** (auth, errors, ids, timestamps, 404-for-others'-data): see
  `docs/course_learning_api_contract_v1.md` §0 — they apply to every endpoint here.
- **JSON shapes** for the learning endpoints: the contract §2. Where the implementation
  added fields or error codes, they are listed under *Additions* below; nothing in the
  contract was removed.

Legend — **Who**: `S` student token · `T` teacher token (own cohorts) · `staff:<perm>` a
staff token with that permission (super_admin has all) · `—` no auth.

## 1. Account & session

| Method | Path | Who | Notes |
|---|---|---|---|
| POST | `/auth/login` | — | access + refresh token; `must_change_password` |
| POST | `/auth/refresh` | — | rotates the refresh token |
| POST | `/auth/logout` | — | revokes this device's refresh token |
| POST | `/auth/logout-all` | any | revokes every session |
| GET | `/auth/me` | any | account + profile |
| POST | `/auth/change-password` | any | |
| POST | `/auth/forgot-password` | — | always `200 {"status":"ok"}`; emails a 6-digit code (15 min) |
| POST | `/auth/reset-password` | — | `{email, code, new_password}`; any failure = `400 invalid_code`; revokes all sessions |
| PATCH | `/me/profile` | S, T | student: first/last name, phone; teacher: + bio |

## 2. Catalogue & enrolment

| Method | Path | Who | Notes |
|---|---|---|---|
| GET | `/courses`, `/courses/{slug}` | — | |
| GET | `/cohorts`, `/cohorts/{id}` | — | seats left |
| POST / DELETE | `/cohorts/{id}/enroll` | S | enrol / cancel |
| GET | `/me/cohorts` | S | my classes + schedule |

## 3. Learning (contract §2.1–2.5)

| Method | Path | Who |
|---|---|---|
| GET | `/me/courses/{slug}/learning` | S |
| GET | `/me/modules/{id}/lessons` | S |
| GET | `/me/lessons/{id}` | S |
| POST | `/me/lessons/{id}/complete` | S |
| PUT | `/me/lessons/{id}/note` | S |
| GET | `/me/materials/{id}/download` | S |

## 4. Assignments & files (contract §2.6, §2.8)

| Method | Path | Who |
|---|---|---|
| GET | `/me/assignments/{id}` | S |
| POST | `/me/assignments/{id}/submissions` | S |
| POST | `/me/files` | S |
| GET | `/me/files/{id}/download` | S |
| GET / POST | `/teacher/cohorts/{id}/assignments` | T, staff:cohort:manage |
| GET / PATCH / DELETE | `/teacher/assignments/{id}` | T, staff:cohort:manage |
| GET | `/teacher/assignments/{id}/submissions` | T, staff:cohort:manage |
| GET | `/teacher/submissions/{id}` | T, staff:cohort:manage |
| GET | `/teacher/submissions/{id}/file` | T, staff:cohort:manage |
| POST | `/teacher/submissions/{id}/review` | T, staff:cohort:manage |

## 5. Quizzes (contract §2.7)

| Method | Path | Who |
|---|---|---|
| POST | `/me/quizzes/{id}/attempts` | S |
| POST | `/me/quiz-attempts/{id}/answers` | S |
| POST | `/me/quiz-attempts/{id}/finish` | S |
| GET | `/me/quiz-attempts/{id}` | S |

## 6. Certificates (contract §2.9)

| Method | Path | Who |
|---|---|---|
| GET | `/me/courses/{slug}/certificate` | S |
| GET | `/me/certificates/{cert_number}/download` | S |
| GET | `/certificates/verify/{cert_number}` | — (public check page) |

## 7. Money

| Method | Path | Who | Notes |
|---|---|---|---|
| GET | `/me/ledger` | S | per enrollment: due/paid/balance + installments |
| GET | `/me/invoices` | S | history, `?status=&limit=` |
| POST | `/payments/invoices` | S | pay an enrollment / installment (`qpay`/`storepay`/`golomt`) |
| GET | `/payments/invoices/{id}` | S | QR, bank deeplinks |
| GET | `/payments/invoices/{id}/status` | S | poll until `paid` |
| GET | `/me/receipts`, `/me/receipts/{id}` | S | eBarimt receipts (`is_temp_mode` = not yet filed) |

## 8. Attendance & class sessions

| Method | Path | Who | Notes |
|---|---|---|---|
| POST | `/me/attendance/check-in` | S | `{token}` from the teacher's QR; `present`/`late` (>15 min) |
| GET | `/me/attendance?course={slug}` | S | sessions + attended % |
| GET / POST | `/teacher/cohorts/{id}/sessions` | T, staff:cohort:manage | |
| POST | `/teacher/cohorts/{id}/sessions/generate` | T, staff:cohort:manage | from the cohort's weekdays/dates |
| PATCH / DELETE | `/teacher/sessions/{id}` | T, staff:cohort:manage | |
| POST | `/teacher/sessions/{id}/qr` | T, staff:cohort:manage | rotating token, 5 min, session day only |
| GET | `/teacher/sessions/{id}/attendance` | T, staff:cohort:manage | roster with status |
| PUT | `/teacher/sessions/{id}/attendance/{student_id}` | T, staff:cohort:manage | manual mark |
| GET | `/teacher/cohorts/{id}/students` | T, staff:cohort:manage | class list |
| GET | `/teachers/{id}/schedule` | T (self), staff | |

A session's `topic_id` is what dates a module on the learning path (and locks it until then).

## 9. Notifications

| Method | Path | Who | Notes |
|---|---|---|---|
| POST / DELETE | `/me/push-tokens` | any | `{token, platform}` (`ios`/`android`/`web`) |
| GET | `/me/notifications` | any | `?limit=&before_id=`; `unread_count` |
| POST | `/me/notifications/{id}/read`, `/me/notifications/read-all` | any | |
| POST | `/admin/notifications` | staff:cohort:manage | to a cohort or to account ids |

Push delivery is **not active**: notifications are stored and listed in-app; sending via
FCM starts once `FCM_CREDENTIALS` is configured (`app/services/notifications/push.py`).

## 10. Staff content authoring (admin panel, not the app)

| Method | Path | Who |
|---|---|---|
| GET / POST | `/admin/courses/{id}/modules` | staff:course:edit |
| PATCH / DELETE | `/admin/modules/{id}` | staff:course:edit |
| GET / POST | `/admin/modules/{id}/lessons` | staff:course:edit |
| GET / PATCH / DELETE | `/admin/lessons/{id}` | staff:course:edit |
| GET / POST | `/admin/lessons/{id}/materials` | staff:course:edit (file ≤ 50 MB or link) |
| PATCH / DELETE | `/admin/materials/{id}` | staff:course:edit |
| GET / POST | `/admin/courses/{id}/quizzes` | staff:course:edit |
| GET / PATCH / DELETE | `/admin/quizzes/{id}` | staff:course:edit |
| PUT | `/admin/quizzes/{id}/questions` | staff:course:edit (replaces the set; `?force=true` if attempts exist) |
| GET | `/admin/quizzes/{id}/attempts` | staff:course:edit |
| GET / POST | `/admin/certificates` | staff:cohort:manage (issue checks eligibility unless `force`) |
| PUT | `/admin/certificates/{id}/file` | staff:cohort:manage (PDF ≤ 20 MB) |
| DELETE | `/admin/certificates/{id}` | staff:cohort:manage (archives) |

## Additions beyond the contract

- **Error codes** added where the contract said only "validate": `description_too_long`,
  `file_required`, `submission_conflict`, `invalid_question`, `invalid_field`,
  `field_too_long`, attendance/session time codes (`invalid_session_date`, …).
- **Fields** added (none removed): quiz attempts carry `quiz_id`, `status`; questions carry
  `image`; results carry `started_at`/`finished_at`; the quiz summary carries `is_required`;
  certificates carry `has_file`.
- **A quiz with no questions** behaves as absent for students (404 / `quiz: null`) and does
  not count toward certificate eligibility.
- **Finishing / reading a quiz attempt** works after the enrollment is cancelled (results
  stay readable); starting and answering require an active enrollment.
- **Assignment `instructions`** is `null` when empty in both languages.

## Operations

- `flask files cleanup` — deletes student uploads older than 24 h that no submission uses.
  Not scheduled yet; run it from cron (daily is enough).
