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
| POST | `/auth/login` | — | access + refresh token; `must_change_password`; `user_type`. While `must_change_password` is true every signed-in route outside `/auth/*` answers 403 `password_change_required` |
| POST | `/auth/refresh` | — | rotates the refresh token |
| POST | `/auth/logout` | — | revokes this device's refresh token |
| POST | `/auth/logout-all` | any | revokes every session |
| GET | `/auth/me` | any | account + profile + `user_type` |
| POST | `/auth/change-password` | any | other devices signed out; **this** device gets a fresh token pair (same body as login) — store it |
| POST | `/auth/forgot-password` | — | always `200 {"status":"ok"}`; emails a 6-digit code (15 min) |
| POST | `/auth/reset-password` | — | `{email, code, new_password}`; any failure = `400 invalid_code`; revokes all sessions |
| PATCH | `/me/profile` | S, T | student: first/last name, phone; teacher: + bio |

**`user_type`** — on login, refresh, `/auth/me` and `PATCH /me/profile`: which app to open.

| Value | Who |
|---|---|
| `adult` | a student who is not a child |
| `child` | a student in kids mode — by, in order: the admin's `ui_mode` (`kids`/`adult`), else age under 18 from `birth_date`, else an active enrollment in a `junior` course |
| `teacher` | a teacher |
| `staff` | back-office staff (not a mobile user) |

Admins set or clear the override with `PATCH /admin/students/{id}` `{"ui_mode": "kids" \| "adult" \| ""}`.

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

## 6. Certificates (contract §2.9) — details: `docs/certificate_api_v1.md`

| Method | Path | Who |
|---|---|---|
| GET | `/me/certificates` | S — one card per course: status, requirements, certificate |
| GET | `/me/courses/{slug}/certificate` | S |
| GET | `/me/certificates/{cert_number}/download` | S — 5-min PDF link; generated from the course template on first use |
| GET | `/certificates/verify/{cert_number}?code=` | — (the QR; name shown only with the code; HTML for browsers) |

## 6a. E-contracts — see `docs/e_contract_api_v1.md`

Signed **in the app**: check details → preview PDF → agree + draw signature → signed PDF.
One contract per enrollment, created automatically when the course has a PDF contract template.

| Method | Path | Who | Notes |
|---|---|---|---|
| GET | `/me/contracts` | S | all mine, newest first; `can_sign`, `is_current` |
| GET | `/me/contracts/{id}` | S | prefilled `form`, `rules`, `finance` |
| POST | `/me/contracts/{id}/preview` | S | `{form}` → `application/pdf`, unsigned |
| POST | `/me/contracts/{id}/sign` | S | `{form, agreed: true, signature}`; `pending` → `signed` |
| GET | `/me/contracts/{id}/download` | S | `{url, expires_at}` once signed |
| GET | `/admin/contracts`, `/admin/contracts/{id}` | staff:cohort:manage | `?course_id=&cohort_id=&student_id=&status=` |
| GET | `/admin/contracts/{id}/download` | staff:cohort:manage | |
| POST | `/admin/contracts/{id}/reset` | staff:cohort:manage | signed → pending (student signs again) |

## 7. Money

| Method | Path | Who | Notes |
|---|---|---|---|
| GET | `/me/ledger` | S | per enrollment: due/paid/balance + installments |
| GET | `/me/invoices` | S | history, `?status=&limit=` |
| POST | `/payments/invoices` | S | pay an enrollment / installment (`qpay`/`storepay`/`golomt`); `enrollment_id` or `installment_id` required. Amount is server-decided: an installment bills exactly its amount (`amount` optional, else must match → 400 `amount_mismatch`); otherwise any part of the balance, default all of it (409 `amount_exceeds_balance` / `nothing_due` / `installment_settled`) |
| GET | `/payments/invoices/{id}` | S | QR, bank deeplinks |
| GET | `/payments/invoices/{id}/status` | S | poll until `paid` |
| GET | `/me/receipts`, `/me/receipts/{id}` | S | eBarimt receipts (`is_temp_mode` = not yet filed) |
| GET | `/admin/enrollments/{id}/installments` | staff:ledger:read | plan + ledger + frozen `price_amount` |
| POST | `/admin/enrollments/{id}/installments` | staff:installment:manage | add `{amount, due_date}` |
| POST | `/admin/enrollments/{id}/installments/default` | staff:installment:manage | course-rule plan for an older enrollment (409 `plan_exists`) |
| PATCH / DELETE | `/admin/installments/{id}` | staff:installment:manage | unpaid only (409 `installment_settled`, `installment_has_invoices`) |
| POST | `/admin/installments/{id}/waive` | staff:installment:manage | forgiven: drops out of `total_due` |

