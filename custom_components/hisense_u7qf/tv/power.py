"""Recognize explicit power observations; never infer power from connectivity."""

from __future__ import annotations

from typing import Any


POWER_FIELDS = ("statetype", "is_power_on", "fake_sleep", "fake_sleep_state")
STATE_EVENTS = {
    "off": "off",
    "fake_sleep_0": "off",
    "fake_sleep_1": "fake_sleep_1",
    "screen_saver": "screensaver",
    "screensaver": "screensaver",
    "on": "on",
    "remote_launcher": "on",
    "remote_setting": "on",
    "sourceswitch": "on",
    "app": "on",
    "livetv": "on",
}


def parse_power_state(data: Any) -> str | None:
    """Return an observation, unknown for invalid flags, or None for no evidence."""
    if not isinstance(data, dict) or data.get("_retained", False):
        return None
    event = STATE_EVENTS.get(str(data.get("statetype", "")).lower())
    if "is_power_on" not in data:
        return event
    value = data["is_power_on"]
    if type(value) not in (bool, int, str) or value not in (0, 1, "0", "1"):
        return "unknown"
    observed = "on" if value in (1, "1") else "off"
    if event is not None and (event != "off") != (observed == "on"):
        return "unknown"
    # fake_sleep_state is collected, but has no verified polarity on P0219.
    # In particular, do not borrow an enum mapping from a different model.
    return event or observed
