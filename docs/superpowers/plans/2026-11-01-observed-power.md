# Observed TV Power Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Report TV power from explicit live telemetry without assumed values.

**Architecture:** One power parser handles documented state events and explicit `is_power_on` fields. A hardware-verified `gettvstate` request with payload `0` obtains the startup state once per runtime connection on the `hisenseservice` route, outside pairing. Retained messages never authorize power or replace a live observation; metadata responses without a power field cannot change power.

**Tech Stack:** Python, paho-mqtt, Home Assistant; stdlib unittest.

**Spec:** User request in this conversation: determine actual TV power; fabricated values can break integrations.

## Global Constraints

- No assumed power, no power inference from MQTT connectivity or picture settings.
- No periodic `gettvstate`; the hardware-verified payload `0` is permitted once per runtime connection on the `hisenseservice` route, outside pairing.
- No automatic power commands, input changes, or navigation during detection.
- Unknown, malformed, or unsupported power fields remain unknown.
- Interpret `fake_sleep_state` only after its polarity is verified on this TV; retain it as diagnostic evidence meanwhile.
- Direct TV access is blocked by the execution environment. Hardware verification must use a read-only capture run on the user's network.

## Review Focus

- Retained ON followed by sourcelist must not authorize a power toggle.
- MQTT disconnect is loss of evidence, not an OFF observation.
- A malformed explicit flag must not become ON through Python truthiness.
- Device/capability replies must notify every state subscriber, not only the media player.
- Missing replies must not manufacture OFF or preserve authorization across reconnects.

### Task 1: Normalize and route live power evidence

**Files:** `tv/power.py`, `tv/state.py`, `protocol/dispatcher.py`, `protocol/connection.py`, `tests/test_power_state.py` under the existing component/test directories.

**Interfaces:** `parse_power_state(data) -> str | None` returns a recognized state or no observation; the existing `_dispatch_state_update(data)` remains the shared consumer boundary.

- [x] Add failing tests for explicit power fields in info/capability replies, invalid flags, retained replay, and disconnect.
- [x] Implement the strict parser and route fresh info/capability observations.
- [x] Remove retained-state replay into power state; keep source snapshot diagnostic-only.
- [x] Run the power tests and full suite.

### Task 2: Query startup state, diagnose, and capture

**Files:** `media_player.py`, `diagnostics.py`, `binary_sensor.py`, `README.md`, `scripts/capture_power.py`, `tests/test_media_player.py`.

**Interfaces:** `query_initial_state(client)` sends the hardware-verified startup query once, tracked by `_state_query_sent` and reset on connect. Diagnostic fields show power provenance and the latest recognized power-related fields per response topic. No periodic metadata polling remains.

- [x] Replace assumed-state tests with tests that require unknown to stay unknown until an actual observation arrives.
- [x] Query startup state without changing power on timeout; make activity unknown when power is unknown.
- [x] Expose power provenance and raw power fields without authentication or personal data.
- [x] Add a read-only capture command for real ON/standby samples, using bundled app certificates.
- [x] Run `python3 -m unittest discover -s tests -v` and `git diff --check`; review changes.

## Progress

Research: state/MQTT implementations are identical in v0.1.8 and v0.1.9. Existing gettvinfo replies only update device metadata. `fake_sleep_state` exists in public implementations, but its polarity and availability on P0219 have not been verified; do not invent a mapping.

Independent review: one callback defect found: the legacy media metadata parser treats statetype-less replies as awake. Fixed all callback power branches to consume normalized client state, with regressions for OFF/invalid replies and repeated ON polls with an empty app list (RED observed before the fix).

Initial constraint: local network socket operations are prohibited by the execution environment. Subsequent hardware captures were run by the user; the application of the complete updated integration in HA remains unverified.

Verification: 53 tests passed after the review fix; `git diff --check` and Python 3.13 compilation passed. The capture CLI help was exercised. Changes remain uncommitted and unpublished.

Hardware evidence received from the user: P0219 returns no power/sleep fields in gettvinfo or capability. Live `tvsleep` at 00:06:11 UTC and `sourceswitch` at 00:06:22 UTC confirm transitions. No info replies were captured during the intervening standby period. These samples do not prove that any service response universally means ON; no inference from that response was added.

Next hardware probe: optional, one-shot `gettvstate` with payload `0`, via the capture script only. Capture direct and broadcast responses; stop on an authentication challenge without exporting its payload or submitting a PIN. Runtime state querying remains unchanged pending evidence.

Ruling after capture: removed the provisional 30-second metadata polling and its associated tests because the observed firmware exposes no power fields through these endpoints. Existing startup metadata reads remain. No response-based ON inference was introduced. Startup power detection remains unresolved pending the direct-state probe.

Second hardware capture: at 00:12:48 UTC, the one-shot `gettvstate` payload `0` was followed by retained `sourceswitch`, then a fresh non-retained `sourceswitch`. No authentication event was reported. This verifies the direct-state request on the configured hisenseservice route while HDMI is already active.

Implementation: request that exact payload once per connection only while state is unknown and no pairing futures exist. Reconnect resets the request latch. The existing fresh broadcast parser sets ON; neither the request nor the retained snapshot sets a value. Silence remains unknown. Added regression tests for startup capture replay, request de-duplication, reconnect, and pairing/unverified-route exclusions.

Final startup-query review: no blockers found; independent reviewer reran all 57 tests successfully. `git diff --check` passes. The integration is changed locally, not deployed to HA or published.
