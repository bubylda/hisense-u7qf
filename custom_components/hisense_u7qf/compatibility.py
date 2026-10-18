"""Model policy shared by HA entities and the protocol actions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


def runtime_options(options: dict[str, Any] | None, model: str | None) -> dict[str, Any]:
    """Keep only U7QF user choices; protocol policy is fixed in this domain."""
    allowed = {"enable_wol", "include_apps_in_sources", "enable_cec_names", "hide_tuner_sources", "assume_screen_state"}
    result = {k: v for k, v in (options or {}).items() if k in allowed}
    result.setdefault("assume_screen_state", False)
    result.update(
        device_profile="50u7qf",
        power_on_strategy="wol_only",
        power_off_strategy="mqtt_power",
        source_switch_strategy="mqtt_id_only",
        mqtt_trace=False,
        extended_discovery=False,
        enable_research_tools=False,
        enable_remote=True,
        enable_picture_controls=True,
        enable_notify=False,
        enable_sound_controls=False,
        enable_audio_only=False,
    )
    return result


@dataclass(frozen=True)
class CompatibilityOptions:
    device_profile: str = "50u7qf"
    power_on_strategy: str = "wol_only"
    power_off_strategy: str = "mqtt_power"
    source_switch_strategy: str = "mqtt_id_only"
    hide_tuner_sources: bool = True
    mqtt_trace: bool = False
    extended_discovery: bool = False
    enable_research_tools: bool = False

    @classmethod
    def from_options(cls, options: dict[str, Any] | None = None) -> CompatibilityOptions:
        values = dict(options or {})
        defaults = asdict(cls())
        if values.get("device_profile") == "generic":
            defaults.update(
                power_on_strategy="upstream_default",
                power_off_strategy="upstream_default",
                source_switch_strategy="upstream_default",
                hide_tuner_sources=False,
            )
        defaults.update({k: v for k, v in values.items() if k in defaults})
        choices = {
            "device_profile": {"50u7qf", "generic"},
            "power_on_strategy": {"wol_only", "upstream_default"},
            "power_off_strategy": {"mqtt_power", "upstream_default"},
            "source_switch_strategy": {"disabled", "mqtt_id_only", "mqtt_id_name", "remote_keys", "upstream_default"},
        }
        for key, allowed in choices.items():
            if defaults[key] not in allowed:
                raise ValueError(f"Invalid {key}")
        return cls(**defaults)


def policy(client: Any) -> CompatibilityOptions:
    return getattr(client, "compatibility", CompatibilityOptions())


def is_tuner(source: dict[str, Any]) -> bool:
    """Match exact protocol identifiers/names; never use substring guessing."""
    tuner = {"tv", "dtv", "atv", "live tv", "livetv", "antenna", "tuner"}
    return any(str(source.get(k, "")).strip().lower() in tuner for k in ("sourceid", "sourcename", "type"))


def selectable_sources(client: Any) -> list[dict[str, Any]]:
    return [
        s for s in client.sources if isinstance(s, dict) and not (policy(client).hide_tuner_sources and is_tuner(s))
    ]
