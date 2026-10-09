# Development changelog

Local development history reviewed 2026-10-09. Only source-confirmed implemented
work is listed; planned features belong in `PROJECT_STATUS.md`.
Dates for committed entries come
from local Git history. The working-tree entries below have no verified release
date: their implementation exists locally, but commit, deployment and test-pass
status are not established by this documentation task.

## Unreleased — completed local implementation

Completed here means the described implementation is present and integrated in
the current working tree. It does not mean tests passed or acceptance is complete.

### Recording lifecycle UI improvements

- Refined recording-job presentation and dashboard/import/admin controls,
  including lifecycle/review-state feedback.
- Evidence: working-tree diffs in `frontend/src/components/recording-jobs.tsx`,
  `import-modal.tsx`, `state-badge.tsx`, dashboard/admin/meeting clients and
  associated recording-job and meeting-detail test changes.

### Action Item Review improvements

- Added task/owner/deadline/confidence/evidence table, missing-field and
  low-confidence flags, source-quote context, validation and retained drafts on
  save failure. Confidence is presented separately from approval status.
- Evidence: `frontend/src/app/meetings/[id]/action-item-review.tsx`, meeting-detail
  integration and `__tests__/action-item-review.test.tsx`.

### Email consistency fix

- Email action task, owner and deadline now come from reviewed action-item rows
  instead of stale extracted JSON. Supplemental context still comes from raw data.
- Action-item edits acquire the approval lock and reject sending/sent delivery.
- Evidence: diffs in `app/email_templates.py`, `app/api/reviews.py`,
  `app/tests/test_email_templates.py` and `test_action_item_consistency.py`.

### Action Items Phase 1A

- Added read-only approved-action endpoint and page with My Actions / All
  Accessible views, meeting/owner/deadline text filters, pagination and evidence.
- Results require approved actions, approved/sent meetings and existing view
  access. My Actions uses owner email, without inferring identity from names.
- Evidence: `app/api/action_items.py`, response schemas, `test_action_items_readonly.py`,
  `frontend/src/app/action-items/`, API/types and navigation changes.
- Phase 1A is the requested documentation label; no release with that name is
  established in local Git history.

### UX improvements

- Updated dashboard, recording imports/jobs, administrator controls and meeting
  review presentation; Action Items adds loading/error/empty-state guidance and
  source evidence disclosure.
- Evidence: existing frontend working-tree diffs and Action Items client source.

## 2026-10-06 — `139ed37`

Committed reliability, audit logging and recording-performance work: audit-event
model/migration and administrator audit UI/API, recording and email audit paths,
status diagnostics and recording query/control changes with associated tests.
Source evidence: `git show --stat 139ed37` and current corresponding modules.

## 2026-10-05 — `e7e9ffc`

Committed meeting-recording workflow reliability changes to recording-job UI,
meeting detail and worker-poll configuration. Source evidence:
`git show --stat e7e9ffc` and its patch.

## 2026-10-02 — `fa5f749`

Committed fix for async lazy loading in the recording-jobs endpoint, as recorded
by the Git commit subject and current eager-loading implementation.

## Earlier committed UX and stability work

- 2026-09-30 `1c9d277` and 2026-09-29 `3746793`: stability, error handling and UX
  improvements, as recorded in commit subjects.
- 2026-09-25 `d779650`: frontend/backend loading performance work.
- 2026-09-23 `04ac456`, `cc57e84`: dashboard feedback and meeting-access status.
- 2026-09-22 `e1ffeca`: API outage feedback instead of a misleading meeting 404.

These entries record implementation history, not fresh test results or proof of
the current deployed version.
