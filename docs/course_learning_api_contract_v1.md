# Course Learning API Contract V1 (backend proposal)

**Status:** **Implemented** (2026-09-29). Answers the 28 questions in the Flutter team's
*Course Learning Frontend → Backend Requirements V1*. Every endpoint below is live; the §4
open product decisions were implemented as proposed. The full mobile endpoint index,
including the staff/teacher side and additions beyond this document, is
`docs/mobile_api_v1.md`.

**Scope:** the student-facing learning surface only (module list, lesson, progress,
materials, note, assignment, quiz, certificate). Authoring (staff creating modules,
quizzes, grading) is a separate back-office contract.

---

## 0. Conventions (apply to every endpoint)

These are the rules the existing API already follows; the learning endpoints keep them.

| Topic | Rule |
|---|---|
| Auth | `Authorization: Bearer <access_token>` from `POST /auth/login`. Every endpoint here requires a **student** token (`actor_type = "student"`). |
| Enrolment | The student must hold an **active enrollment** in a cohort of the course. Otherwise `403 not_enrolled`. |
| Foreign ids | An id that exists but belongs to another course/student answers **404**, not 403 — the API does not confirm the existence of other people's data. |
| Ids | Integers. Every object the app can act on carries one. |
| Localised text | `{"mn": "...", "en": "..."}` objects (as on `GET /courses`). `en` may be `null`. |
| Timestamps | ISO-8601 **with offset**, UTC: `"2026-08-06T01:00:00+00:00"`. The client formats "Today, 14:20" / "Just now". |
| Dates | Bare ISO date: `"2026-08-06"`. Times of day: `"HH:MM"` in Asia/Ulaanbaatar. |
| Durations / sizes | Integers: `duration_seconds`, `size_bytes`. No pre-formatted labels. |
| Errors | `{"error": "<code>", ...extra}` with the HTTP status below. Codes are stable; the app branches on `error`, never on text. A human sentence, when the backend has one, is in `detail.message`. |

**Error statuses used here**

| Status | Meaning | Codes |
|---|---|---|
| 400 | Bad input | endpoint-specific (`content_required`, `invalid_option`, …) |
| 401 | No/expired/invalid token | `authentication_required`, `token_expired`, `invalid_token`, `account_inactive` |
| 403 | Wrong actor or not enrolled | `forbidden`, `not_enrolled` |
| 404 | Not found (or not yours) | `course_not_found`, `lesson_not_found`, `quiz_not_found`, … |
| 409 | State conflict | `lesson_locked`, `attempt_finished`, `already_answered`, `no_attempts_left` |
| 413 | Upload too large | `file_too_large` |
| 502/503 | Storage/upstream failure | `storage_error` (503 = retry may succeed) |

This is the failure model the Flutter repository needs (Step 0 of the integration order):
map `401` → re-auth, `403 not_enrolled` → "not enrolled" screen, `404` → "not found",
`409` → refresh the screen state, `5xx` → retryable error.

---

## 1. Data model (what the backend will store)

Names follow the finalized ERD (`master db erd.sql`); **bold** = addition to the ERD.

| Concept (Flutter) | Table | Notes |
|---|---|---|
| Module | `course_topics` | `course_id`, `name_mn/en`, `sort_order` |
| Lesson / Exercise | `course_lessons` | `topic_id`, `name_mn/en`, `type`, `classroom_embed_url`, `duration_min`→**`duration_seconds`**, `sort_order`, **`summary_mn/en`**, **`sections` (JSON)** |
| Material | `lesson_materials` | `lesson_id`, `cohort_id` (null = all cohorts), `title`, `type`, `url`, **`file_key`, `file_name`, `content_type`, `size_bytes`** |
| Progress | `lesson_progress` | `enrollment_id`, `lesson_id`, `completed`, `watched_at` |
| Note | **`lesson_notes`** (new) | `student_id`, `lesson_id`, `content`, `created_at`, `updated_at`; unique (`student_id`, `lesson_id`) |
| Assignment | `assignments` | `cohort_id`, `lesson_id`, `title`, `description`, `due_date`, `max_score`, **`attachment_material_id`** |
| Submission | `assignment_submissions` | one row **per submission** (history kept — business rule: homework is archived, never overwritten) + **`file_id`** |
| Mentor feedback | `assignment_submissions.feedback` + `graded_by_teacher_id`, `graded_at` | one feedback per submission |
| Quiz | `exams` | `course_id`, `topic_id`, **`lesson_id`**, `name_mn/en`, `pass_point`, `max_attempts` (null = unlimited) |
| Question / option | `exam_questions` (+ **`explanation`**) / `exam_answers` | options ordered by `sort_order`; `is_correct` never leaves the server before the question is answered |
| Attempt | `student_exams` / `student_exam_answers` | one row per attempt |
| Uploaded file | **`student_files`** (new) | S3 key, name, type, size, owner |
| Certificate | `certificates` | `cert_number`, `file_url`, `verify_url`, `payment_cleared`, `issued_at` |

