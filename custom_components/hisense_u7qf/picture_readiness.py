"""Wait for U4 to finish loading source/HDR/preset data before allowing writes."""

import threading
import time

SETTLE_SECONDS = 3.0


def picture_ready(client):
    deadline = getattr(client, "_picture_ready_after", 0.0)
    if isinstance(deadline, (int, float)) and time.monotonic() < deadline:
        return False
    # A fresh response can still be the transient no-signal bank during HDMI
    # negotiation. Do not edit it while waiting for the actual signal profile.
    if (getattr(client, "_u7qf_picture_guard", False) is True
            and getattr(client, "_picture_active_app", None) is None
            and str(client.current_source or "").upper().startswith("HDMI")):
        for item in list(client.picture_settings.values()):
            if item.name == "VideoFormatInfo" and not str(item.value or "").strip():
                return False
    return True


def defer_picture(client):
    """One delayed read, never a corrective write or automatic retry."""
    cancel_picture_refresh(client)
    client._picture_ready_after = time.monotonic() + SETTLE_SECONDS

    def refresh():
        with client._action_lock:
            if client._picture_refresh_timer is not timer:
                return
            client._picture_refresh_timer = None
            if client.connected:
                client.get_picture_settings()

    timer = threading.Timer(SETTLE_SECONDS, refresh)
    timer.daemon = True
    client._picture_refresh_timer = timer
    timer.start()


def cancel_picture_refresh(client):
    timer = getattr(client, "_picture_refresh_timer", None)
    if timer:
        timer.cancel()
    client._picture_refresh_timer = None
