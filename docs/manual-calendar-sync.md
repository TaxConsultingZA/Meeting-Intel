# Manual calendar sync

Dashboard shows **Sync calendar now** only to a subscribed administrator. One
click sends one authenticated `POST /calendar/sync` with an empty JSON object.
Caller-supplied user lists are rejected. The button has an immediate click guard;
the backend uses a PostgreSQL advisory lock to reject overlapping manual runs
across API instances with 409. There is no automatic retry or new timer.

The backend snapshots active subscribers, then rechecks subscription and a
nonempty Entra identity link under a row lock before each calendar read. Users
who opted out or lack that link are skipped. Subscription is preserved during
the read using the same row lock used by opt-out. An identity link proves sign-in,
not calendar consent: the existing app-only Microsoft credential and existing
`.default` grant are reused, and Microsoft enforces mailbox/calendar access.
Denied access is a failed user sync; no consent or new permission is requested.
No number of users or account names is hardcoded.

The existing Calendar window and upsert behavior are reused (30 days back,
14 days forward, including offline events). Only cached calendar events and sync
status are written. Recording discovery, jobs, AI, mail, and workers are not called.
`created` counts new event rows; `updated` counts existing rows refreshed, including
unchanged events whose sync timestamp is refreshed. Responses contain only counts
and success/partial/failed status. Per-user failures do not retry or stop the other
eligible subscribers. The Dashboard refreshes calendar/status reads independently
and revalidates Recent Meetings while preserving its filters.

`ENABLE_SCHEDULED_SYNC=false` retains its existing behavior. This action does not
enable the schedule. It does not start a worker. The existing frontend request
timeout still applies; an unconfirmed response requires checking sync status
before manually trying again, and a still-running manual operation rejects overlap.

Public availability requires a separately authorized deployment of both frontend
and backend, retaining disabled scheduled sync and stopped recording workers.
A subscribed admin must sign in; intended users need active subscriptions, Entra
identity links and existing Microsoft calendar access. Review the eligible set
before clicking once. Implementation checks use mocked Graph and fake DB sessions;
they do not establish production grants, subscriber count or live sync results.
