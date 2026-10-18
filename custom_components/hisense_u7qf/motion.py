"""Observed MEMC values and optional owner-provided labels for VIDAA firmware."""

from __future__ import annotations

from typing import Any

MOTION_BUSINESS_ID = "de.loewe.sl2.i32.video.enum.memc"
MOTION_VALUES_KEY = "motion_smoothing_observed_values"
MOTION_LABELS_KEY = "motion_smoothing_labels"


def motion_item(client: Any, business_id: str = MOTION_BUSINESS_ID):
    for item in list(client.picture_settings.values()):
        if item.raw_data.get("menu_biz_id") == business_id and item.raw_data.get("menu_value_type") == "int":
            try:
                int(item.value)
            except (TypeError, ValueError):
                return None
            return item
    return None


def labels_from_options(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or len(value) > 64:
        raise ValueError("MEMC labels must be an object with at most 64 entries")
    labels = {}
    for code, label in value.items():
        normalized = str(int(code))
        if not isinstance(label, str) or not label.strip() or len(label) > 80:
            raise ValueError("Each MEMC label must be a non-empty string of at most 80 characters")
        labels[normalized] = label.strip()
    if len(set(labels.values())) != len(labels):
        raise ValueError("MEMC labels must be unique")
    return labels
