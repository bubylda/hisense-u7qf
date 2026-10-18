"""Evidence-backed scope, not a broad VIDAA compatibility claim."""

KNOWN_MODELS = {"50u7qf", "50a690fevs"}


def is_known_model(model):
    name = "".join(c for c in str(model or "").lower() if c.isalnum())
    if name.startswith("hisense"):
        name = name[len("hisense") :]
    return name in KNOWN_MODELS


def old_integration_active(hass, ip):
    """Do not run the old and the new controller against the same television."""
    entries = hass.config_entries.async_loaded_entries("hisense_vidaa")
    return isinstance(entries, list) and any(
        entry.domain == "hisense_vidaa" and entry.data.get("ip_address") == ip for entry in entries
    )


async def async_refresh_identity(hass, entry, client):
    """Repair older entries that saved the generic UPnP renderer name."""
    import contextlib

    with contextlib.suppress(Exception):
        fingerprint = await hass.async_add_executor_job(client.get_device_fingerprint, 1.5)
        data = dict(entry.data)
        for key, field in (("model_name", "model"), ("firmware_version", "sw_version")):
            value = fingerprint.get(key)
            if isinstance(value, str) and value.strip() and value != "Renderer":
                data[field] = value.strip()
        if is_known_model(data.get("model")):
            data["experimental_model"] = False
        if data != dict(entry.data):
            hass.config_entries.async_update_entry(entry, data=data)
