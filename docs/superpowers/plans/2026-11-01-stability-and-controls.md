# Stability and controls implementation plan

Goal: fix the four confirmed lifecycle/state defects and keep navigation keys off automatic dashboards.

Design: pairing uses its own randomly generated MQTT session ID and must leave the loaded client running. Each flow owns and closes its temporary client on failure, cancellation, replacement or removal. Token-watch callbacks belong to a generation so stopped callbacks cannot reschedule or interfere with a restarted watch. Unknown power is not activity. Navigation button entities remain callable, but are hidden by default; entry migration 1.2 hides existing navigation buttons once without deleting IDs or overriding user-hidden entries. Screen buttons remain visible. The optional generated remote card remains available.

Alternatives: deleting navigation entities breaks existing automations; disabling them makes them uncallable. Hiding preserves both. Keeping the running MQTT client avoids restoring it after cancelled pairing; U7QF already uses independent session IDs.

Constraints: no TV commands, dependency installation, deployment, commits or changes outside this checkout. Tests use real local modules with doubles only at Home Assistant/MQTT boundaries because HA is unavailable. Keep the optional remote card compatible.

Execution: implement inline with regression tests first, then one independent review.

- [x] Add failing regression tests for failed/retried/cancelled pairing, runtime preservation, unknown activity, stopped/restarted token-watch generations, hidden navigation and one-time migration.
- [x] Fix flow client ownership and probe cleanup; run lifecycle tests.
- [x] Fix token-watch shutdown and activity state; run regressions.
- [x] Hide navigation defaults and migrate existing entries once; document optional card and hidden controls.
- [x] Run the complete unittest suite, Python/JSON syntax checks, diff check, and independent review.

Review focus: connected PIN dialogs must retain their flow client; cancelled/failed probes must release it; restart must invalidate older timer callbacks; migration must preserve user-hidden and unrelated entities and must not reapply after a user unhides a button; screen controls must stay visible.

Progress: baseline clean, 14 tests passing. New lifecycle tests initially failed on eight defective paths, then passed after fixes. Visibility/migration tests initially failed on visible navigation and missing migration, then passed. Final suite: 29 tests pass on Python 3.9 and 3.13; 64 Python files and 12 JSON files parse; diff check passes. Independent review found no actionable defects; HA visibility and migration APIs were checked against official source. Remaining validation limit: no actual HA runtime or TV exercise; MQTT/HA boundaries use doubles. Work remains in the authorized checkout; no Git metadata mutations. User requested implementation without additional approval steps.
