# Recording identity and SAST display release — 2026-10-27

## Release boundary

Base: 7c30e0fa5198fba6c8b0fada7022d35fae3e8157 on codex/recording-identity-repair.
The primary main checkout remains at d965b65 with its local changes untouched.
No BusinessAI, Decisions, unrelated search changes, settings or migrations are imported.
API, worker and frontend must be built from the same tracked Git archive.

## Changes

- User-facing shared instants render in Africa/Johannesburg with SAST. The modal's long zone label is removed. Calendar ranges also show SAST.
- Lists and modal sort parsed instants descending, with unknown/invalid times last; UTC and explicit offsets are interpreted once. Extracted unzoned text is not treated as a reliable instant.
- Authorized review reads batch-load separate file display metadata. File time is shown without rewriting the original calendar time, title, transcript, summary, approvals, tasks or permissions. An explicitly absent file time does not fall back to an old calendar time.
- A calendar link requires an actual event ID. A separate Teams evidence object must contain exact drive/item identity, a meeting ID and a recording reference before the API exposes a verified Teams title. No title or time overlap can create either identity.
- The modal keeps the actual filename primary and shows Teams and calendar identity separately, with reasons for undetermined records. The API returns the same owner-scoped data and time ordering.
- Graph recording time only uses offset-bearing creation metadata; last-modified, discovery and filename wall clocks cannot supply a missing recording time.
- Existing bounded nested OneDrive roots, delta checkpoints, matching rules and owner permissions are retained. SharePoint coverage is not asserted without a specific authorized directory/file.

## Existing-data reconciliation (not a new Graph/calendar scan)

Current read-only database/list snapshot: Wei 7 files in list, 5 calendar linked, 0 persisted Teams verifications, 2 undetermined; Nicole 47 / 19 / 0 / 28; Sphesihle 12 / 10 / 0 / 2. All listed rows have saved file times.
The last saved discovery checkpoint covers 7 / 47 / 12 personal-drive files respectively; these are historical known-directory counts, not proof of current complete Microsoft access. No additional missing list row is demonstrated within that saved scope. Missing files outside that scope remain unknown.
Sphesihle: accessible SharePoint file count, missing file count and updated personal-page acceptance are UNKNOWN / NOT ACCEPTED. The prior screenshot is not post-update acceptance.

Wei Test: exact original file exists and is listed, recording instant 2026-09-01T08:41:58Z (10:41 SAST). Existing review cf0acc35-d1cb-4847-b099-8620e971ebdb is retained. Correct Outlook event and stable Teams recording reference remain unconfirmed; never rebind Trust.
Wei October meeting: exact original file exists and is listed, instant 2026-10-22T06:50:32Z (08:50 SAST). Teams screenshot and recording-start message agree with the file creation instant, but a stable meeting-to-file reference is not yet persisted. Do not invent a Teams verification or link overlapping test 10.22. No imported review/job exists for this file.

## Verification before commit

- Backend: 282 tests passed across recording identity/update/delta, Wei cases, timezone/matching, owner permissions, review/catalog, pipeline and Graph tests.
- Frontend: 385 tests passed across 37 suites, including all four display locations, explicit UTC/+08/+02 instants, absent times, sorting and independent identity labels.
- TypeScript, production webpack build, changed-source ESLint and git diff whitespace check passed.
- Existing React act/key fixture warnings and Starlette HTTPX deprecation remain outside this scope.
- No production data writes, migrations, discovery/matching stages, transcription, retry/cancel or email actions were used for verification.

Private read-only snapshot and protected-table fingerprints are in ignored artifacts/local-test-recordings/integrated-release-20261027/. Existing evidence directories are preserved unchanged. Deployment IDs and actual-session acceptance are reported separately after release.
