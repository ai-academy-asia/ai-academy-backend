# Teacher schedule-change (class handover) API — v1

Answers `teacher_schedule_change_backend_spec.md` (mobile PR #373). Implemented and
covered by `tests/test_schedule_change_*.py`. All endpoints need a **teacher** token;
staff and student tokens get `403 forbidden`, no token `401`.

## 1. Decisions (spec §3)

| # | Question | v1 answer |
|---|---|---|
| 1 | Assignment model | The accepted request **is** the covering assignment (`schedule_change_requests.status = 'accepted'`). No column on `class_sessions` changes; `cohorts.teacher_id` stays the original teacher. |
| 2 | Eligible recipients | Every other teacher whose login is active and who is **not teaching or covering another session that overlaps** this one. No program/cohort restriction. |
| 3 | Overlap | Blocked at send (`409 recipient_busy`) and re-checked at accept (`409 schedule_conflict`). Back-to-back (11:00 end / 11:00 start) is not a clash. A session without `end_time` counts as 60 minutes. |
| 4 | Duplicates | One `pending` request per session (DB unique index). Re-sending the identical request (same recipient + message) returns the existing one with `200` — no second row or notification. A different recipient while pending → `409 request_pending`. |
| 5 | Concurrency | Decisions lock the request row (`SELECT … FOR UPDATE`); acceptance also locks the recipient's teacher row. At most one `accepted` request per session (DB unique index). |
| 6 | Visibility | Schedule entry only. The covering teacher does **not** get attendance/QR/roster access to that cohort in v1 (attendance unchanged, per spec). |
| 7 | Notifications | In-app, and pushed through FCM when `FCM_CREDENTIALS` is set (issue #2, `mobile_api_v1.md` §9). See §5. |
| 8 | Authorization | Only the cohort's own teacher can send for a session and cancel; only the recipient can accept/reject. Anyone else gets `404` (the API does not confirm other people's requests exist); the other party gets `403 not_recipient` / `not_sender`. |
| 9 | Cancel / expiry | Sender may cancel a pending request. A pending request becomes `expired` once the session's local start (Asia/Ulaanbaatar) has come; it is settled lazily when either party reads or acts on it, and actions then answer `409 session_started`. |
| 10 | Audit | `created_at`, `updated_at`, `resolved_at`, `resolved_by_teacher_id` (recipient for accept/reject, sender for cancel, `null` for expiry) + an info log line per create/resolve. |

Session edited after sending: the request stays; acceptance re-checks clashes at the new
time. Session deleted: its requests are deleted with it (`ON DELETE CASCADE`).

## 2. Statuses

`pending` → `accepted` | `rejected` | `cancelled` | `expired`. The last four are terminal.
Repeating the decision a request already has returns it unchanged (`200`); any other
action on a resolved request is `409 request_already_resolved` with `current_status`.

## 3. Request object

```json
{
  "id": 12,
  "session_id": 345,
  "session": {
    "id": 345, "cohort_id": 7, "cohort_name": "CL-2026-10",
    "title": "Corporate Leaders", "topic_id": null, "topic": null,
    "date": "2026-10-06", "start_time": "09:00", "end_time": "11:00", "room": "Room 204"
  },
  "sender":    {"id": 3, "name": "Anar Bat", "photo_url": null},
  "recipient": {"id": 5, "name": "Bold",     "photo_url": null},
  "status": "accepted",
  "message": "Өвчтэй байна",
  "reason": null,
  "created_at": "2026-10-01T01:00:00+00:00",
  "updated_at": "2026-10-01T02:00:00+00:00",
  "resolved_at": "2026-10-01T02:00:00+00:00",
  "resolved_by_teacher_id": 5,
  "session_assignment": {"session_id": 345, "teacher_id": 5, "assignment_type": "covering"}
}
```

`session_assignment` is `null` unless `status` is `accepted`. `photo_url` is always `null`
for now (teachers have no photo). No student data is ever included. `message` / `reason`
are optional, trimmed, ≤ 500 characters.

## 4. Endpoints

| Method | Path | Who | Success |
|---|---|---|---|
| GET | `/teacher/sessions/{id}/eligible-teachers` | cohort's teacher | `{session_id, items: [{id, name, photo_url}]}` (not paged — all active teachers) |
| POST | `/teacher/schedule-change-requests` | cohort's teacher | `201` request (`200` for an identical retry) |
| GET | `/teacher/schedule-change-requests?direction=sent\|received&status=&limit=&before_id=` | own | `{direction, items: [request]}`, newest first, `limit` default 50 (max 100), page with `before_id` = last id |
| GET | `/teacher/schedule-change-requests/{id}` | sender, recipient | request (current status — use it, not the notification payload) |
| POST | `/teacher/schedule-change-requests/{id}/accept` | recipient | request |
| POST | `/teacher/schedule-change-requests/{id}/reject` | recipient | request; body `{"reason": "…"}` optional |
| POST | `/teacher/schedule-change-requests/{id}/cancel` | sender | request |
| GET | `/teacher/sessions?from=YYYY-MM-DD&to=YYYY-MM-DD` | teacher | `{from, to, items: [schedule entry]}` |

Create body: `{"session_id": 345, "recipient_teacher_id": 5, "message": null}`. The sender is
always the token's teacher.

### Errors (`{"error": code, …extra}`)

| HTTP | code | when |
|---|---|---|
| 400 | `session_id_required`, `recipient_required`, `cannot_request_self`, `invalid_message`, `message_too_long`, `invalid_reason`, `reason_too_long`, `invalid_direction`, `invalid_status`, `invalid_before_id`, `invalid_limit`, `from_and_to_required`, `invalid_date` | input |
| 403 | `forbidden` | not a teacher token |
| 403 | `not_recipient` / `not_sender` | the other party tried this action |
| 404 | `session_not_found` | unknown session, or not the caller's cohort |
| 404 | `recipient_not_found` | unknown or deactivated teacher |
| 404 | `request_not_found` | unknown, or the caller is not a party |
| 409 | `request_pending` (+`request_id`) | another pending request for the session |
| 409 | `session_already_covered` (+`request_id`) | session already has an accepted cover |
| 409 | `recipient_busy` | recipient teaches at that time (send) |
| 409 | `schedule_conflict` (+`session_ids`) | recipient teaches at that time (accept) |
| 409 | `session_started` | session's start time has passed |
| 409 | `request_already_resolved` (+`current_status`) | decision on a resolved request |

## 5. Notifications (in-app, `GET /me/notifications`)

| kind | to | data |
|---|---|---|
| `schedule_change_request` | recipient, on create | `{"request_id", "session_id"}` |
| `schedule_change_response` | sender, on accept / reject | `{"request_id", "session_id", "status"}` |

Titles/bodies are Mongolian text built by the server. The notification is committed in the
same transaction as the request. Cancel and expiry send nothing; opening a stale
notification should fetch `GET …/{request_id}` and show the current status without the
accept/reject buttons when it is no longer `pending`.

## 6. Schedule

`GET /teacher/sessions` returns each session as the `session` object above plus:

| field | regular (own cohort) | covering (accepted handover) |
|---|---|---|
| `assignment_type` | `"regular"` | `"covering"` → render as **Орлон заах** |
| `request_id` | `null` | the accepted request |
| `original_teacher` | `null` | the cohort's teacher |
| `covered_by` | the covering teacher, or `null` | `null` |

The original teacher keeps the session (`regular`, with `covered_by` set). Sessions other
teachers cover never appear as the caller's `covering`. `GET /teachers/{id}/schedule`
(cohort-level) additionally returns `covering_sessions` in the same shape.
