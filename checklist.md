# Subwise: Project Checklist

Tick items as you finish them: change `[ ]` to `[x]`.
"CRUD" in this project = **service layer + routers** for each module. Models and schemas are only the shape; nothing works until the services and routers exist.

## Open decisions (settle these early)
- [ ] Final product name (Subwise / Recurra / Renewly / other)
- [ ] AI provider and model
- [ ] File storage for uploads (local folder for dev, S3-compatible bucket for deploy)
- [ ] Email provider for reminders and password reset (or skip email, in-app only)
- [ ] Frontend framework (React / Next.js / other)
- [ ] Hosting (backend, database, frontend)
- [x] Accepted file types: CSV and receipts/PDF
- [x] AI role: analyst, with user-approved actions only

---

## DONE
- [x] PRD and feature list
- [x] Database design (28 tables)
- [x] SQLAlchemy models, Groups A to F
- [x] Seed script (plans, default categories)
- [x] Pydantic schemas (73 classes)
- [x] Schema usage checker and coverage test

---

## Phase 0: Foundation check (do this first)
- [ ] Project folder structure: `app/models`, `app/schemas`, `app/services`, `app/routers`, `app/core`, `tests`
- [ ] `.env` and `config.py` (database URL, JWT secret, AI key, PayPal keys)
- [ ] `.gitignore` (`.env`, `.venv`, `__pycache__`, uploads)
- [ ] Git repository created and first commit pushed
- [ ] PostgreSQL running (Docker Compose)
- [ ] All models import cleanly and `create_all()` succeeds
- [ ] Alembic set up, first migration generated and applied
- [ ] `seed.py` runs (Free and Plus plans exist)
- [ ] Consistent error format and global exception handler
- [ ] CORS configured for the frontend origin
- [ ] Logging set up

## Phase 1: Auth routes and security (Days 1-2)
- [ ] `core/security.py`: password hashing, JWT create/decode, hashed token helper
- [ ] `get_current_user` dependency
- [ ] `POST /auth/register` (lowercase email, create Free entitlement and notification preferences)
- [ ] `POST /auth/login` (failed-login counter, lockout via `locked_until`)
- [ ] `POST /auth/refresh` (rotate refresh token)
- [ ] `POST /auth/logout` (revoke refresh token)
- [ ] `POST /auth/forgot-password` (same response whether or not the email exists)
- [ ] `POST /auth/reset-password` (token expiry, single use)
- [ ] `POST /auth/change-password`
- [ ] `GET` and `PATCH /auth/me`
- [ ] `DELETE /auth/me` (wipes all user data)
- [ ] Login rate limiting
- [ ] Tests: register, login, wrong password, lockout, refresh, logout, reset