**Hierarchy (Q2):** Course 1:N Module 1:N Lesson. A lesson has 0..N materials, 0..1 assignment
(per cohort), 0..1 quiz, 0..1 note per student.

---

## 2. Endpoints

### 2.1 Learning path — module list, progress, continue, certificate state

`GET /me/courses/{course_slug}/learning`

Answers Q1, Q4–Q6, Q8 and feeds the certification section in one call — the module list screen
needs all of it at once.

```json
{
  "course": {
    "id": 7, "slug": "corporate-leaders",
    "title": {"mn": "Corporate Leaders AI", "en": "Corporate Leaders AI"},
    "description": {"mn": "...", "en": "..."},
    "banner_image_url": "https://..."
  },
  "enrollment_id": 118,
  "cohort_id": 12,
  "progress": {"percent": 30, "completed_lessons": 6, "total_lessons": 20},
  "continue": {"module_id": 31, "lesson_id": 204},
  "certificate": {"status": "not_eligible"},
  "modules": [
    {
      "id": 30, "order": 1,
      "title": {"mn": "AI хэрхэн ажилладаг вэ", "en": "How AI works"},
      "schedule": {"date": "2026-08-06", "start_time": "09:00"},
      "lesson_count": 4, "completed_lessons": 4,
      "completed": true, "locked": false
    }
  ]
}
```

- `description` is a localised **object**, same as `GET /courses/{slug}` (reconciles the
  `Object?` vs `String` mismatch the Flutter doc raises).
- **Q4 icon / accent colour:** the backend sends **no icon, image or colour**. The client maps
  `order` onto its bundled icon/accent palette. `illustrationAsset` stays client-side;
  `banner_image_url` is there if the design ever wants the real course image.
- `schedule` — raw fields (Q "scheduleLabel"): the date and start time of the module's first
  class session; the client formats `"08/04 • Да • 09:00"` (weekday from `date`). `null` when
  the module has no scheduled session (e.g. self-paced).
- **Q5 percent:** **server-computed**, `floor(completed_lessons / total_lessons × 100)`. The client
  displays it and never derives it. (The Figma "30% vs 2-of-5 modules" discrepancy disappears:
  the percentage is lesson-based, not module-based.)
- **Q6 completed / locked:** **server-sent**; the client must not derive them.
  - `completed` = every lesson in the module is completed.
  - `locked` = the module's `schedule.date` is still in the future (recordings open after the
    live class). A module with no schedule is never locked. *Product may change the rule; the
    field and its meaning for the client stay the same.*
- **Q8 continue:** **server-selected**. First lesson (by module order, then lesson order) that is
  unlocked and not completed; if all are completed, the last lesson; `null` if nothing is
  unlocked. Replaces `_continueLearningTarget()`.
- `certificate` — summary only; details in §2.9.

Errors: `404 course_not_found`, `403 not_enrolled`.

### 2.2 Lessons in a module

`GET /me/modules/{module_id}/lessons`

```json
{
  "module": {"id": 31, "order": 2, "title": {"mn": "...", "en": "..."}},
  "lessons": [
    {"id": 204, "order": 1, "title": {"mn": "Nesting loops", "en": "Nesting loops"},
     "type": "recording", "duration_seconds": 1455, "completed": false, "locked": false}
  ]
}
```

- `type`: `"recording"` (live-class recording) \| `"video"` \| `"reading"`. The client maps it
  to a badge ("Live Classroom Recording"); the server sends no badge text.
- A lesson's `locked` follows its module's.

Errors: `404 module_not_found`, `403 not_enrolled`.

### 2.3 Lesson detail (the Exercise Detail screen)

`GET /me/lessons/{lesson_id}`

**Q3: yes — re-key `getExercise` from `moduleId` to `lessonId`.** Exercise content is per lesson.

