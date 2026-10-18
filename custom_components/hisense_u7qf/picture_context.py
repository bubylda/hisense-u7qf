"""Context boundaries for source-specific SDR/HDR/Dolby picture settings."""

import json

from .picture_readiness import picture_ready

HDR_BUSINESS_ID = "de.loewe.sl2.str.servicemode.videoinfo.hdrtype"
MODE_BUSINESS_ID = "de.loewe.sl2.i32.video.enum.picture.adjustment"


def picture_context(client):
    """Keep raw firmware values; unknown formats must not alias SDR."""
    values = {i.raw_data.get("menu_biz_id"): str(i.value) for i in list(client.picture_settings.values())}
    app = getattr(client, "_picture_active_app", None)
    return (
        app if isinstance(app, str) else str(client.current_source or client.current_source_id or "unknown"),
        values.get(HDR_BUSINESS_ID, "unknown").strip().lower(),
        values.get(MODE_BUSINESS_ID, "unknown"),
    )


def context_key(client):
    return json.dumps(picture_context(client), ensure_ascii=True, separators=(",", ":"))


def guarded_picture_command(client, expected, command, *args):
    if expected != (picture_context(client), client._picture_generation):
        raise ValueError("Picture context changed while command was queued")
    return command(*args)


def invalidate_picture(client):
    client.picture_settings.clear()
    client.brightness = client.backlight = client.contrast = client.picture_mode = None
    client._picture_generation += 1
    client._picture_snapshot.clear()


def validate_picture_write(client):
    """Re-read the active bank before writing; never replay across contexts."""
    if not picture_ready(client):
        raise ValueError("Picture profile is still settling after an input/HDR/mode change")
    before = (picture_context(client), client._picture_generation)
    if "unknown" in before[0] or client._pending_source or client._pending_power:
        raise ValueError("Picture context is unknown or a source/power transition is pending")
    client._picture_snapshot.clear()
    client.get_picture_settings()
    if not client._picture_snapshot.wait(3):
        raise ValueError("No fresh picture snapshot; command cancelled")
    if not picture_ready(client) or before != (picture_context(client), client._picture_generation):
        raise ValueError("Picture context changed; refresh the controls before trying again")


def live_observed_values(client, business_id):
    """Personal 50U7QF evidence, restricted to the actually tested input/bank."""
    if (
        getattr(getattr(client, "compatibility", None), "device_profile", None) == "50u7qf"
        and picture_context(client) == ("HDMI3", "sdr", "3")
        and client.picture_settings_version == "U4"
    ):
        return {
            "de.loewe.sl2.i32.video.enum.memc": {0, 1},
            "de.loewe.sl2.i32.video.autodimming.video": {0, 1, 2, 3},
        }.get(business_id, set())
    return set()


def catalog_control_items(client):
    """Expose ordinary picture controls, excluding status and service fields."""
    exclude = (
        "supported",
        "exist",
        "flag",
        "reset",
        "restore",
        "apply",
        "servicemode",
        "system.",
        "notify",
        "status",
        "feature",
        "image.still",
        "vga.",
        "3d",
        "wb.level",
        "color.tuner",
    )
    dedicated = {
        "de.loewe.sl2.i32.video.brightness",
        "de.loewe.sl2.i32.video.backlight",
        "de.loewe.sl2.i32.video.contrast",
        "de.loewe.sl2.i32.video.enum.memc",
        "de.loewe.sl2.i32.video.autodimming.video",
        MODE_BUSINESS_ID,
    }
    for item in list(client.picture_settings.values()):
        business = item.raw_data.get("menu_biz_id", "")
        text = (business + " " + item.name).lower()
        if (
            item.raw_data.get("menu_value_type") == "int"
            and business.startswith("de.loewe.sl2.i32.video.")
            and business not in dedicated
            and not any(word in text for word in exclude)
        ):
            yield item
