# Recording read recovery — 2026-10-27

Scope: frontend import dialog only, on top of 8e1f0fb. No API/auth/worker changes, discovery, matching, transcription or data migrations.

## Evidence and limits

The previous visible status-error message is emitted only by the background GET /recordings/jobs catch handler. A bounded read-only API log sample contains 535 requests from 08:27:09Z to 11:12:48Z: jobs 418 HTTP 200 / 29 HTTP 401; reviews 70 HTTP 200 / 8 HTTP 401; users/me 5 HTTP 200; recordings/available 5 HTTP 200. The last observed jobs authentication-failure interval was 10:14:08Z–10:15:44Z, followed by HTTP 200 at 10:15:58Z. There are no 5xx or exception-class records in this sample.

Historical browser request detail for the precise visible-error instant is unavailable; queried frontend runtime logs and currently captured browser error logs provide no attributable sample. These limits do not prove an absent network fault, and HTTP 401 alone does not establish token expiration. No Graph or calendar investigation was repeated.

A deterministic regression test failed against 8e1f0fb: one rejected background status read followed by successful reads leaves the original cached-data alert displayed. This proves the frontend recovery defect independently of the unconfirmed cause of the original rejected request.

## Minimal correction

- Opening a dialog keeps supplied rows visible as cached while revalidating GET /recordings/available and GET /recordings/jobs.
- Only a successful pair replaces the snapshot, clears a prior read error, and displays “Recording list and task status loaded successfully.”
- A failed background read invalidates that marker; non-auth recovery rechecks both saved-data endpoints before clearing the warning. Status-only success cannot certify a failed list read.
- HTTP 401 keeps the cached-state warning, offers a normal canonical /login link and stops repeated background attempts. No token, cookie, error body or credentials are displayed.
- Explicit Refresh still performs saved list/status reads only. It never runs discovery, matching or transcription.

## Verification

The original failing test now passes. Added partial-recovery, cached-snapshot, and HTTP-401 stop/relogin tests. All 394 frontend tests, TypeScript, changed-file ESLint and production webpack build pass. No protected business data or permissions are written by this patch. Private sanitized diagnostics and read-only data fingerprints are retained in ignored artifacts/local-test-recordings/status-read-blocker-20261027/.

Deployment and canonical-session acceptance are recorded separately after publishing the same tested commit. The prior known usable frontend remains the rollback target; any actual acceptance failure requires immediate rollback. Sphesihle SharePoint file gaps remain unknown and unaccepted.
