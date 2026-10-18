"""50U7QF U4 enums recovered from N0712 frontend, not array-index guesses.

Mappings are from N0712; SDR controls were verified on 50U7QF/P0219.
"""

MODE_ID = "de.loewe.sl2.i32.video.enum.picture.adjustment"
HDR_FLAG_ID = "de.loewe.sl2.i32.video.hdr.flag"
MOTION_ID = "de.loewe.sl2.i32.video.enum.memc"
DIMMING_ID = "de.loewe.sl2.i32.video.autodimming.video"

PICTURE_MODES = {
    0: {"Standard": 1, "Cinema Day": 3, "Cinema Night": 2, "Dynamic": 0, "Sports": 5},
    1: {"HDR Standard": 1, "HDR Day": 3, "HDR Night": 2, "HDR Dynamic": 0, "HDR Sports": 5},
    2: {"Dolby Vision Bright": 3, "Dolby Vision Dark": 2, "Dolby Vision Custom": 1},
    3: {"HDR10+ Standard": 1, "HDR10+ Cinema": 3, "HDR10+ Dynamic": 0},
}
SIGNAL_PROFILES = {0: "SDR", 1: "HDR", 2: "Dolby Vision", 3: "HDR10+"}


def business_item(client, business_id):
    return next(
        (i for i in list(client.picture_settings.values()) if i.raw_data.get("menu_biz_id") == business_id), None
    )


def integer_value(client, business_id):
    item = business_item(client, business_id)
    if item is None or item.raw_data.get("menu_value_type") != "int":
        return None
    try:
        return int(item.value)
    except (TypeError, ValueError):
        return None


def uses_u4_model_table(client):
    return (
        getattr(getattr(client, "compatibility", None), "device_profile", None) == "50u7qf"
        and getattr(client, "picture_settings_version", None) == "U4"
        and integer_value(client, MODE_ID) is not None
        and integer_value(client, HDR_FLAG_ID) in PICTURE_MODES
    )


def model_picture_modes(client):
    if not uses_u4_model_table(client):
        return {}
    # Enhanced/ACR is an AI feature switch, not an enum value. It is excluded.
    return dict(PICTURE_MODES[integer_value(client, HDR_FLAG_ID)])


def model_setting_choices(client, business_id):
    if not uses_u4_model_table(client) or integer_value(client, business_id) is None:
        return {}
    if business_id == DIMMING_ID:
        support = integer_value(client, "de.loewe.sl2.i32.video.local.dimming.supported")
        if support == 1:
            return {"Off": 0, "Low": 1, "Medium": 2, "High": 3}
        if support == 2:
            return {"Off": 0, "On": 1}
        if support == 3:
            return {"Off": 0, "Energy Saving": 4, "Low": 1, "Medium": 2, "High": 3}
        return {}  # support=0 is Dynamic Backlight, a different parameter
    if business_id == MOTION_ID:
        support = integer_value(client, "de.loewe.sl2.i32.video.smooth.motion.supported")
        if support is None or not support & 128 or not support & 1:
            return {}
        names = [
            ("Off", 0, 255),
            ("Smooth", 5, 32),
            ("Standard", 4, 16),
            ("Clear", 3, 8),
            ("Film", 2, 4),
            ("Custom", 1, 2),
        ]
        # N0712 masks the five fixed choices when bit 128 is set. Custom's
        # visibility stays at its default in the frontend's t < 5 loop.
        return {name: value for name, value, mask in names if name == "Custom" or not support & 128 or support & mask}
    return {}
