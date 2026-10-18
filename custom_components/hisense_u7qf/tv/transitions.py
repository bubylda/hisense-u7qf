"""Bounded command confirmation without retries or corrective commands."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

_LOGGER = logging.getLogger(__name__)


def begin_transition(client: Any, kind: str, requested: Any, timeout: float) -> dict[str, Any]:
    pending = {"kind": kind, "requested": requested, "outcome": "pending", "started": time.monotonic()}
    setattr(client, f"_pending_{kind}", pending)
    client.last_command_outcome = pending
    _LOGGER.debug("%s transition requested: %s", kind, requested)

    def expire() -> None:
        with client._action_lock:
            if getattr(client, f"_pending_{kind}") is pending:
                if pending["outcome"] == "pending":
                    pending["outcome"] = "confirmation_timeout"
                setattr(client, f"_pending_{kind}", None)
                _LOGGER.debug("%s transition ended: %s", kind, pending["outcome"])
        with client._action_lock:
            if timer in client._transition_timers:
                client._transition_timers.remove(timer)

    timer = threading.Timer(timeout, expire)
    timer.daemon = True
    client._transition_timers.append(timer)
    timer.start()
    return pending


def confirm_transitions(client: Any, data: dict[str, Any]) -> None:
    if not hasattr(client, "_action_lock"):
        return
    with client._action_lock:
        power = client._pending_power
        observed_power = "on" if client.state in ("on", "screensaver") else client.state
        if power and observed_power == power["requested"]:
            power["outcome"] = "confirmed"
            client._pending_power = None
        source = client._pending_source
        if source:
            expected = source["requested"]
            # A volume/settings event must never confirm a source request.
            if ("sourceid" in data and str(data["sourceid"]) == expected["sourceid"]) or (
                "sourcename" in data and data["sourcename"] == expected["sourcename"]
            ):
                source["outcome"] = "confirmed"
                client._pending_source = None
