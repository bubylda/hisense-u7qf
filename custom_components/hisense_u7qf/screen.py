"""Audio Only actions without pretending the TV reports screen state."""

import threading
import time

from .picture_context import picture_context


def screen_off_blockers(client, model=None):
    """Expose the exact failed guards instead of blaming the HDMI input."""
    from .model import is_known_model

    reasons = []
    if model is not None and not is_known_model(model):
        reasons.append(f"unrecognized model={model!r}")
    if not client.connected:
        reasons.append("MQTT disconnected")
    if not client.is_on:
        reasons.append(f"power state={client.state!r}")
    if not screen_menu_source(client):
        reasons.append(f"quick-menu layout is not known for source={picture_context(client)[0]!r}")
    if client._pending_source or client._pending_power:
        reasons.append("source/power transition pending")
    return reasons


def screen_off_error(client, model=None):
    return "Audio Only unavailable: " + "; ".join(screen_off_blockers(client, model))


def screen_menu_source(client):
    """N0712 uses the same menu for ordinary external inputs, regardless of signal.

    Tuner menus depend on channels/PVR/HbbTV; Home/apps are separate contexts.
    """
    source = picture_context(client)[0].upper()
    return source.startswith("HDMI") or source in {"AV", "AVS", "COMPONENT", "VGA", "SCART"}


def can_screen_off(client):
    return (
        client.connected
        and client.is_on
        and screen_menu_source(client)
        and not client._pending_source
        and not client._pending_power
    )


def screen_action(client, off):
    """Serialize the visually confirmed menu path; EXIT always remains recoverable."""
    if not client._screen_action_lock.acquire(blocking=False):
        raise ValueError("A screen action is already running")
    try:
        with client._navigation_lock:
            if not client.connected:
                raise ValueError("TV MQTT connection is not available")
            if off and not can_screen_off(client):
                raise ValueError(screen_off_error(client))
            source = picture_context(client)[0]
            # EXIT wakes a dark panel and dismisses an existing menu. Without
            # this, a repeated MENU could be consumed only as a wake-up key.
            keys = ("KEY_EXIT", "KEY_MENU", "KEY_DOWN", "KEY_OK") if off else ("KEY_EXIT", "KEY_EXIT")
            try:
                for key in keys:
                    # Serialize our commands while allowing incoming TV state
                    # to be processed between keys (including stock-remote use).
                    with client._action_lock:
                        if not client.connected:
                            raise ValueError("TV disconnected during screen action")
                        if off and (picture_context(client)[0] != source or client._pending_source or client._pending_power):
                            raise ValueError("TV context changed during screen action")
                        client.send_key(key)
                    time.sleep(1 if off else 0.5)
            except Exception:
                # Close an incomplete menu, never retry the whole sequence.
                if off and client.connected:
                    client.send_key("KEY_EXIT")
                raise
            # No is_on/screen/audio-only value is changed optimistically.
    finally:
        client._screen_action_lock.release()


def init_screen_actions(client):
    client._screen_action_lock = threading.Lock()
    client._navigation_lock = threading.RLock()
