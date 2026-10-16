# AI Academy backend requirements specification — v1

One consolidated list of the backend work the mobile app and the Admin Panel still need.
For each item: what exists today, what is missing, and who can unblock it.
Tracking issue: [#5](https://github.com/ai-academy-asia/ai-academy-backend/issues/5).

**Audited on 2026-10-16** against:

| Component | Repository | Revision |
|---|---|---|
| Backend (this repo) | `ai-academy-asia/ai-academy-backend` | `main` at `c6e6ce0` |
| Push delivery (open PR) | [PR #4](https://github.com/ai-academy-asia/ai-academy-backend/pull/4), from the `AlimaaBayarmaa` fork | `a6f8767` |
| Mobile app (Flutter) | `ai-academy-asia/ai-academy-mobile-legacy` | `main` at `96f40ae` |
| Admin Panel (Next.js) | `ai-academy-asia/ai-academy-admin-panel` | `main`, plus branch `feat/quiz-management` (`e55452c`) |

**How to read it:**
- Statements about current behaviour cite the source: a file, route, test or Issue.
- Path prefixes: `backend:` for this repo, `mobile:` for the app, `panel:` for the Admin Panel.
- Anything not yet built is marked **PROPOSED**.
- Anything only an owner can answer is marked **DECISION**.
- Nothing here was verified against production. No production API was called, and no
  production data was read.

---

## 1. Purpose and scope

The aim is for the manager to review **one** document and take each decision once, instead
of receiving separate small requests.

Areas covered:
- authentication and user lifecycle;
- Course Learning;
- FCM push;
- E-Contract;
- Admin Panel self-service;
- other gaps found in the mobile API clients.

Pure UI defects are excluded unless they expose a missing backend contract.

**Not in scope:**
- implementing anything;
- changing PR #4;
- production configuration, credentials or deployments.

---

## 2. Executive summary

- **The backend is further ahead than the open requests suggest.** Many items the mobile docs
  still call "backend gaps" already exist on `main` (§3.3). They need mobile integration, not
  backend work.
- **The test suites pass.** Run locally on 2026-10-16 against a disposable local database:
  `main` passes **1,239** tests and PR #4 passes **1,253**. Ruff and the 300-line check are
  clean on both.
- **19 verified backend gaps** (table §4.1):
  - 2 are P0;
  - 7 are P1;
  - 10 are P2.

  Another 10 items are Admin Panel UI work over APIs that already exist, and 1 Admin Panel need (ADM-11) has no API yet (§4.2).

**Immediate blockers (P0):**
1. **Push delivery is not on `main`.**
   - On `main`, `send_push` is a logged no-op. With credentials set it still says
     "delivery is not implemented" (`backend:app/services/notifications/push.py:20-27`).
   - PR #4 implements FCM HTTP v1 delivery. Its CI run is waiting for maintainer approval
     (`action_required`, run 38736015972).
   - **Merging PR #4 deploys it to production automatically** (§5.1.5).
2. **The production server has no FCM credentials.** `FCM_CREDENTIALS` must be added to the
   server `.env`. Deploys never copy `.env` (`.github/workflows/deploy.yml`, rsync
   `--exclude '.env'`).

**What we can do ourselves, without the manager:**
- All test-data work on the local backend: seeding, enrolling, sessions, resets.
- Every Admin Panel page over existing APIs (§6.2).
- The P1/P2 code items whose behaviour is already decided:
  - AUTH-1 (server-side enforcement of `must_change_password`);
  - CL-4 (note lock check);
  - CL-5 (`has_note`);
  - the Issue #1 PR.
- Mobile integration of the APIs listed in §3.3.

**Only the manager or account owner can provide:**
- PR #4 approval and merge (which is a production deploy);
- the production Firebase project and server credentials;
- legally approved contract templates, and approval of a live signing test;
- six product decisions (§10).

---

## 3. Current architecture and evidence

### 3.1 Components inspected

- **Backend (Flask, PostgreSQL, S3):**
  - Routes are in `backend:app/routes/*.py` and models in `backend:app/models/*.py`.
  - Permissions are in `backend:app/auth/permissions.py`. Roles are `super_admin`, `finance`,
    `sales_enrollment` and `content_marketing`. `student` and `teacher` have no back-office
    permissions.
  - CI: `.github/workflows/deploy.yml` runs lint, then tests, then deploy on push to `main`.
- **Mobile:**
  - API clients are in `mobile:lib/features/*/data/http_*_repository.dart`.
  - Contracts and gap labels are in `mobile:docs/ai/DATA_AND_API.md` and
    `mobile:docs/ai/PROJECT_CONTEXT.md`.
- **Admin Panel:**
  - Sign-in is for `super_admin` only (`panel:src/lib/auth/session-core.ts`).
  - The sidebar has Students, Courses, Classrooms and Staff (`panel:src/components/layout/nav-items.ts`).
  - Quiz management exists only on the unmerged branch `feat/quiz-management`, which also has
    uncommitted work in progress.
- **Not audited:** `admin-web`, a local-only scaffold with no remote and one commit. It runs on
  mocks; its endpoint map is intentionally empty (`admin-web:src/lib/api/endpoints.ts`).

### 3.2 Related Issues and PRs

| Item | State | Relevance |
|---|---|---|
| backend [#2](https://github.com/ai-academy-asia/ai-academy-backend/issues/2), [#3](https://github.com/ai-academy-asia/ai-academy-backend/issues/3), [PR #4](https://github.com/ai-academy-asia/ai-academy-backend/pull/4) | Open | FCM delivery, error tests |
| backend [#1](https://github.com/ai-academy-asia/ai-academy-backend/issues/1) | Open | Module on teacher assignments. Done locally (`674ef74`) but never pushed |
| mobile [#414](https://github.com/ai-academy-asia/ai-academy-mobile-legacy/issues/414) | Open, blocked | Per-lesson schedule and attendance (CL-1) |
| mobile [#324](https://github.com/ai-academy-asia/ai-academy-mobile-legacy/issues/324) | Open | Approved live e-contract signing test (EC-2) |
| mobile [#154](https://github.com/ai-academy-asia/ai-academy-mobile-legacy/issues/154) | Open | Assignment link or file (CL-2) |
| mobile [#293](https://github.com/ai-academy-asia/ai-academy-mobile-legacy/issues/293) | Open | Push readiness; Android side shipped |

### 3.3 Already provided on `main`, so nothing to ask the backend for

These are cleared by code evidence. The work left is mobile integration or a docs update.

| Capability | Evidence |
|---|---|
| Teacher schedule-change requests, eligible teachers, covering sessions | `backend:app/routes/schedule_changes.py`, `docs/schedule_change_api_v1.md`, `tests/test_schedule_change_*.py` |
| `/me/certificates` (one card per course), `can_download`, PDF generated on first download | `backend:app/services/certificates/mine.py`, `tests/test_certificate_cohort_mine.py`, `tests/test_certificate_generation.py` |
| Notification pagination (`?before_id=`), `read-all` | `backend:app/routes/notifications.py:30-45` |
| Push-token register, move and delete (idempotent) | `backend:app/services/notifications/push.py:30-76`, `tests/test_notifications_inbox.py::test_push_token_moves_between_accounts` |
| Ledger installments `{id, seq, due_date, amount, status, paid_at}`; invoice and payment shapes | `backend:app/services/account/money.py:29-37`, `app/models/invoice.py:80-102` |
| Teacher view of a submission's file (presigned) | `GET /teacher/submissions/{id}/file`, `tests/test_assignment_review.py::test_submission_file_presigned` |
| The login response carries `must_change_password`; change-password and reset clear it | `backend:app/routes/auth.py:22-36,118` |
| Forgot/reset password by e-mail code; `logout-all`; `PATCH /me/profile` | `backend:app/routes/account.py`, `tests/test_account_password_reset.py`, `tests/test_account_profile.py` |
| Shape of a resumed quiz attempt's `answer` | `backend:app/services/quizzes/payloads.py`, `tests/test_quiz_attempts.py::test_resume_returns_same_attempt_and_reveals_only_answered` |
| Lesson video URL (`video.embed_url`, from `CourseLesson.classroom_embed_url`) | `backend:app/models/learning.py:51`, `tests/test_learning_lessons.py` |
| E-Contract: list, detail, preview, sign, download, staff reset | `backend:app/routes/contracts.py`, `tests/test_contracts_{student,sign,staff,pdf}.py` |

---

## 4. Requirements matrix

Each gap below is a verified backend gap or decision. Priority definitions are in §9.

### 4.1 Backend

| ID | Feature | Current status | Evidence | Exact missing behaviour | Proposed implementation / acceptance | Admin Panel resolves it? | Priority | Dependencies / owner |
|---|---|---|---|---|---|---|---|---|
| PUSH-1 | FCM delivery | Built in PR #4; `main` is a no-op | `push.py:20-27` (main); PR #4 `app/services/notifications/fcm.py`, `tests/test_notifications_push.py` (14 tests) | No push reaches any device | Approve the CI run, review, merge. Acceptance: CI green, and a staging or test push received | No | **P0** | Maintainer (approval and merge = production deploy) |
| PUSH-2 | Production FCM configuration | Not configured | PR #4 `.env.example`; deploy excludes `.env` | `FCM_CREDENTIALS` is absent on the server | Owner adds one-line service-account JSON to the server `.env` and restarts. Acceptance: log line `push: kind=… reached>0` | No | **P0** | Firebase project owner and server owner |
| PUSH-3 | Transient FCM errors | Logged and dropped | PR #4 `fcm.py` (only 400 and 403 tested) | No retry for `UNAVAILABLE`, `INTERNAL` or `QUOTA_EXCEEDED`; sends are synchronous inside the request | §5.1.4 | No | P2 | Us; only when volume grows |
| PUSH-4 | Teacher announcements ("Зар тараах") | Not available to teachers | `notifications.py:51` requires `cohort:manage`; the teacher role has none (`permissions.py:29`) | A teacher cannot notify their own cohort | **PROPOSED** API §7.4 | No | P1 | **DECISION D3**, then us |
| AUTH-1 | `must_change_password` enforcement | Advisory only | The flag is never checked in `app/auth/` (grep: only `service.py` provisioning) | A temporary-password session can call every API | Middleware answers `403 password_change_required` (§7.1) | No | P1 | Us |
| AUTH-2 | Back-office staff accounts | CLI only | `backend:app/cli.py:29` `create-staff`; no `/admin/staff` route | Staff (finance, sales) cannot be created or deactivated through the API | `/admin/staff` CRUD, `super_admin` only | No | P2 | **DECISION**, if ops needs it |
| AUTH-3 | Breadth of `sales_enrollment` | Can hard-delete students and teachers | `permissions.py` (`student:manage`, `teacher:manage`); `routes/admin.py` DELETE | Possibly broader than intended | Confirm, or split out `*:delete` | No | P2 | **DECISION** |
| EC-1 | Contract templates | API exists; no template seeded locally; production state unknown | `PUT /admin/courses/{id}/templates/contract` (`routes/admin.py:193-217`); only `.pdf` produces contracts (`services/courses.py:38-42`) | No contract appears until a course has an approved `.pdf` template | Upload approved templates per course (API or panel, §6.2) | API: **yes, now**. Panel: needs a page | P1 | **Legal or manager** supplies the template |
| EC-2 | Live signing test (mobile #324) | Backend complete; mobile signing disabled by product decision | `mobile:lib/features/contracts/presentation/contract_screen.dart:36-66` | A disposable contract and approval; S3 access for a non-production run | Run the #324 checklist on a test account; reset with `POST /admin/contracts/{id}/reset` | Reset: API yes | P1 | **DECISION D5**; test S3 bucket |
| EC-3 | Local or test S3 | Not configurable | `backend:app/config.py:84-86` (`AWS_REGION`, `S3_BUCKET`, `S3_PREFIX`); no `endpoint_url` anywhere in `app/` | Preview, sign, materials and certificates cannot run end to end without real AWS | **PROPOSED** `S3_ENDPOINT_URL` (MinIO), §7.6 | No | P2 | Us |
| EC-4 | Explicit contract cancel | Only implicit | Cancelled when the enrollment becomes inactive (`services/contracts/core.py:54`) | No staff "cancel" without removing the enrollment | Add only if ops asks | Workaround: remove the enrollment | P2 | DECISION, low |
| CL-1 | Per-lesson class date and attendance (mobile #414) | Missing | `ClassSession` has `topic_id` (module), with no `lesson_id` (`backend:app/models/engagement.py:17-37`); `/me/attendance` sessions carry `topic_id` only | The Junior map's states "check-in required" and "attendance completed" cannot be derived per lesson | **PROPOSED** §7.2 | No | P1 | **DECISION D2**, then us |
| CL-2 | Assignment submission type (link, file or both) | Missing | No field on `Assignment` (`backend:app/models/assignment.py`); either is accepted (`services/assignments/student.py:113`) | The app cannot know which form to show, so every assignment uses the link form | **PROPOSED** §7.3 | No | P1 | **DECISION D1**, then us |
| CL-3 | What completes a lesson | Endpoint only | `POST /me/lessons/{id}/complete` (`tests/test_learning_lessons.py::test_complete_is_idempotent_and_updates_progress`); check-in writes only `Attendance` (`services/attendance/checkin.py`), although contract §2.3 says attendance "can" complete a lesson | No trigger is defined | Implement whichever trigger D4 chooses | No | P1 | **DECISION D4** |
| CL-4 | Note save ignores the lesson lock | Bug-level | `put_note` uses `lesson_for_student`, not the lock check (`services/learning/student.py`) | Notes can be written on locked lessons | Answer `409 lesson_locked`, as `GET /me/lessons/{id}` does | No | P2 | Us |
| CL-5 | `has_note` in the lesson list | Missing field | `/me/modules/{id}/lessons` item has no note flag | The app makes N detail calls per module | Add `has_note: bool` (§7.7) | No | P2 | Us |
| CL-6 | Teacher exam / quiz results | Missing for teachers | Only `GET /admin/quizzes/{id}/attempts` (`course:edit`, `routes/quizzes_staff.py:56`) | "Шалгалтын дүн" and the Junior exam badge have no source | **PROPOSED** §7.5 | No | P2 | **DECISION D6** |
| CL-7 | Per-student attendance for teachers | Missing aggregate | `/teacher/cohorts/{id}/students` returns `student_id, enrollment_id, name, phone` (`services/attendance/sessions.py:64-69`) | The gradebook shows "—" | Add `attendance{attended,total_past,percent}` using the existing student rule (`services/attendance/student.py:42-46`) | No | P2 | Us |
| CL-8 | Module on teacher assignments (Issue #1) | Done locally, not pushed | Local branch `feature/1-assignment-module-metadata` (`674ef74`, `tests/test_assignment_modules.py`) | Not on any remote | Push and open a PR | No | P2 | Us |

### 4.2 Admin Panel: APIs exist, no page

These need panel work only; the backend is ready. Details are in §6.

| ID | Area | API | Priority |
|---|---|---|---|
| ADM-1 | Cohorts (create; teacher, classroom, schedule) | `/admin/cohorts[/<id>]` (`cohort:manage`) | P1 |
| ADM-2 | Enrollment and roster | `POST /admin/cohorts/<id>/enroll`, `GET`/`DELETE /admin/cohorts/<id>/students[/<sid>]` | P1 |
| ADM-3 | Class sessions (needed for attendance and module locks) | `/teacher/cohorts/<id>/sessions[/generate]`, `/teacher/sessions/<id>` (super_admin passes) | P1 |
| ADM-4 | Announcements | `POST /admin/notifications` | P1, after PUSH-1 |
| ADM-5 | Contracts list, reset and templates | `/admin/contracts*`, `/admin/courses/<id>/templates/contract` | P1 |
| ADM-6 | Quizzes | `/admin/courses/<id>/quizzes`, `/admin/quizzes/<id>*`. The panel branch `feat/quiz-management` needs finishing and merging | P1 |
| ADM-7 | Certificates and templates | `/admin/certificates*`, `/admin/cohorts/<id>/certificates`, templates `kind=cert` | P2 |
| ADM-8 | Lesson video URL and material cohort scoping | `PATCH /admin/lessons/<id>` (`classroom_embed_url`), material `cohort_id` | P2 |
| ADM-9 | Student birth date and parent contact | `PATCH /admin/students/<id>` accepts `birth_date`, `parent_name`, `parent_phone` (`services/users.py:19-20`) | P2 |
| ADM-10 | Payments, ledger, eBarimt | `/admin/invoices*`, `/admin/ledger/*`, `/admin/ebarimt*` | P2 |
| ADM-11 | Schedule-change oversight | **No admin route.** All routes are `actor_required("teacher")` (`routes/schedule_changes.py:14`) | P2, needs backend |

---

## 5. Detailed requirements

### 5.1 FCM push

**5.1.1 Already on `main`:**
- **Token storage and API:**
  - Tokens live in `firebase_tokens` (`FirebaseToken`, `app/models/engagement.py:63-76`).
    Platforms are `ios`, `android` and `web`.
  - `POST /me/push-tokens` is an upsert (201 when new, 200 when known). It moves a token
    between accounts.
  - `DELETE /me/push-tokens` removes the caller's own token only, and is idempotent.
  - There is no per-account cap.
  - Logout does not remove tokens; the app removes its own before signing out
    (`mobile:lib/features/notifications/push/push_notifications.dart`).
- **Triggers:** every push goes through `inbox.notify()` (`services/notifications/inbox.py`),
  best-effort after the inbox rows are committed.
  - `announcement`: `POST /admin/notifications`, `services/notifications/broadcast.py:41-61`;
  - `schedule_change_request` and `schedule_change_response`:
    `services/schedule_changes/requests.py`, `decisions.py`.

**5.1.2 Added by PR #4** (Issues #2 and #3):
- **Sender and authentication:**
  - FCM HTTP v1 `messages:send`, authorised with a service-account JWT grant.
  - The access token is cached until 60 s before expiry and refreshed on a 401.
- **Payload:** `notification{title, body?}`, plus `data` with every value as a string and
  reserved keys dropped. It also sets `data.kind`, the recipient's own `data.notification_id`,
  Android `priority: HIGH` and APNs `sound: default`.
- **Error handling:**
  - `UNREGISTERED` deletes the token.
  - Other errors are logged and keep the token.
  - A network failure skips that one device only.
- **Configuration:** `FCM_CREDENTIALS` (inline JSON or a file path) and `FCM_HTTP_TIMEOUT`
  (default 10 s).
- **Tests:** 14 in `tests/test_notifications_push.py`.

**5.1.3 What the mobile app consumes:**
- The tap handler reads only `data.notification_id`. It opens the Notification screen, then
  the matching detail.
- No code branches on `kind` (`mobile:lib/features/notifications/push/push_messaging.dart:14-33`).
- **No new notification kinds are required.** Assignment, grade and payment notifications exist
  only as seed rows (`app/seeds_programmes/homework_money.py:128-139`). Nothing in the app needs
  them, so they are deliberately not requested here.

**5.1.4 Remaining code (P2, PUSH-3).** Do this when announcement volume justifies it, not
before:
- Retry `UNAVAILABLE` and `INTERNAL` with exponential back-off, up to 3 attempts, honouring
  `Retry-After`.
- On `QUOTA_EXCEEDED`, stop the batch and log it.
- Move delivery out of the request (a queue or background worker) once a cohort exceeds about
  100 devices.
- Acceptance: unit tests for each error class, and no token deleted on a transient error.

**5.1.5 Deployment.**
- Merging to `main` runs `deploy.yml`:
  1. rsync to the server (excluding `.env` and `.secrets`);
  2. `docker compose --profile prod up -d --build`;
  3. health check of `https://api.ai-academy.asia/health`.
- So **merge = production deploy.**
- Without `FCM_CREDENTIALS` on the server, the merged code stays a logged no-op. Order:
  1. merge;
  2. set credentials;
  3. restart;
  4. send one test announcement to a test cohort.
- The `action_required` CI state is GitHub's approval gate for workflow runs on fork PRs. That
  is inferred: the repository itself does not configure it.

**5.1.6 iOS** is not a backend task:
- an APNs key uploaded to Firebase, and the iOS push capability (Apple account owner);
- protected Xcode changes in the mobile repo (mobile `DATA_AND_API.md` §1.2).

### 5.2 E-Contract

**Supported today (all in this repo; no external signing provider):**
- A grep for docusign, signnow, hellosign, e-mongolia and HTTP clients in
  `app/services/contracts` finds nothing.
- **Lifecycle:**
  - One `StudentContract` per enrollment (`app/models/contract.py`), created lazily by
    `core.sync()` when the course has a `.pdf` template.
  - Status changes:
    - `pending` → `signed`;
    - `pending` → `cancelled` when the enrollment becomes inactive;
    - `cancelled` → `pending` when it is reactivated.
  - Only a staff reset reopens a signed contract.
- **Rules:**
  - Junior courses require a guardian.
  - A positive balance requires a final payment date, between today and the cohort end.
  - Field validation is in `services/contracts/fields.py`.
- **Signing:** the drawn signature PNG is stamped into the template (`pypdf`, `reportlab`).
  The signed PDF and the signature are stored in S3, and downloads use a presigned URL
  (300 s).
- **Staff:** `GET /admin/contracts`, detail and download, and `POST /admin/contracts/{id}/reset`
  (`cohort:manage`).
- **Tests:** 42 across `tests/test_contracts_{student,sign,staff,pdf}.py`.

**Mobile:** form, preview, signature, success and download are built. "Гэрээ байгуулах" stays
disabled until #324 is approved and passes (`contract_screen.dart:36-66`).

**Missing:**
- **EC-1:** an approved template per course. This is content, not code.
- **EC-2:** the approved test.
- **EC-3:** a non-AWS storage option for local runs.
- **EC-4:** explicit cancel (optional).

**Safe test path (no production):**
1. Run the local backend with a seeded programme.
2. Upload a **test** template through the staff API.
3. Point the debug app at the local backend (mobile `DATA_AND_API.md` §3.1).

Preview and sign need S3: either a dedicated **test** bucket, or EC-3. Without S3, the list,
detail, form, rules and error states can still be tested. Reset makes a test contract
reusable.

### 5.3 Course Learning

Status for each flow:

| Flow | Status | Notes |
|---|---|---|
| Enrollment, modules, lessons, lesson detail | Implemented and verified | `tests/test_learning_path.py`, `test_learning_lessons.py`, `test_student_enrolment.py` |
| Materials and downloads | Implemented and verified | `tests/test_learning_notes_materials.py`, `test_learning_admin_materials.py` |
| Notes | Implemented | Gap CL-4: no lock check |
| Assignments: submit, version, review, score, feedback, files | Implemented and verified | `tests/test_assignment_{student,files,review}.py`. Gap CL-2: submission type |
| Quizzes: start, resume, answer, finish, attempts, weighting | Implemented and verified | `tests/test_quiz_{attempts,answers,summary}.py`. Pass/fail and images are drawn nowhere in the app (mobile UI work) |
| Progress and completion | Endpoint implemented | Trigger missing (CL-3) |
| Attendance check-in and summary | Implemented and verified | `tests/test_attendance_*.py`. Gap CL-1: no per-lesson link |
| Certificates | Implemented and verified | §3.3. The app still builds this itself and should adopt `/me/certificates` and `can_download` |
| Video | URL delivered; admins must fill it | Mobile has no player (mobile UI). The panel doesn't expose the field (ADM-8) |

### 5.4 Authentication and user lifecycle

**Complete:**
- login, refresh with rotation and reuse detection, logout and logout-all;
- `/auth/me`, change and reset password;
- staff create, update, deactivate (which revokes sessions), delete and reset-password for
  students and teachers;
- self-service profile edit.

`user_type` comes from `ui_mode`, then age, then a junior enrollment
(`app/auth/user_type.py:35-48`).

**Gaps:** AUTH-1 (enforcement), AUTH-2 (staff API), AUTH-3 (permission breadth).

**Not requested:**
- self-registration;
- self-service account deletion (accounts are created by staff; see Q2);
- avatars;
- locale, theme or notification preferences.

The app has no requirement for these beyond inert controls. They are product choices, not
backend gaps.

### 5.5 Admin Panel operational requirements

The panel supports students, teachers, courses, classrooms, and modules, lessons, materials
and sections (§6). For day-to-day operation of the mobile features, the order that matters
is:
1. cohorts (ADM-1);
2. enrollment (ADM-2);
3. sessions (ADM-3);
4. contract templates (ADM-5);
5. announcements (ADM-4).

Without these pages, staff need direct API calls for routine work.

**Caution:** the local `panel:.env.local` currently sets `API_MODE=http` against the
production host. Point it at a local backend (`API_BASE_URL=http://localhost:8000`) before any
test-data work.

### 5.6 Other verified gaps

| Item | Evidence | Owner |
|---|---|---|
| A notification with a `null` body is dropped by the app | The backend allows it (`broadcast.py:47-49`; `inbox.py:21` returns `n.body`). The mobile parser requires a String (`http_notification_repository.dart:259`) | **Mobile fix**: treat the body as optional. No backend change |
| Bank-transfer instructions are not returned to the student | Built in `app/payments/golomt.py:166-181` and stored in `provider_meta`, which `Invoice.to_dict` omits (`app/models/invoice.py`) | P2. Only when mobile payments are integrated (they run on fixtures today) |
| No student-accessible eBarimt receipt file or QR | `/admin/ebarimt/{id}/qr` is staff-only (`app/routes/ebarimt.py:84`) | P2, same condition |
| `photo_url` is always null for eligible teachers | `app/services/schedule_changes/serialize.py:17`; no avatar field on `PersonProfile` | P2, only if a photo is wanted |
| `/me/cohorts` has no `progress_pct` | `services/schedules.py:104-106` returns `cohort.to_dict()` | Low. The app reads progress from `/learning` |

---

## 6. Admin Panel self-service checklist

### 6.1 What we can do now, without the manager

Use the local backend (`flask seed programme <key>`, see the README) and the staff API, or the
panel pointed at local:
- create, edit, deactivate and reset students and teachers;
- create courses, modules, lessons, materials and lesson sections;
- enroll and remove students (`/admin/cohorts/<id>/enroll`, API only);
- create and generate class sessions (API);
- upload a **test** contract template, list contracts, and reset a signed test contract
  (API);
- send an in-app announcement to a test cohort (`POST /admin/notifications`);
- issue or archive test certificates (API);
- tear down with `flask seed programme <key> --remove`, then admin `DELETE` and contract reset.

### 6.2 What needs an Admin Panel enhancement (no backend change)

ADM-1 to ADM-10 (§4.2). The order follows §9.

### 6.3 What needs backend work

PUSH-1, plus the server configuration in PUSH-2; AUTH-1 to AUTH-3; EC-3 and EC-4; CL-1 to
CL-8; ADM-11; PUSH-3 and PUSH-4 (§4.1).

---

## 7. API contract proposals

**Everything in this section is PROPOSED. None of it exists yet.** Every error uses the
existing `{"error": "<code>"}` envelope.

### 7.1 Enforce `must_change_password` (AUTH-1)

- **Behaviour:** while the flag is true, every authenticated request answers
  `403 {"error":"password_change_required"}`. Exempt: `GET /auth/me`,
  `POST /auth/change-password`, `/auth/logout`, `/auth/logout-all` and `/auth/refresh`.
- **Where:** `app/auth/middleware.py`, after the account is loaded.
- **Compatibility:** the mobile app already routes such accounts to change-password before
  Home (mobile `DATA_AND_API.md` §5). The panel shows the flag.
- **Tests:**
  - a flagged account gets 403 on `/me/cohorts`;
  - the exempt routes still work;
  - after change-password, access is restored.

### 7.2 Per-lesson class session (CL-1, after D2)

- **Schema:** `class_sessions.lesson_id` (nullable FK to `course_lessons`, `ON DELETE SET NULL`).
- **Writes:**
  - `POST /teacher/cohorts/{id}/sessions` and `PATCH /teacher/sessions/{id}` accept `lesson_id`.
    It must belong to a module of the cohort's course, otherwise `400 invalid_lesson`.
  - `…/sessions/generate` may map sessions to lessons in course order.
- **Reads:**
  - `/me/attendance` sessions add `lesson_id`.
  - `/me/modules/{id}/lessons` items add `session: {date, start_time, end_time, attendance_status} | null`.
- **Authorization:** unchanged (teacher of the cohort, or `cohort:manage`).
- **Tests:**
  - mapping validation;
  - a lesson without a session reads `null`;
  - attendance status per lesson;
  - existing module-lock behaviour unchanged.

### 7.3 Assignment submission type (CL-2, after D1)

- **Schema:** `assignments.submission_types` (JSON array of `link` and/or `file`, default
  `["link","file"]`, which matches today's behaviour).
- **Fields:** the student `assignment` shape and the teacher assignment shape add
  `submission_types`. Teacher create and update accept it (`400 invalid_submission_types`
  when empty or unknown).
- **Submit:**
  - `POST /me/assignments/{id}/submissions` answers `400 submission_type_not_allowed` when it
    carries a type that isn't allowed;
  - `400 submission_empty` is unchanged.
- **Idempotency:** unchanged; each submission is a new version.

### 7.4 Teacher announcement to their own cohort (PUSH-4, after D3)

`POST /teacher/cohorts/{id}/announcements`

- **Request:** `{"title": "…", "body": "…"}`
- **Response:** `201 {"sent": 23}`
- **Authorization:** `actor_required("teacher")`, and the teacher must teach the cohort.
  Otherwise `404 cohort_not_found`, which doesn't confirm the cohort exists.
- **Validation:** `title` is required, up to 200 characters. `body` is a string or omitted.
- **Delivery:** reuses `broadcast.send_announcement` with kind `announcement`, so inbox and push
  follow automatically.
- **Idempotency:** none. Optionally reject an identical title and body to the same cohort within
  60 s with `409 duplicate_announcement`.

### 7.5 Teacher quiz results (CL-6, after D6)

`GET /teacher/cohorts/{id}/quiz-results?student_id=`

- **Response:** `{items:[{student_id, quiz_id, quiz_title, lesson_id, best_percent, last_percent, passed, attempts_used}]}`
- **Authorization:** the cohort's teacher, or `cohort:manage`.
- **Data:** read-only over existing `StudentExam` rows.

### 7.6 S3 endpoint override for local and test runs (EC-3)

- **Config:** `S3_ENDPOINT_URL` (optional). When set, the boto3 client uses it (for example a
  MinIO container added to the dev Compose profile, which has none today).
- **Production:** unchanged when unset.
- **Tests:** client construction with and without the variable.

### 7.7 Lesson list `has_note` (CL-5)

`/me/modules/{id}/lessons` items add `has_note: bool`, true when the student has a non-empty
note. No new query per lesson: one grouped query per module.

---

## 8. Test and acceptance plan

**Unit and integration:**
- Run `python -m pytest -q` against a disposable local database. `tests/conftest.py` refuses
  any host that isn't local and any database name that doesn't end in `_test`.
- Every proposal in §7 ships with route-level tests in the style of
  `tests/test_schedule_change_*.py`.
- CI runs the same suite, plus ruff and the 300-line check.

**End to end, local only:**
1. Backend: `docker compose --profile dev up -d`, `flask db upgrade`,
   `flask seed programme <key>` (seeded `@test.ai-academy.asia` logins).
2. Mobile: a debug build with `--dart-define=AIA_API_BASE_URL=http://10.0.2.2:8000` (Android
   emulator). The red "API: host" pill confirms the override.
3. Panel: `API_MODE=http`, `API_BASE_URL=http://localhost:8000`.
4. Push: PR #4 branch plus a **test** Firebase project's key in the local `.env` only. Send one
   announcement to the seeded cohort.
5. Contracts: a test template and a test S3 bucket (or EC-3). Reset after each sign.
6. Clean up: `flask seed programme <key> --remove`, delete the test accounts, reset contracts,
   and delete test tokens with `DELETE /me/push-tokens`.

**Production:** only the owner-run checks in §10 (one test push after PUSH-2, and #324 once
approved). No other production side effects.

---

## 9. Prioritised roadmap (ordered by dependency)

**P0: true blockers**
1. PUSH-1: approve the CI run, review and merge PR #4. This is a production deploy.
2. PUSH-2: set `FCM_CREDENTIALS` on the server, restart, send one test announcement.

**P1: unblocks features the app already has**
1. AUTH-1: enforce `must_change_password`. Independent; we can start now.
2. ADM-1, ADM-2, ADM-3: cohorts, enrollment and sessions pages. These come before anything that
   needs real cohorts and sessions.
3. ADM-6: finish and merge the panel quiz branch.
4. EC-1 and ADM-5: templates and the contracts page. Then EC-2, the #324 test, after D5.
5. ADM-4: announcements page, after PUSH-1.
6. CL-2: after D1. CL-1: after D2, and it builds on ADM-3. CL-3: after D4.
7. PUSH-4: after D3.

**P2: secondary**
- CL-4, CL-5, CL-7, CL-8 (push Issue #1), EC-3, EC-4, PUSH-3;
- AUTH-2, AUTH-3, CL-6 (after D6);
- ADM-7 to ADM-11;
- the payment items in §5.6.

---

## 10. Manager and account-owner actions

Only items we cannot complete ourselves:

| # | Action | Why |
|---|---|---|
| M1 | Approve the CI run on PR #4, review and merge it (or delegate) | Only maintainers can approve fork workflow runs and merge, and merge deploys to production |
| M2 | Name the **production** Firebase project, then (a) put its service-account key into the server `.env` as `FCM_CREDENTIALS` and (b) provide its `google-services.json` for the release build | Credentials and server access are owner-only |
| M3 | Provide the legally approved contract PDF template(s), per course, with placeholders | Legal content (EC-1) |
| M4 | **D5:** approve the #324 live signing test (who, when, which disposable contract), and provide a test S3 bucket or accept EC-3 | Signing is irreversible for the student; storage is AWS-owned |
| M5 | Product decisions **D1–D4, D6** (below) | They change behaviour and data |
| M6 | Later, for iOS push: APNs key and the iOS push capability | Apple account owner |

**Decisions:**

| ID | Question |
|---|---|
| D1 | Does an assignment take a link, a file, or either? Is it set per assignment? (CL-2) |
| D2 | Does each class session correspond to exactly one lesson, so it can be mapped? (CL-1) |
| D3 | May teachers send announcements to their own cohorts? (PUSH-4) |
| D4 | What completes a lesson: attendance, a saved note (the app's current rule), or video watched? (CL-3) |
| D6 | What does "exam result" mean for teachers and the Junior badge: best or last quiz percent, or certificate quiz requirements? (CL-6) |

---

## 11. Open questions and assumptions

| # | Question | Why it can't be answered from the source |
|---|---|---|
| Q1 | Which courses in production already have contract templates and video URLs? | Production data was deliberately not read |
| Q2 | Does App Store review require in-app account deletion when accounts are created by staff? | Apple policy interpretation; no sign-up exists (`routes/` has no register route) |
| Q3 | Is the `sales_enrollment` delete power intended? (AUTH-3) | Policy |
| Q4 | Will announcement volume ever need queued delivery? (PUSH-3) | Product scale |

**Assumption:** the `action_required` CI state is GitHub's approval gate for fork PRs, not a
repository setting.

---

## 12. Definition of done

- **P0:**
  - PR #4 merged and deployed;
  - `FCM_CREDENTIALS` set;
  - one owner-run test announcement received on an Android device;
  - the server log shows `reached>0`.
- **Each backend item:**
  - code and tests merged;
  - the matching `docs/*_api_v1.md` updated;
  - CI green (lint, tests, file length);
  - the mobile docs' gap label removed or updated in the same cycle.
- **Each Admin Panel item:** the page works against a local backend with seeded data, and no
  test step touches production.
- **Decisions:** D1–D6 answered in writing and copied into this document's §10 with the date.
- **This document:** updated whenever an item changes status, so it stays the single list.