```json
{
  "id": 204,
  "module": {"id": 31, "order": 2, "title": {"mn": "...", "en": "..."}},
  "order": 1,
  "title": {"mn": "Nesting loops", "en": "Nesting loops"},
  "type": "recording",
  "duration_seconds": 1455,
  "video": {"embed_url": "https://www.youtube.com/embed/..."},
  "summary": {"mn": "...", "en": "..."},
  "sections": [
    {"title": {"mn": "...", "en": "..."}, "body": {"mn": "...", "en": "..."},
     "bullets": [{"mn": "...", "en": "..."}]}
  ],
  "completed": false,
  "materials": [ /* §2.4 material objects */ ],
  "note": null,                /* §2.5 note object or null */
  "assignment": null,          /* §2.6 assignment object or null */
  "quiz": null                 /* §2.7 quiz summary or null */
}
```

- `moduleCaption` ("Modules 2") is built client-side from `module.order`.
- `video` — `null` when the lesson has no recording. `embed_url` is a web embed (YouTube /
  Google Classroom); playing it needs a WebView or player on the client — new client work.
- `sections` keep the structure the UI already renders (title + body + bullets), not HTML.

Errors: `404 lesson_not_found`, `403 not_enrolled`, `409 lesson_locked` (module still locked).

**Mark complete (Q7)** — `POST /me/lessons/{lesson_id}/complete` → `{"completed": true, "progress": {…§2.1 progress…}}`.
Idempotent. The app does not need it yet (it has no "done" control), but progress must be
writable by someone; this is the student-side path for when the video player lands. Live-class
attendance can also complete a lesson server-side.

### 2.4 Materials (Q14, Q15)

Materials are **per lesson**, optionally narrowed to one cohort. Delivered inside the lesson
detail (`materials[]`):

```json
{"id": 88, "title": "Course material 1", "type": "file",
 "file_name": "week2-slides.pdf", "content_type": "application/pdf", "size_bytes": 10485760}
```

- `type`: `"file"` (stored on S3) \| `"link"` (external URL — then `url` is included and there is
  nothing to download).
- `content_type` replaces the hardcoded `", PDF"`; `size_bytes` replaces `sizeLabel`.

**Download:** `GET /me/materials/{material_id}/download` →
`{"url": "https://s3…signed…", "expires_at": "…", "file_name": "…", "size_bytes": 10485760}`.
The URL is a **pre-signed S3 GET, valid 5 minutes**, with no auth header needed — the client
downloads it directly and gets real byte progress. Request a new one if it expires.

The **assignment attachment** is the same material object, so both widgets share one model and
one download path.

Errors: `404 material_not_found`, `403 not_enrolled`, `503 storage_error`.

### 2.5 Student note (Q16, Q17)

**One note per student per lesson.** Delivered inside the lesson detail as `note` (or `null`):

```json
{"id": 51, "content": "…", "created_at": "…", "updated_at": "…",
 "author": {"name": "Болд Батаа", "initials": "ББ"}}
```

- `author` comes from the signed-in student's profile — replaces the hardcoded `"БП"` /
  `"Болд Батаа"`. (Also available from `GET /auth/me`.)

**Create or update:** `PUT /me/lessons/{lesson_id}/note` with `{"content": "…"}` → the note object
(`201` on first save, `200` on update). Same call for both, so the app needs no separate "create" path.
`content` is trimmed; empty → `400 content_required`; over 5000 characters → `400 content_too_long`.
There is no delete (the UI has none).

### 2.6 Assignment, submission, mentor feedback (Q9–Q12, Q18, Q19)

Delivered inside the lesson detail as `assignment` (or `null`), also at
`GET /me/assignments/{assignment_id}`:

```json
{
  "id": 17,
  "title": {"mn": "…", "en": "…"},
  "instructions": {"mn": "…", "en": "…"},
  "due_date": "2026-08-20",
  "max_score": 100,
  "attachment": null,                  /* §2.4 material object or null */
  "submission": {
    "id": 301, "version": 2, "status": "reviewed",
    "link": "https://github.com/…", "description": "…",
    "file": null,                      /* §2.8 file object or null */
    "submitted_at": "…",
    "score": 85,
    "feedback": {
      "message": "…", "created_at": "…",
      "mentor": {"id": 4, "name": "Дорж Бат", "initials": "ДБ", "role": "teacher"}
    }
  }
}
```

- **Q9:** assignments carry `title`, `instructions`, `due_date`, `max_score`. The UI shows none
  of these today — new UI work if the design wants them. Any may be `null`.
- **Q10 submit:** `POST /me/assignments/{assignment_id}/submissions` with
  `{"link": "…", "description": "…", "file_id": null}`.
  At least one of `link` or `file_id` is required (`400 submission_empty`); `link` must be
  `http(s)` (`400 invalid_link`); `description` optional, ≤ 5000 chars. Returns the
  `submission` object, `201`.
