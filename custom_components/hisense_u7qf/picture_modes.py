"""Resolve firmware-provided picture labels without guessing numeric enums."""

from .firmware_u4 import HDR_FLAG_ID, SIGNAL_PROFILES, integer_value, model_picture_modes, uses_u4_model_table
from .picture_context import MODE_BUSINESS_ID, picture_context


def mode_bank(client):
    source, signal, _mode = picture_context(client)
    if uses_u4_model_table(client):
        signal = SIGNAL_PROFILES[integer_value(client, HDR_FLAG_ID)]
    return source, signal


def mode_item(client):
    return next(
        (i for i in list(client.picture_settings.values()) if i.raw_data.get("menu_biz_id") == MODE_BUSINESS_ID), None
    )


def firmware_mode_choices(client):
    """Use explicit value/label pairs only; array positions are not enum codes."""
    item = mode_item(client)
    if item is None:
        return {}
    raw = item.raw_data
    options = raw.get("menu_opts") or raw.get("options") or raw.get("opts") or []
    if not options:
        return model_picture_modes(client)
    if not isinstance(options, list):
        return {}
    result = {}
    codes = set()
    for option in options:
        if (
            not isinstance(option, dict)
            or option.get("available", True) is False
            or option.get("enabled", True) is False
        ):
            continue
        label = option.get("name") or option.get("label")
        code = option.get("value", option.get("code"))
        if not isinstance(label, str) or not label.strip() or isinstance(code, bool):
            return {}
        try:
            if not isinstance(code, (int, str)):
                return {}
            value = int(code)
        except (TypeError, ValueError):
            return {}
        if label.strip() in result or value in codes:
            return {}  # ambiguous metadata must not authorize a write
        result[label.strip()] = value
        codes.add(value)
    return result


def current_mode_label(client):
    item = mode_item(client)
    if item is None:
        return None
    try:
        code = int(item.value)
    except (ValueError, TypeError):
        return None
    choices = firmware_mode_choices(client)
    return next((label for label, value in choices.items() if value == code), None)
