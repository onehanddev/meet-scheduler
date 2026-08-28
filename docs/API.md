# API Reference

Base URL (dev): `http://127.0.0.1:8000`
Interactive docs: `http://127.0.0.1:8000/docs` (Swagger) and `/redoc`
Health: `GET /healthz → { status: "ok" }`

All error responses use the envelope:
```json
{ "code": "string", "message": "string", "details": [{"field":"...","message":"..."}] }
```
`details` is non-empty only for `422 validation_error` (Pydantic). Booking/conflict codes are top-level `code`.

---

## Authentication

### POST /auth/register
Register a host. No auth.
```json
// Request
{ "email": "alice@example.com", "password": "correct horse battery staple" }
```
- `email`: `EmailStr`, normalized `strip().lower()`, case-insensitive unique DB constraint.
- `password`: 8–128 chars, no character-class rules. Stored as Argon2id hash.
- `201` → safe profile:
```json
{ "id": "uuid", "email": "alice@example.com", "username": null, "display_name": null, "timezone": "Asia/Kolkata" }
```
- `409` duplicate email → envelope `code` varies (detail carries message). Generic message per PRD § Auth.

### POST /auth/login
```json
// Request
{ "email": "alice@example.com", "password": "…password…" }
```
- Unknown email or wrong password → `401 Invalid email or password` (same message).
- `200` →
```json
{ "access_token": "jwt", "refresh_token": "jwt", "token_type":"bearer", "expires_in":900 }
```
JWT claims: `sub` (host id), `type` (`access`|`refresh`), `iat`, `exp`, `jti`. `access` 15 min, `refresh` 30 days. `jti` persisted as `refresh_tokens` row.

### POST /auth/refresh
```json
{ "refresh_token": "jwt" }
```
- Rejects `access` token (`type` mismatch) → `401`.
- Rejects unknown/revoked `jti` → `401`.
- On success: marks old `jti` revoked, mints new access+refresh pair (persist new `jti`), commits. `200` → same shape as login.
- Replay of used refresh token → `401`.

### POST /auth/logout
```json
{ "refresh_token": "jwt" }
```
- Revokes `jti`. Further `refresh` with same token → `401`. `204` on success.

### GET /auth/me and GET /me
Bearer `access_token` required (`Authorization: Bearer <token>`).
- `200` → `HostProfileResponse`.
- No token / bad signature / expired / `type != access` → `401`.

---

## Profile

### GET /me
`Authorization: Bearer <access_token>` required.
- `200` → `{ id, email, username, display_name, timezone }`

### PUT /me
`Authorization: Bearer …` required.
```json
{ "username": "alice", "display_name": "Alice", "timezone": "America/New_York" }
```
All fields optional; unknown fields are ignored by `ProfileUpdateRequest`? (no `extra=forbid` on profile, only on booking). Validations:
- `username`: lowercased, 3–30, `^[a-z0-9]([a-z0-9_-]*[a-z0-9])?$`, not reserved (`admin` etc.). Case-insensitive unique → `409 Username already taken`.
- `display_name`: trimmed, non-blank if present, ≤100 chars.
- `timezone`: `ZoneInfo` validated.

Changing `username` changes public URL immediately; no alias history.

---

## Meeting Types

All require `Authorization: Bearer`.

### POST /meeting-types
Create the single meeting type for the host.
```json
{
  "title":"30 Minute Meeting","event_slug":"30min","duration":30,
  "active":true, "minimum_notice":60, "horizon_days":60
}
```
- `title`: 1–200 chars trimmed, required.
- `event_slug`: URL-safe, 1–30, not reserved, `lower()`-unique per host is not enforced at create (only one per host, but slug semantics mirrored from username).
- `duration`: `15|30|45|60` required.
- `minimum_notice` / `minimum_notice_minutes`: 0–10080, alias-compatible.
- `horizon_days` / `horizon`: 1–365, alias-compatible. Defaults 60 each.
- Second POST for same host → `409 Meeting type already exists`.
- `201` → `MeetingTypeResponse`.

