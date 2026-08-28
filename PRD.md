# Minimal One-on-One Meeting Scheduler Backend

## Problem Statement

People need a simple way to publish their recurring weekly availability and let another person reserve a one-on-one meeting through a shareable link. Existing scheduling products provide substantially more organization, workflow, calendar, conferencing, and notification functionality than this initial product requires.

The first release needs a reliable backend that lets a host create an account with an email address and password, authenticate securely, configure one meeting type and a weekly schedule, and receive conflict-free bookings. Invitees must be able to inspect available times in their own time zone without creating an account. Slots beginning less than one hour from the current time must never be offered or accepted.

## Solution

Build an API-first scheduling backend using FastAPI, PostgreSQL, SQLAlchemy, and Alembic. A host registers with a unique email address and password, then signs in to receive JWT access and refresh credentials. Passwords are hashed with Argon2id before persistence and are never stored or logged in plaintext. The host chooses a public username, configures one fixed-duration meeting type, and saves one or more recurring availability windows for each weekday in an IANA time zone.

The application exposes a public link in the form `/{username}/{event-slug}`. An invitee uses that link to retrieve the meeting details and currently bookable slots in a requested time zone. The invitee supplies a name and email, with optional notes, to create an immediately confirmed booking. The booking blocks overlapping times transactionally. The invitee can later cancel or reschedule through an unguessable management token without registering.

The MVP uses only availability and bookings stored in this application. It does not synchronize external calendars, send notifications, create video-conference links, or support organizations.

## User Stories

1. As a prospective host, I want to register with my email address and a password, so that I can create an account directly in the application.
2. As a host, I want my password stored only as a secure hash, so that a database disclosure does not reveal my password.
3. As a registered host, I want to sign in with my email address and password, so that I can access my scheduling account.
4. As an authenticated host, I want short-lived JWT access credentials and a renewable refresh credential, so that I can use protected APIs without repeatedly entering my password.
5. As a host, I want to sign out and revoke my refresh credential, so that it cannot be used again.
6. As a host, I want to choose a unique public username, so that I can share a memorable booking link.
7. As a host, I want to change my public username, so that I can correct or update my public identity.
8. As a host, I want to set my display name, so that invitees know whose meeting they are booking.
9. As a host, I want to select my IANA time zone, so that my recurring schedule remains meaningful across time zones and daylight-saving changes.
10. As a host, I want one meeting type, so that I can offer a focused scheduling experience without managing a catalog of events.
11. As a host, I want to give my meeting type a title, so that invitees understand the purpose of the meeting.
12. As a host, I want to choose a 15, 30, 45, or 60 minute duration, so that the meeting fits my needs.
13. As a host, I want a unique event slug, so that my public link is readable and stable.
14. As a host, I want to activate or deactivate my meeting type, so that I can temporarily stop accepting bookings without deleting my setup.
15. As a host, I want to define recurring weekly availability, so that I do not have to enter the same working hours for every date.
16. As a host, I want to add multiple availability windows on one weekday, so that breaks such as lunch do not appear as bookable time.
17. As a host, I want to leave a weekday empty, so that no slots are offered on that day.
18. As a host, I want invalid or overlapping weekly windows to be rejected, so that my schedule has unambiguous behavior.
19. As a host, I want to replace my weekly availability atomically, so that invitees never see a partially updated schedule.
20. As a host, I want bookings to block overlapping times, so that I cannot be double-booked.
21. As a host, I want simultaneous attempts to reserve the same time to result in only one confirmed booking, so that concurrency cannot create conflicts.
22. As a host, I want to list my upcoming and past bookings, so that I can see what has been scheduled.
23. As a host, I want cancelled bookings to remain distinguishable from confirmed bookings, so that booking history is not lost.
24. As an invitee, I want to open a public booking link without signing in, so that booking has minimal friction.
25. As an invitee, I want to see the host's display name, meeting title, and meeting duration, so that I know what I am booking.
26. As an invitee, I want to request slots in my own time zone, so that I do not need to convert the host's schedule manually.
27. As an invitee, I want unavailable and already-booked times omitted, so that every displayed slot is a valid candidate at the time it is returned.
28. As an invitee, I want slots starting less than 60 minutes from now omitted, so that I cannot book without sufficient notice.
29. As an invitee, I want to see slots up to 60 days ahead, so that I can plan ahead within the supported booking window.
30. As an invitee, I want to provide my name and email, so that the host can identify me.
31. As an invitee, I want to add optional notes, so that I can give the host useful context.
32. As an invitee, I want my valid booking to be confirmed immediately, so that I do not have to wait for host approval.
33. As an invitee, I want stale or conflicting booking attempts to fail clearly, so that I can select another currently available time.
34. As an invitee, I want to cancel through an unguessable link without creating an account, so that I can release a time I no longer need.
35. As an invitee, I want a cancelled time to become available again when it still satisfies all booking rules, so that another person can reserve it.
36. As an invitee, I want to view valid replacement slots before rescheduling, so that I can choose another suitable time.
37. As an invitee, I want rescheduling to move my booking atomically, so that a failed attempt does not destroy my existing reservation.
38. As an invitee, I want cancellation and rescheduling links to stop working when their token is invalid, so that other people cannot manage my booking.
39. As a privacy-conscious invitee, I want public availability responses to exclude attendee and booking details, so that another person's information is never exposed.
40. As an API client, I want validation failures and booking conflicts represented consistently, so that I can display actionable errors.
41. As a future product developer, I want slot calculation isolated from the source of availability rules, so that date-specific overrides can be added without changing the public booking contract.