## Phase 2: Subscription management CRUD (Days 3-4)
- [ ] Categories service and router (list, create, update; defaults are read-only)
- [ ] Tags service and router (list, create, delete)
- [ ] Subscription service: create (plus first `price_history` row)
- [ ] Subscription service: update (amount change writes a new `price_history` row in the same transaction)
- [ ] Subscription service: archive instead of hard delete
- [ ] Plan limit check (Free = max subscriptions) with clear 403 message
- [ ] Duplicate detection (409 with `DuplicateWarningOut`, then `acknowledge_duplicate`)
- [ ] Ownership checks on category and tag IDs (they must belong to the same user)
- [ ] Trial rules (end date required, trial-ending data available)
- [ ] `POST /subscriptions`, `GET /subscriptions` (search, filter, sort, pagination), `GET /{id}`, `PUT /{id}`, `DELETE /{id}`
- [ ] `PATCH /subscriptions/{id}/status` and `POST /subscriptions/bulk`
- [ ] `GET /subscriptions/{id}/price-history`
- [ ] Payments: `POST` and `GET /subscriptions/{id}/payments`
- [ ] Audit log row on every create, update, archive
- [ ] Tests: data isolation (User A cannot see User B's data, returns 404)
- [ ] Tests: price change creates history, unchanged price does not
- [ ] Tests: Free plan limit, trial without end date rejected

## Phase 3: Import system (Days 5-6)
- [ ] File upload endpoint with validation (type, size limit, extension, content sniffing)
- [ ] File storage service (save and read, never trust the original filename)
- [ ] CSV parser (encoding, delimiters, bad rows)
- [ ] Saved column mappings: `GET` and `POST /imports/mappings`
- [ ] Recurring-pattern detection (same merchant, similar amount, regular gaps)
- [ ] PII redaction before anything is sent to the AI
- [ ] AI extraction for receipts and PDF invoices (text PDFs and images)
- [ ] Validate AI output with `AIExtractionResult` (never trust raw model JSON)
- [ ] Per-field confidence stored on import items
- [ ] Duplicate matching against existing subscriptions
- [ ] Paste-an-email import: `POST /imports/email`
- [ ] `GET /imports/{id}`, `GET /imports/{id}/items`
- [ ] `POST /imports/{id}/confirm` (only confirmed items become subscriptions, price history created too)
- [ ] `POST /imports/{id}/undo`
- [ ] Failed and timeout handling (job status `failed`, error message)
- [ ] Tests: AI output never creates subscriptions without confirmation
- [ ] Tests: malformed CSV, oversized file, wrong file type

## Phase 4: Financial intelligence (Days 7-8)
- [ ] Monthly-equivalent calculation (weekly, yearly, every N months, shared percent)
- [ ] Totals per currency (never add different currencies together)
- [ ] `GET /analytics/overview` (totals, by category, active count, upcoming renewals)
- [ ] Next-renewal-date roll-forward logic
- [ ] `GET /analytics/forecast`
- [ ] `GET /analytics/price-changes` (percent and yearly impact)
- [ ] Renewal calendar and iCal export
- [ ] Budgets: `GET`, `POST`, `PATCH /budgets` and `GET /budgets/status`
- [ ] Savings tracker: `GET` and `POST /savings` (user-confirmed only)
- [ ] Health Score calculation and `GET /analytics/health-score`
- [ ] Zombie detector and overlap finder (generate `ai_insights`)
- [ ] "What if I cancel?" simulator
- [ ] Insights: `GET /ai/insights`, `POST /ai/insights/{id}/dismiss`
- [ ] Tests for every calculation with hand-checked numbers (weekly, yearly, multi-currency, shared, paused)

## Phase 5: AI analyst (Days 7-8)
- [ ] AI client wrapper (timeouts, retries, error handling, no secrets in logs)
- [ ] Context builder (sends only the user's subscription facts, minimum personal data)
- [ ] `POST /ai/ask` grounded in saved records, with citations
- [ ] Refuses to answer when there is no data, never invents subscriptions
- [ ] Conversation history: `GET /ai/conversations`, `GET /ai/conversations/{id}`
- [ ] Proposed actions: validate with `ProposedActionCreate`, store as `pending`
- [ ] `GET /ai/actions`, `POST /ai/actions/{id}/decision` (apply change only on approve, write audit log)
- [ ] Prompt-injection defences (treat imported text and notes as data, never as instructions)
- [ ] Monthly report: `GET /ai/reports`, `POST /ai/reports/monthly`
- [ ] Subscription Wrapped
- [ ] Cancellation message drafter
- [ ] Label any AI price or alternative suggestion as "verify this"
- [ ] Tests: answers match database numbers, injected text cannot trigger actions

## Phase 6: Notifications (around Days 8-9)
- [ ] Preferences: `GET` and `PATCH /notifications/preferences`
- [ ] Scheduler job (renewals, trial ending, price increase, budget warning, weekly digest)
- [ ] Dedupe using `dedupe_key` so reruns never duplicate alerts
- [ ] `GET /notifications` and `PATCH /notifications/{id}/read`
- [ ] Email sending (if included) with a sandbox or test mode
- [ ] Tests: scheduler run twice produces one alert

## Phase 7: PayPal (Days 9-10)
- [ ] PayPal Sandbox developer account, business and buyer test accounts
- [ ] Access-token fetch and caching
- [ ] `GET /plans`
- [ ] `POST /payments/paypal/create-order` (server sets the price, idempotency key)
- [ ] `POST /payments/paypal/capture-order` (verify amount, currency and status with PayPal)
- [ ] Activate entitlement on successful capture
- [ ] `POST /payments/paypal/webhook` (raw body, verify signature, store `event_id`, ignore repeats)
- [ ] Handle refund and failed payment (revoke entitlement)
- [ ] `GET /payments/orders` and `GET /payments/entitlement`
- [ ] Plan gating on subscription limit, AI chat and imports per month
- [ ] Expired-plan handling
- [ ] Tests: double capture, duplicate webhook, refund revokes plan, tampered amount rejected

## Phase 8: Frontend (Days 11-12)
- [ ] Project setup, API client, auth token handling, route guards
- [ ] Register, login, forgot password pages
- [ ] Dashboard (totals per currency, renewals, category chart, health score)
- [ ] My Subscriptions (list, search, filters, add, edit, archive, bulk actions)
- [ ] Import page (upload, review table with low-confidence highlighting, confirm)
- [ ] Intelligence centre (price history, forecast, insights, budgets, savings)
- [ ] AI assistant page (chat, suggested questions, citations, approve/reject actions)
- [ ] Notifications and settings page
- [ ] Upgrade page and PayPal checkout buttons
- [ ] Loading, empty and error states on every page
- [ ] Mobile-responsive layout and dark mode

## Phase 9: Quality and security pass
- [ ] Every query filtered by `user_id` (review all services once more)
- [ ] No secrets in the repo or logs
- [ ] File upload limits and validation confirmed
- [ ] Rate limits on login, AI ask and upload
- [ ] Schema checker passes (`python check_schema_usage.py`)
- [ ] All acceptance criteria from the PRD pass
- [ ] Demo mode: seeded sample account with realistic data

## Phase 10: Submission (Day 13)
- [ ] Deployed backend and frontend, environment variables set
- [ ] Production database migrated and seeded
- [ ] PayPal Sandbox works on the deployed URL (webhook URL updated)
- [ ] README (what it is, setup, env variables, architecture, demo login)
- [ ] Architecture and database diagram
- [ ] Demo video (problem, import, dashboard, AI chat, PayPal payment)
- [ ] Final end-to-end test on the deployed app
- [ ] Submission form completed

---

## Progress log
| Date | What I finished | Blockers |
| --- | --- | --- |
|  |  |  |