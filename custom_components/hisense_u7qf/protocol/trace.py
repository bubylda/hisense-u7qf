"""Bounded sanitized MQTT telemetry."""

from __future__ import annotations

import base64
import json
import threading
import time
from collections import deque
from datetime import UTC, datetime
from typing import Any

SENSITIVE = {
    "deviceid",
    "uniquedeviceid",
    "password",
    "pin",
    "pincode",
    "token",
    "accesstoken",
    "refreshtoken",
    "access_token",
    "refresh_token",
    "username",
    "client_id",
    "mac",
    "mac_address",
    "serial_number",
    "private_key",
    "authorization",
}
# Only values in explicitly understood fields appear in ordinary exports.
SAFE_FIELDS = {
    "softwareVersion",
    "boardVersion",
    "vendorBrand",
    "chipplatform",
    "deviceType",
    "launcherVersion",
    "vidaaappVersion",
    "brand",
    "capability",
    "featurecode",
    "tuner_num",
    "is_signal",
    "is_lock",
    "hotel_mode",
    "playerFamilyName",
    "playerFamilyVersion",
    "menu_info",
    "items",
    "data",
    "menu_name",
    "menu_biz_id",
    "menu_value_type",
    "pic_setting_version",
    "menu_opts",
    "opts",
    "min_value",
    "max_value",
    "action",
    "statetype",
    "is_power_on",
    "sourceid",
    "sourcename",
    "displayname",
    "sourceName",
    "sourcelist",
    "volume",
    "volume_type",
    "volume_value",
    "is_mute",
    "muted",
    "applist",
    "appId",
    "appid",
    "appname",
    "appName",
    "name",
    "model",
    "model_name",
    "modelNumber",
    "firmware_version",
    "sw_version",
    "version",
    "manufacturer",
    "audio_output",
    "hdr_mode",
    "audio_format",
    "type",
    "supported",
    "error",
    "code",
    "menu_id",
    "menu_value",
    "value",
    "min",
    "max",
    "step",
    "options",
}


def sanitize(value: Any, private: bool = False) -> Any:
    if isinstance(value, dict):
        return {
            k: "[REDACTED]"
            if k.lower() in SENSITIVE or any(x in k.lower() for x in ("token", "password", "secret", "privatekey"))
            else sanitize(v, private)
            if private or k in SAFE_FIELDS
            else "[UNRECOGNIZED]"
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [sanitize(x, private) for x in value]
    return value


def safe_topic(topic: str) -> str:
    parts = topic.split("/")
    if len(parts) > 3 and parts[1:3] == ["remoteapp", "mobile"] and parts[3] != "broadcast":
        parts[3] = "[client]"
    elif len(parts) > 4 and parts[1:3] == ["remoteapp", "tv"]:
        parts[4] = "[client]"
    return "/".join(parts)


def decode(payload: bytes) -> tuple[Any, str]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return base64.b64encode(payload).decode("ascii"), "base64"
    try:
        return json.loads(text), "json"
    except (ValueError, RecursionError):
        return text, "text"


class TraceBuffer:
    def __init__(self, limit: int = 500, max_payload: int = 65536):
        self.events = deque(maxlen=limit)
        self.max_payload = max_payload
        self.lock = threading.RLock()
        self.sequence = 0

    def record(
        self,
        direction: str,
        topic: str,
        payload: bytes | str | None,
        qos: int = 0,
        retain: bool = False,
        private: bool = False,
        correlation: str | None = None,
    ) -> dict[str, Any]:
        raw = payload if isinstance(payload, bytes) else str(payload or "").encode()
        truncated = len(raw) > self.max_payload
        data, encoding = decode(raw[: self.max_payload])
        # Authentication traffic is never retained even in private/raw mode.
        auth = any(k in topic.lower() for k in ("authentication", "token", "vidaa_app_connect"))
        clean = (
            "[REDACTED]"
            if auth
            else sanitize(data, private)
            if encoding == "json"
            else data
            if private
            else "[RAW OMITTED]"
        )
        with self.lock:
            self.sequence += 1
            event = {
                "id": self.sequence,
                "time": datetime.now(UTC).isoformat(),
                "monotonic": time.monotonic(),
                "direction": direction,
                "topic": safe_topic(topic),
                "payload": clean,
                "encoding": encoding,
                "qos": qos,
                "retain": retain,
                "size": len(raw),
                "truncated": truncated,
                "correlation": correlation,
            }
            self.events.append(event)
            return dict(event)

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.lock:
            return list(self.events)[-max(1, min(limit, self.events.maxlen)) :]