## Implementation Decisions

### Product Vocabulary

- A **host** is an authenticated user who publishes availability and receives bookings.
- An **invitee** is an unauthenticated person who books, cancels, or reschedules a meeting.
- A **meeting type** is the single bookable event configured by a host.
- An **availability window** is a recurring host-local start and end time attached to a weekday.
- A **slot** is a candidate interval derived from an availability window after notice, horizon, and conflict rules are applied.
- A **booking** is a reserved one-on-one interval between one host and one invitee.

### Technology and Architecture

- The backend will use Python and FastAPI for HTTP APIs.
- PostgreSQL will be the source of truth.
- SQLAlchemy will provide ORM and transaction management.
- Alembic will manage schema migrations.
- API request and response contracts will use Pydantic models.
- The backend is API-first. No frontend is included in this specification.
- Domain behavior will be separated into authentication, host profile, meeting type, availability, slot calculation, and booking capabilities.
- Slot calculation will consume an availability-provider boundary rather than querying recurring windows throughout the codebase. The initial provider returns only weekly recurring windows. A future provider can merge weekly windows with date-specific overrides without changing public slot or booking APIs.

### Authentication and Authorization

- Email and password are the only host registration and login method in the MVP.
- Host email addresses are normalized and case-insensitively unique.
- Passwords must be between 8 and 128 characters. The MVP does not impose character-class rules.
- The backend will hash passwords with Argon2id using a maintained password-hashing library that generates a unique salt and stores algorithm parameters in the encoded hash.
- Only the encoded Argon2id hash is persisted. Plaintext passwords must never be written to the database, logs, tokens, exceptions, analytics, or API responses.
- Login verifies the submitted password against the encoded hash. Authentication failures return the same status and message whether the email is unknown or the password is incorrect.
- A successful registration returns the created host's safe account representation. A host signs in separately to receive credentials.
- A successful login issues a signed JWT access token valid for 15 minutes and a JWT refresh token valid for 30 days.
- JWTs use a strong environment-provided signing secret and include the host identifier as `sub` plus `type`, `iat`, `exp`, and unique `jti` claims. Access and refresh tokens are not interchangeable.
- Refresh-token identifiers are stored in a revocable form. Refresh rotates the credential, invalidating the used refresh token and issuing a new access and refresh pair.
- Logout revokes the applicable refresh credential. Access tokens remain valid only until their short expiration.
- Authenticated host endpoints may only read or mutate resources owned by the current host.
- Invitees do not authenticate. Booking management endpoints require a cryptographically random, unguessable token scoped to one booking.
- Raw booking-management tokens will not be stored in plaintext. Only a secure digest will be persisted.

### Host and Public Identity

- Each host has one case-insensitively unique username.
- Usernames and event slugs use a URL-safe normalized form. Reserved route names cannot be selected.
- Changing a username changes the public booking URL. Redirects from historical usernames are not required.
- A host must have a username, valid IANA time zone, active meeting type, and at least one weekly availability window before slots can be offered.
- Public responses expose only the host display name, public username, time zone when needed for clarity, meeting title, duration, and computed slots. They never expose host email addresses, password hashes, private account metadata, invitee details, or booking records.

### Meeting Type

- Each host can own exactly one meeting type in the MVP.
- The meeting type contains a title, event slug, duration, active state, minimum notice, and future booking horizon.
- Duration must be one of 15, 30, 45, or 60 minutes.
- Minimum notice defaults to 60 minutes and is configurable for the meeting type.
- The future booking horizon defaults to 60 days and is configurable for the meeting type.
- No buffer exists before or after a booking in the MVP.
- The host can deactivate the meeting type. A deactivated meeting type exposes no slots and rejects new bookings without deleting existing booking history.

### Weekly Availability