Response shape `MeetingTypeResponse` (`meeting_types/schemas.py:9`):
```json
{
  "id":"uuid","host_id":"uuid","title":"...","event_slug":"30min",
  "duration":30,"active":true,
  "minimum_notice":60,"horizon_days":60,
  "horizon":60,"minimum_notice_minutes":60
}
```

### GET /meeting-types
List (0 or 1) for current host.

### GET /meeting-types/{id}
Ownership-checked. Non-owned / missing → `404`.

### PUT /meeting-types/{id} and PATCH /meeting-types/{id}
`MeetingTypeUpdateRequest` (all fields optional). `apply_update` validates updates, handles slug uniqueness per host. `200` on success, `404` if not found/owned, `409` on conflict.

### PUT /meeting-types and PATCH /meeting-types
Singleton update — resolves host’s meeting type without id. Same semantics. `404` if no meeting type exists.

Deactivating (`active: false`) makes the public meeting/slots return `404 meeting_type_inactive` and booking `409/404 meeting_type_inactive`.

---

## Availability

All require `Authorization: Bearer`.

### GET /availability
- `200` → `{ windows: [{weekday:int, start:"HH:MM", end:"HH:MM"}…] }` sorted by `weekday, start`.

### PUT /availability
Atomically replaces all windows in one transaction.
```json
{ "windows": [{"weekday":0,"start":"09:00","end":"12:00"}, {"weekday":0,"start":"13:00","end":"17:00"}] }
```
- `weekday` 0=Mon … 6=Sun, `start`/`end` `HH:MM` `00:00–23:59`. `start < end` (overnight rejected). Same-weekday overlap → `422`; adjacent allowed. Empty `windows:[]` clears schedule.
- Returns `200` with persisted windows sorted.
- No `PATCH` — full replacement only.

---

## Bookings (host-scoped + token-protected)

### GET /bookings
Bearer required. Host-scoped list.
- Query: `?status=confirmed|cancelled&from=ISO&to=ISO` (time filters on `start_time`). Invalid `status` → `422`. Invalid datetime → `422`.
- Ordered by `start_time asc`.

### GET /bookings/{booking_id}
Bearer required. Booking must belong to current host → `404` otherwise.

### POST /bookings/{booking_id}/cancel
No Bearer — token in body.
```json
{ "management_token": "raw-token-from-booking-response" }
```
- Validates `SHA256(token) == management_token_hash`. Invalid → `401 invalid_management_token`. Missing booking → `404 booking_not_found`.
- Idempotent: already `cancelled` → returns cancelled state, `200`.
- Cancels in transaction, sets `status='cancelled'`, `updated_at=now()`.

### POST /bookings/{booking_id}/reschedule
```json
{ "management_token":"...", "new_slot_start":"2026-09-01T09:30:00Z" }
```
- `new_slot_start` must include timezone.
- `401` bad token, `404` not found, `409 booking_not_confirmed` if `status != confirmed`, `409 reschedule_same_interval` if new == old.
- Validates new slot via provider+notice/horizon+overlap (self excluded). `409 slot_no_longer_available` if not a valid candidate.
- Atomic: creates new `Booking(status='confirmed', management_token_hash=copied, predecessor_id=old.id)`, cancels old, re-validates via filtered bookings, commits together. On `EXCLUDE` violation → `409 booking_conflict`.

`BookingOut` shape (`bookings/schemas.py:7`):
```json
{
  "id":"uuid","host_id":"uuid","meeting_type_id":"uuid",
  "invitee_name":"Bob","invitee_email":"bob@example.com","notes":null,
  "start_time":"2026-09-01T09:00:00Z","end_time":"2026-09-01T09:30:00Z",
  "slot_start":"…","slot_end":"…","status":"confirmed",
  "created_at":"...","updated_at":"...","predecessor_id":null
}
```

---

## Public (no auth)

