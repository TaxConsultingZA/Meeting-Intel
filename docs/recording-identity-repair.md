# Recording identity repair — 2026-10-26

## Scope and observed evidence

Read-only inventory found 50 Unknown recordings and the explicit Test case.
All 51 exact Graph drive/item metadata reads succeeded. None of the 50 Unknown
rows had an imported meeting or processing job; each lacked the saved filename.
36 have title/time candidates requiring owner confirmation. 14 have no matching
candidate in the owner's +/-2 day calendar window. This does not prove that no
event exists elsewhere or in deleted/historical calendars.

Test item 01LIX265JFMJPO3YO52BELGAXDCTWU7SPI exists in its owner's Recordings
folder, but its preserved meeting is linked to the unrelated Trust classroom
session. The actual Test calendar occurrence could not be established by stable
event identity. No record is automatically rebound from title/time similarity.

## Behavior

- Display filename, Graph recording time and file size independently of results.
- Owner-controlled association stores stable calendar event ID/iCalUId or an
  independent choice in processed_items.identity_json. It changes no participants,
  transcript, summary, review result, approval or job history.
- Historical mismatch has an explicit needs_review state and uses the filename.
- Exact owner-drive verification applies even to administrators. Active processing
  blocks identity changes; cancelled/completed jobs remain intact.
- New matching rejects placeholders, differing normalized titles and ambiguous
  nearby occurrences. It uses offset-bearing Graph timestamps.
- Discover files scans only the authenticated subscribed owner's OneDrive,
  exhausts valid pagination, persists idempotent discoveries and queues no work.
- Refresh reloads saved rows. Manual Calendar Sync updates calendar cache only.
  ENABLE_SCHEDULED_SYNC and ENABLE_AUTO_RECONCILE remain unchanged (both false).

## Data procedure

scripts/audit_recording_identity.py is GET/SELECT-only. The repair tool has separate
plan, migrate, apply, verify and rollback commands. Plans and backups include exact
before/after ledger fields and must remain in an ignored/private folder.

Apply modifies only filename and identity_json after locking and comparing each
ledger row. Rollback restores exactly those fields and rejects intervening edits.
Protected table fingerprints are compared before/after; the baseline is recorded.
The additive Alembic migration is 70b4e91f8a20; it does not rewrite meeting data.

Private inventory.csv includes every original filename, item/drive ID, recording
time, meeting ID, task statuses, transcript/summary/review indicators and candidate
IDs. It and raw Graph evidence are deliberately excluded from Git/deployment.

## Validation

186 backend tests and 58 frontend tests passed. TypeScript and local production
build (webpack) passed. Default local Turbopack could not use the shared dependency
junction outside its filesystem root; the source itself compiled via webpack.
Cloud deployment installs its own dependencies.

Acceptance must check exact inventory IDs through authenticated owner sessions:
the 50 filenames replace Unknown; Test shows its original filename and no verified
calendar link with preserved review/processing history. Other users must not see
these private owner rows. A successful build alone is not acceptance.
