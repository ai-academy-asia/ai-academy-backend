---
name: quality
description: Run the aiaa-backend quality gate on a change — house standards, lint, tests, refactor and code review — and report (or fix) what fails. Use when the user asks to "check standards", "lint", "refactor", "review", "шалга", "стандарт", "чанар", before committing/pushing, or after a feature lands. Args: optional `fix` (apply fixes; default is report-only) and an optional git range (default: uncommitted changes, else the last commit).
---

# Quality gate for aiaa-backend

Run the steps **in order**; each later step assumes the earlier ones pass. Default mode is
**report only** — change nothing unless the args contain `fix`. Talk to the user in Mongolian.

## 0. Scope

- Args may hold `fix` and/or a git range (`abc123..HEAD`, `HEAD~3..HEAD`).
- No range: use uncommitted changes (`git status --short`, `git diff HEAD`); if the tree is
  clean, use the last commit (`HEAD~1..HEAD`).
- List the changed files once (`git diff --name-only <range>`); steps 3–5 look only at these.
  Steps 1–2 always run on the whole repo because CI does.

## 1. Lint (CI gate)

```bash
.venv/bin/ruff check app tests scripts wsgi.py
```
- `fix` mode: `.venv/bin/ruff check app tests scripts wsgi.py --fix`, then re-run; fix what is
  left by hand. Config: `pyproject.toml` (line-length 100, py39 target — no `X | Y` at
  runtime without `from __future__ import annotations`, no `match`).
- Do **not** run `ruff format`: the code is hand-formatted on purpose (aligned comments).

## 2. File length (CI gate — every .py < 300 lines)

```bash
python3 scripts/check_file_length.py
```
Any file listed fails CI. `fix` mode: split it — a service module becomes a package whose
`__init__.py` re-exports only the public API with `__all__` (see `app/services/payments/`,
`app/services/enrolment/`); a test file splits by endpoint. Migrations are exempt.

## 3. Tests

```bash
docker compose --profile dev up -d db           # local Postgres :5433
.venv/bin/python -m pytest -q -p no:cacheprovider   # ~8 min; or pass the relevant test files
```
Run the test files for the changed areas first, then the full suite before a push. A failure
is reported with its output — never skip, xfail or loosen a test to get green.

## 4. House standards (read the changed code against this list)

**API conventions** (`docs/course_learning_api_contract_v1.md` §0):
- Routes stay thin; logic lives in `app/services/`, which raise `ServiceError(status, code, **extra)`.
  Errors render as `{"error": "<code>"}` — stable codes, never prose.
- Someone else's id → **404**, not 403. Access rules come from `app/services/access.py`
  (`enrollment_for_course`, `lesson_for_student`, `cohort_for_teacher`, `ensure_module_open`) —
  never re-implemented per endpoint.
- Ids/limits from a request go through `app/services/params.py` (`get_by_id`, `parse_limit`):
  a raw `db.session.get(Model, "abc")` or `int(limit)` is a 500.
- Timestamps via `app.timeutil.iso()` (with offset); dates bare; durations/sizes as integers;
  no pre-formatted display strings; localised text as `{"mn", "en"}`.
- Course/cohort status is `draft` / `open` / `closed` only.
- Every learning-content route passes `ensure_module_open` (a locked module must not leak
  through a material, quiz or assignment id).

**Money & security:**
- The server derives every amount; client figures are advisory. Settlement is idempotent;
  underpayments do not settle. Refund `amount` is the running total (retry-safe).
- Nothing secret in responses (quiz answer keys before answering, gateway `raw` /
  `provider_meta`, OTP codes). Codes/tokens stored only as hashes.
- No outbound call on a request path that would reveal account existence by timing.

**Structure:**
- Cross-area calls are direct lazy imports (`from app.services.x import f` inside the function)
  — no try/except fallbacks that duplicate another area's rule.
- New models + one reviewed migration: autogenerate also "detects" the partial unique indexes
  that exist only in migrations — strip every change to existing tables; check
  `flask db upgrade` → `downgrade` → `upgrade` on a scratch `*_test` DB.

**Tests:**
- Real Postgres via `tests/conftest.py`; outbound HTTP/SMTP blocked — stub at the source
  (`app.payments.get_provider`, `PosAPIClient`, `app.mail.send_message`, storage names).
- Shared fixtures live in `tests/<area>_helpers.py` and are **bound explicitly** in each
  module (`finance = payments_helpers.finance`) — never `pytest_plugins`.
- Each endpoint: happy path + 401 + 403/404 + its error codes + DB side effects.
- A bug found but not fixed → strict `xfail` asserting the correct behaviour.

**Docs & Postman** — a new or changed route must appear in:
- `docs/mobile_api_v1.md` if the mobile app calls it;
- `aiaa-api.postman_collection.json` in the folder of its caller (Auth, Public, Account,
  Student, Teacher, Admin/<permission>). `tests/test_postman_collection.py` enforces this in
  CI; to see the gaps directly:
  ```bash
  DATABASE_URL=postgresql+psycopg2://x@localhost/aiaa_test \
    .venv/bin/python scripts/check_postman.py
  ```

`fix` mode: fix each violation in the changed code. Report-only: list them.

## 5. Refactor

On the changed files only, look for: duplication across areas, functions with too many
branches (ruff `C901`/`PLR0912` as a hint: `.venv/bin/ruff check <files> --select C901,PLR0912
--exit-zero`), files near 300 lines, dead fallback code, comments that restate code.
- `fix` mode: invoke the `simplify` skill on the change, then re-run steps 1–3.
- Keep behaviour identical — a refactor that changes a response or an error code is a bug.

## 6. Review

Invoke the `code-review` skill on the scope from step 0 (pass the git range as its argument).
- `fix` mode: fix the confirmed findings, add a test per fix, re-run steps 1–3.
- Report-only: relay the findings.

## 7. Report (Mongolian, short)

| Алхам | Төлөв | Тэмдэглэл |
|---|---|---|
| Lint | ✅/❌ | … |
| Файлын урт | ✅/❌ | … |
| Тест | ✅/❌ | N passed / failed |
| Стандарт | ✅/⚠️ | зөрчил бүр `file:line` |
| Refactor | ✅/⚠️ | … |
| Review | ✅/⚠️ | олдсон асуудлууд, зэрэглэлээр |

Then: what was changed (fix mode) or what should be fixed (report mode). Never commit or push
from this skill — ask the user; a push to `main` deploys to production.