### GET /{username}/{event_slug}
Returns public meeting info or `404`.
```json
{ "username":"alice","display_name":"Alice","timezone":"America/New_York","title":"30 Minute Meeting","duration":30,"event_slug":"30min" }
```
- `host_not_found` (404) if username unknown.
- `meeting_type_not_found` (404) if slug missing for host.
- `meeting_type_inactive` (404) if `active=false`.
- Never includes email, password hash, or invitee data.

### GET /{username}/{event_slug}/slots
```text
GET /alice/30min/slots?from=2026-09-01&to=2026-09-07&timezone=Europe/Berlin
```
- `from`, `to`: `YYYY-MM-DD` or ISO datetime (date part extracted). `from ≤ to` else `422`.
- `timezone`: valid IANA invitee zone (validated before host lookup); invalid → `422`.
- Unknown host/slug inactive → `404` (deleted or deactivated host meeting types yield `404`).
- `200` → `{ slots: [{ start:"2026-09-01T11:00:00+02:00", end:"2026-09-01T11:30:00+02:00", start_utc:"2026-09-01T09:00:00+00:00", end_utc:"..." }], timezone:"Europe/Berlin" }`.

### POST /{username}/{event_slug}/bookings
```json
{ "invitee_name":"Bob","invitee_email":"bob@example.com","slot_start":"2026-09-01T09:00:00Z","notes":null }
```
- `invitee_name`: 1–200 trimmed non-blank.
- `invitee_email`: `EmailStr`.
- `slot_start`: `datetime` with timezone (ISO8601; `Z` accepted).
- `notes`: optional, ≤2000 chars. Extra fields → `422 validation_error`.
- Validates host timezone set (`422 host_timezone_not_set`), active state (404), and that `slot_start` is exactly a generated candidate (via `valid_starts` set) — stale/conflicting → `409 slot_no_longer_available`.
- Maps `EXCLUDE` violation → `409 booking_conflict` (private message, no invitee disclosure).
- `201` →
```json
{ "id":"uuid","status":"confirmed","invitee_name":"Bob","invitee_email":"bob@example.com","notes":null,"slot_start":"2026-09-01T09:00:00Z","slot_end":"2026-09-01T09:30:00Z","management_token":"…" }
```
`management_token` is returned **once**; only its SHA-256 digest is persisted.

---

## Error Catalog

| HTTP | code | When |
|---|---|---|
| 401 | `unauthenticated` | Missing/bad Bearer. |
| 401 | `unauthorized` / `Could not validate credentials` | Bad signature, expired, `type` mismatch, revoked `jti`. |
| 401 | `invalid_management_token` | Bad booking management token. |
| 404 | `not_found` | Generic resource not found. |
| 404 | `host_not_found` | Public: unknown username. |
| 404 | `meeting_type_not_found` | Public/slots: unknown slug for host. |
| 404 | `meeting_type_inactive` | Deactivated meeting type. |
| 404 | `booking_not_found` | No booking with that id. |
| 409 | `conflict` | Generic conflict (username/slug unique violation). |
| 409 | `slot_no_longer_available` | Selected slot stale/out of window/notice/horizon/cancelled-window. |
| 409 | `booking_conflict` | Postgres `EXCLUDE` overlap — another booking won the race. |
| 409 | `booking_not_confirmed` | Reschedule on cancelled booking. |
| 409 | `reschedule_same_interval` | New slot == current. |
| 422 | `validation_error` | Pydantic validation / malformed input, includes `details[{field,message}]`. |
| 422 | `host_timezone_not_set` | Host has no timezone; booking disabled. |

All non-4xx errors mirror PRD § API Contracts error envelope. See `src/meet_scheduler/main.py:28-79` for handler source.

---

## Notes

- OpenAPI schema: `GET /openapi.json`.
- Slots are advisory; booking revalidates inside transaction.
- For concurrency behavior see `tests/public/test_bookings.py:299-386` (real threads + `pg_blocking_pids`) and `docs/ARCHITECTURE.md`.