- Availability is defined in the host's IANA time zone, not as fixed UTC offsets.
- A host may define zero or more windows for each weekday.
- Each window contains a weekday, inclusive local start time, and exclusive local end time.
- Start time must precede end time. Overnight windows are not supported; a host must split availability across adjacent weekdays.
- Windows on the same weekday cannot overlap. Adjacent windows are allowed but may be normalized into a single continuous interval.
- Replacing weekly availability occurs in one transaction.
- Date-specific overrides, holidays, and one-off availability are not implemented. The availability-provider boundary must allow those rules to be introduced later without altering booking storage or public API contracts.

### Time and Slot Generation

- Persisted booking timestamps use timezone-aware UTC values.
- Recurring availability retains weekday and host-local wall-clock values so that it follows the host's configured time zone across daylight-saving transitions.
- Public slot requests must include a valid invitee IANA time zone and a bounded date range.
- Slot generation expands the host's weekly windows into concrete intervals for the requested dates, converts those intervals to UTC, applies business rules, and returns localized representations for the requested invitee time zone.
- Candidate slots begin at each availability window's start and advance in increments equal to the meeting duration. A candidate is included only if its entire interval fits within the availability window.
- A candidate is excluded if it overlaps any confirmed booking for the host.
- A candidate is excluded when its start is earlier than `current server time + minimum notice`. A slot beginning exactly at that boundary is allowed.
- A candidate is excluded when its start is later than the configured future booking horizon.
- Notice and horizon comparisons occur against UTC instants using a request-scoped server time, avoiding drift during one calculation.
- Nonexistent local times caused by daylight-saving transitions produce no slot. Ambiguous local times must be resolved consistently and must never yield duplicate UTC slots.
- Slot responses are advisory. Every rule is checked again inside the booking transaction because another invitee may reserve a returned slot before it is submitted.

### Bookings and Conflict Protection

- A booking contains the host, meeting type, invitee name, invitee email, optional notes, UTC start and end timestamps, status, management-token digest, and audit timestamps.
- Invitee name and email are required. Notes are optional and length-limited.
- A new valid booking is immediately assigned `confirmed` status. Host approval is not part of the lifecycle.
- The backend derives the booking end from the selected meeting duration. Clients cannot choose an arbitrary end timestamp.
- New bookings must exactly match a slot generated from the host's current availability and meeting-type rules.
- PostgreSQL will enforce that a host cannot have overlapping confirmed booking intervals. The constraint must cover all confirmed bookings for a host rather than relying only on an application-level pre-check.
- Booking creation runs in a transaction and maps a database overlap violation to a stable conflict response. Under concurrent requests for the same slot, one request may succeed and all others must fail without creating duplicate bookings.
- Cancelled bookings remain in storage for history but no longer block their interval.
- Cancellation is idempotent: cancelling an already cancelled booking returns its cancelled state without creating another transition.
- A cancellation request requires the valid management token.
- Rescheduling requires the valid management token and a currently valid replacement slot.
- Rescheduling is atomic. The existing booking remains confirmed if the replacement cannot be reserved.
- A successful reschedule preserves a traceable booking history, either through booking revision metadata or a link between the old and replacement reservation, while exposing one current confirmed reservation to the host.
- A booking cannot be rescheduled to its current interval as a way to bypass current notice or availability rules.

### API Contracts

- Authentication APIs register a host, log in with email and password, rotate application credentials using a refresh token, revoke a refresh credential, and return the current host profile.
- Authenticated profile APIs read and update display name, username, and IANA time zone.
- Authenticated meeting-type APIs create or update the host's single meeting type and change its active state.
- Authenticated availability APIs read and atomically replace the full recurring weekly schedule.
- Authenticated booking APIs list the host's bookings with status and time filters and retrieve an individual owned booking.
- A public meeting API resolves the username and event slug and returns only public host and meeting information.
- A public slots API accepts a date range and invitee time zone and returns currently eligible slot start and end timestamps.
- A public booking API accepts a selected slot start, invitee name, invitee email, and optional notes. It returns the confirmed booking details and the one-time booking-management token.
- Token-protected booking APIs expose the booking's invitee-safe details, return valid rescheduling slots, cancel the booking, and atomically reschedule it.
- Public identifiers and tokens should use non-sequential values that do not disclose record counts.
- API errors will use one consistent structured envelope containing a machine-readable code, human-readable message, and field details when applicable.
- The API will distinguish malformed input, unauthenticated access, unauthorized ownership, missing or inactive public resources, invalid management tokens, no-longer-valid slots, and booking conflicts.
- Conflict responses will not disclose who owns the conflicting booking.

### Operational Behavior

- The service must use a database transaction for multi-record schedule replacement, booking creation, cancellation, and rescheduling.
- Database migrations must be repeatable and safe for a clean environment.
- Token-signing secrets and database credentials must come from environment-based configuration and never be committed.
- Logs must not contain plaintext passwords, password hashes, application access or refresh tokens, booking-management tokens, or unnecessary invitee personal information.
- Health endpoints may report process and database readiness without exposing sensitive configuration.