- **Q11 resubmission:** the **same call**. Each submission is a new version (`version` +1);
  history is kept, the response and `assignment.submission` always show the latest. Allowed until
  `due_date` passes (`409 past_due`); if `due_date` is `null`, always allowed.
- **Q12 statuses:** `submitted` (waiting for the mentor) → `reviewed` (feedback/score present).
  Mapping onto the app: no `submission` → `notSubmitted`; any `submission` → `submitted` (success
  card). `pendingReview` stays a client-only "request in flight" state.
- **Q18/Q19 feedback:** tied to **one submission**, written by the teacher who reviewed it.
  `null` until reviewed. **No avatar image** — `initials` are sent ready to render. `role` is the
  enum `"teacher"`; the client picks the label ("Lead Mentor"). Feedback on an earlier version stays
  with that version; the app shows the latest submission's feedback.

Errors: `404 assignment_not_found`, `403 not_enrolled`, `409 past_due`, `400` codes above.

### 2.7 Quiz — attempts and secure grading (Q20–Q24)

**The answer key never reaches the client before a question is answered.**

**Summary** (inside the lesson detail as `quiz`, or `null`):

```json
{
  "id": 9,
  "title": {"mn": "…", "en": "…"},
  "question_count": 5,
  "pass_percent": 70,
  "attempts_used": 1,
  "attempts_left": null,
  "open_attempt_id": null,
  "last_result": {"attempt_id": 40, "correct": 4, "total": 5, "percent": 80, "passed": true,
                  "finished_at": "…"}
}
```

- **Q23 retry:** `attempts_left` is `null` when unlimited, else a count; `0` → hide "Дахин quiz өгөх".
- **Q24 persistence:** `last_result` is the most recent finished attempt — the preview card shows it
  on load; nothing is lost when the screen is disposed.
- `resultTitle` is not sent; the result-screen caption is a client string.

**Start (or resume) — Q21:** `POST /me/quizzes/{quiz_id}/attempts` →

```json
{
  "attempt_id": 41, "started_at": "…",
  "questions": [
    {"id": 101, "order": 1, "prompt": "…",
     "options": [{"id": 501, "text": "…"}, {"id": 502, "text": "…"}],
     "answer": null}
  ]
}
```

- Options are **ordered** (the client keeps deriving A/B/C/D from position) and carry ids.
- If the student already has an unfinished attempt, this **returns that attempt** (`200`, answered
  questions include their `answer`) — resume, not a second attempt. A new attempt is `201`.
- No time limit in v1 (no expiry). `409 no_attempts_left` when the limit is reached.

**Answer one question — Q20, Q22 (per answer):**
`POST /me/quiz-attempts/{attempt_id}/answers` with `{"question_id": 101, "option_id": 502}` →

```json
{"question_id": 101, "option_id": 502, "correct": false,
 "correct_option_id": 501, "explanation": "…"}
```

- This is how the app gets **immediate inline feedback without holding the key**: correctness,
  the right option and the explanation are revealed only for a question the student has just
  answered, and the answer is then final.
- `409 already_answered`, `409 attempt_finished`, `400 invalid_option` (option not in that question).

**Finish:** `POST /me/quiz-attempts/{attempt_id}/finish` →

```json
{"attempt_id": 41, "correct": 4, "total": 5, "percent": 80, "passed": true,
 "questions": [{"question_id": 101, "order": 1, "correct": false}]}
```

- Unanswered questions count as wrong. `percent` is weighted by each question's `point`
  (default 1); `correct`/`total` count questions. Also readable later at
  `GET /me/quiz-attempts/{attempt_id}`. The result list needs only correctness per question —
  matches the UI's generic "Асуулт" rows.
- **Server-graded:** `quizScore()` and `QuizQuestion.correctOptionIndex` go away.

Errors: `404 quiz_not_found` / `attempt_not_found`, `403 not_enrolled`, `409` codes above.

### 2.8 Student file upload (Q13)

`POST /me/files` — `multipart/form-data`, field `file` →
`{"id": 77, "file_name": "report.pdf", "content_type": "application/pdf", "size_bytes": 482133}` (`201`).

- Accepted: `pdf, doc, docx, ppt, pptx, xls, xlsx, zip, png, jpg, jpeg`; max **20 MB**
  (`400 unsupported_file_type`, `413 file_too_large`).
- Attach by sending the returned `id` as `file_id` in the submission (§2.6). A file can be
  attached only by its owner; unattached files are cleaned up after 24 h.