What is owed: the course's discounted price is frozen on the enrollment at enrolment
(`price_amount`) and a plan is laid out from the course rule (`installment_count` equal
payments, first on the cohort start date, then every `installment_interval_months`).
`total_due` = Σ non-waived installments, else the frozen price — a later course price
edit never changes it.

## 8. Attendance & class sessions

| Method | Path | Who | Notes |
|---|---|---|---|
| POST | `/me/attendance/check-in` | S | `{token}` from the teacher's QR; `present`/`late` (>15 min) |
| GET | `/me/attendance?course={slug}` | S | sessions + attended % |
| GET / POST | `/teacher/cohorts/{id}/sessions` | T, staff:cohort:manage | a session may carry `lesson_id` (sets its module): the lesson is then locked until that class, and `/me/modules/{id}/lessons` shows its `schedule` and `attendance` |
| POST | `/teacher/cohorts/{id}/sessions/generate` | T, staff:cohort:manage | from the cohort's weekdays/dates; never two sessions on one date. Body `{regenerate, assign_lessons}`: `regenerate` moves future sessions to a new time and drops days no longer met (past, marked or handed-over sessions are kept); `assign_lessons` gives sessions without a lesson the course's lessons in order |
| POST | `/admin/cohorts/{id}/sessions/generate` | staff:cohort:manage | same, for the Admin Panel |
| PATCH / DELETE | `/teacher/sessions/{id}` | T, staff:cohort:manage | |
| POST | `/teacher/sessions/{id}/qr` | T, staff:cohort:manage | rotating token, 5 min, session day only |
| GET | `/teacher/sessions/{id}/attendance` | T, staff:cohort:manage | roster with status |
| PUT | `/teacher/sessions/{id}/attendance/{student_id}` | T, staff:cohort:manage | manual mark |
| GET | `/teacher/cohorts/{id}/students` | T, staff:cohort:manage | class list |
| GET | `/teachers/{id}/schedule` | T (self), staff | + `covering_sessions` (accepted handovers) |
| GET | `/teacher/sessions?from=&to=` | T | own sessions (`regular`) + covered ones (`covering`) |
| GET | `/teacher/sessions/{id}/eligible-teachers` | T (cohort's teacher) | handover recipients |
| GET / POST | `/teacher/schedule-change-requests` | T | `?direction=sent\|received&status=` |
| GET | `/teacher/schedule-change-requests/{id}` | T (sender/recipient) | |
| POST | `/teacher/schedule-change-requests/{id}/accept\|reject\|cancel` | T | recipient / recipient / sender |

A session's `topic_id` is what dates a module on the learning path (and locks it until then).
Class handover (schedule-change) requests: see `docs/schedule_change_api_v1.md`.

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
| GET / POST | `/admin/certificates` | staff:cohort:manage (issue checks eligibility unless `force`; PDF made from the course template) |
| POST | `/admin/certificates/{id}/generate` | staff:cohort:manage (rebuild the PDF) |
| POST | `/admin/cohorts/{id}/certificates` | staff:cohort:manage (issue a whole class; `{force?, student_ids?}`) |
| PUT | `/admin/certificates/{id}/file` | staff:cohort:manage (PDF ≤ 20 MB) |
| DELETE | `/admin/certificates/{id}` | staff:cohort:manage (archives) |

## Additions beyond the contract

- **Module lock everywhere:** `409 lesson_locked` also comes from material download, quiz
  start and the assignment endpoints while the module's first class date is ahead.
- **Quiz percent is weighted by question `point`** (staff-set, default 1); `correct` / `total`
  still count questions. Pass/fail and certificates use the weighted percent.
- **Ungraded assignments** (`max_score: null`) can be reviewed with feedback only; `score` is
  then `null`.
- **Course status** is `draft` / `open` / `closed` everywhere: `open` = on sale (site + app),
  `closed` = still browsable in `/courses` but no longer sold, `draft` = hidden.

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