## Testing Decisions

- The primary testing seam is the HTTP API. Tests should exercise externally observable behavior through FastAPI requests and verify persisted outcomes using an isolated PostgreSQL test database.
- Tests should assert contracts and business behavior rather than private function calls, ORM query shape, or implementation-specific method invocation.
- PostgreSQL, rather than an in-memory database substitute, is required for booking integration tests because overlap constraints, transaction behavior, and concurrency are core product guarantees.
- Registration tests cover valid registration, normalized case-insensitive email uniqueness, password length boundaries, safe response fields, and rejection of duplicate accounts.
- Authentication tests cover successful and failed login, generic invalid-credential responses, JWT claims and expiration, access-token requirements, refresh rotation and replay rejection, logout revocation, and cross-host authorization.
- API tests verify password behavior through registration and login. A focused PostgreSQL persistence test additionally verifies the security invariant that the stored credential is an Argon2id encoded hash and never equals the submitted password.
- Profile tests cover username normalization, case-insensitive uniqueness, reserved names, valid IANA time zones, and public URL changes.
- Meeting-type tests cover the one-per-host rule, allowed durations, active state, notice configuration, horizon configuration, and ownership.
- Availability tests cover empty weekdays, multiple windows, invalid ranges, overlapping windows, adjacent windows, atomic replacement, and host-local time-zone persistence.
- Slot API tests cover duration alignment, partial trailing intervals, multiple windows, booked intervals, inactive meeting types, empty schedules, invalid request ranges, and invitee time-zone conversion.
- Boundary tests freeze the request-scoped clock and verify that a slot 59 minutes and 59 seconds away is rejected while a slot exactly 60 minutes away is allowed under the default notice.
- Horizon tests verify the 60-day default and ensure clients cannot obtain or create a booking outside the configured range.
- Daylight-saving tests cover spring-forward nonexistent times, fall-back ambiguous times, date changes between host and invitee zones, and zones without daylight saving.
- Booking tests verify required invitee fields, server-derived end times, current availability revalidation, immediate confirmation, private response data, and stable conflict errors.
- A real concurrent integration test sends multiple booking attempts for the same slot and verifies that exactly one confirmed booking exists.
- Cancellation tests cover valid, invalid, and repeated token use and verify that a cancelled interval becomes bookable when all other rules permit it.
- Rescheduling tests cover valid moves, invalid replacement slots, conflicts, atomic rollback, history preservation, and token authorization.
- Privacy tests verify that public meeting, slot, and conflict responses never expose invitee data or private host identity data.
- There is no existing application test suite or prior application test pattern in the repository. The first implementation should establish API integration fixtures around FastAPI and isolated PostgreSQL as the project's testing precedent.

## Out of Scope

- Organizations, teams, memberships, roles, permissions beyond host ownership, round-robin scheduling, and collective events.
- More than one meeting type per host.
- Meetings with more than one host or invitee.
- Google, Apple, Microsoft, and other social or OAuth identity providers.
- Magic-link authentication, email verification, password reset, multi-factor authentication, account recovery, and breached-password lookup.
- Date-specific availability overrides, one-off availability, holidays, and vacation periods.
- Google Calendar, Outlook, Apple Calendar, or other external calendar synchronization.
- Calendar event creation and downloadable calendar invitations.
- Email, SMS, push, webhook, or other booking notifications and reminders.
- Zoom, Google Meet, Microsoft Teams, or other conferencing integration.
- Host-provided physical locations or static meeting URLs.
- Host approval, tentative booking states, waitlists, and booking requests.
- Payments, subscriptions, billing, coupons, and usage limits.
- Custom invitee questions, required phone numbers, and custom forms.
- Buffers, travel time, daily booking limits, group capacity, and complex scheduling rules.
- Username redirect history and custom domains.
- A frontend, mobile application, or administrative dashboard.
- Importing historical bookings or accounts from other scheduling products.

## Further Notes

- The first implementation should favor a small, explicit domain model over generic scheduling abstractions. The availability-provider boundary is the intentional extension point for future date-specific overrides.
- The public slot list is never a reservation. Transactional conflict protection and complete rule revalidation at booking time are required correctness boundaries.
- The product deliberately does not notify invitees. The booking response must therefore present the management token/link clearly because it is the invitee's only way to return and cancel or reschedule.
- The repository did not contain issue-tracker configuration, triage-label vocabulary, application code, ADRs, or a domain glossary when this PRD was created. This document defines the initial vocabulary and cannot be published with a `ready-for-agent` label until project issue tracking is configured.