- Stored privately on S3 (the same bucket as course templates, under `students/`); read back
  through a pre-signed URL like materials.

### 2.9 Certificate (Q25, Q26)

`GET /me/courses/{course_slug}/certificate` →

```json
{
  "status": "not_eligible",
  "requirements": {
    "lessons_completed": {"done": false, "percent": 30},
    "quizzes_passed": {"done": false, "passed": 1, "required": 3},
    "payment_cleared": {"done": true}
  },
  "certificate": null
}
```

- `status`: `not_eligible` \| `eligible` (requirements met, being issued) \| `issued`.
- When `issued`: `"certificate": {"cert_number": "AIAA-2026-00123", "issued_at": "…", "verify_url": "https://…"}`.
- **Download:** `GET /me/certificates/{cert_number}/download` → `{"url", "expires_at"}` (pre-signed, like §2.4).
- **Q26 eligibility (proposal, needs product sign-off):** every lesson completed, every required
  quiz passed (`pass_percent`), and the course balance paid (`student_ledger.balance = 0` →
  `payment_cleared`). Attendance or a final project can be added as further `requirements`
  entries without changing the shape — the client renders the list it gets.
- These are **student** endpoints, unrelated to the admin `/courses/{id}/templates/cert`
  (the template is what the issued certificate is generated from).

---

## 3. Answers index

| # | Question | Answer |
|---|---|---|
| 1 | Module endpoint/shape; own progress/lock? | §2.1 — modules carry `completed`, `locked`, lesson counts |
| 2 | Lesson endpoint; hierarchy | §2.2; Course 1:N Module 1:N Lesson |
| 3 | Re-key exercise to lesson? | **Yes** — `GET /me/lessons/{lesson_id}` |
| 4 | Icon/colour key or image URL? | Neither; client maps `order` to its palette |
| 5 | Percent: server or formula? | Server-computed, lesson-based; client displays only |
| 6 | completed/locked server or client? | Server-sent |
| 7 | Does the app report progress? | Optional `POST /me/lessons/{id}/complete`; not needed yet |
| 8 | Continue Learning | Server-selected `continue` |
| 9 | Assignment metadata | title, instructions, due_date, max_score (all nullable) |
| 10 | Submission payload | `link`, `description`, `file_id`; link or file required |
| 11 | Resubmission | Same call; new version, history kept |
| 12 | Statuses → app states | `submitted`/`reviewed` → app `submitted`; none → `notSubmitted` |
| 13 | File upload | `POST /me/files` then `file_id`; 20 MB; types in §2.8 |
| 14 | Material scope | Per lesson, optionally per cohort |
| 15 | Download mechanism | Pre-signed S3 URL via `/download`; bytes + content type sent |
| 16 | Note identity/timestamps | `id`, `created_at`, `updated_at`, `author` |
| 17 | One or many notes? | One per student per lesson; `PUT` upserts |
| 18 | Feedback shape; avatar? | §2.6; initials, no image |
| 19 | Feedback tied to? | One submission |
| 20 | Secure grading | Per-answer round trip reveals key only after answering |
| 21 | Attempts modelled? | Yes — id, start, resume; no expiry in v1 |
| 22 | Per-answer or batched? | Per-answer, then `finish` |
| 23 | Retry / limit | `attempts_left` (`null` = unlimited) |
| 24 | Last score on load | `quiz.last_result` |
| 25 | Student certificate endpoints | §2.9 |
| 26 | Eligibility | Lessons + quizzes + payment (product to confirm) |
| 27 | Auth / scopes | Student token + active enrolment; others' ids → 404 |
| 28 | Error contract | §0 |

## 4. Open product decisions (not backend-blocking the shape)

1. **Lock rule** (§2.1) — "locked until the class date" is the proposal.
2. **Certificate eligibility** (§2.9) — which requirements apply per course.
3. **Resubmission cut-off** (§2.6) — `due_date` proposed; product may prefer "until reviewed".
4. **Quiz placement** — per lesson (proposed, matches the UI) vs. per module (ERD `topic_id`); the
   API shape is the same either way.

## 5. Suggested backend delivery order

Mirrors the Flutter integration order so each app step has its endpoint ready:

1. Tables + authoring seed: `course_topics`, `course_lessons`, `lesson_progress` → §2.1–2.3.
2. Materials + download (§2.4).
3. Notes (§2.5).
4. Assignments + submissions + feedback (§2.6), then uploads (§2.8).
5. Quiz attempts (§2.7).
6. Certificates (§2.9) — after progress and quizzes exist.

Staff-side authoring and grading endpoints ship alongside each step (separate contract).
