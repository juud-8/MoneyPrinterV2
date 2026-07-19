"""Honest Studio-metric ingestion plan (CTR / retention / impressions).

Public YouTube Data API fills views/likes/comments only. CTR, impressions,
and average percentage viewed require YouTube Analytics API (OAuth) or a
manual Studio paste. This module:

- Defines typed sources so proxies are never silently treated as ground truth
- Provides validation helpers for analytics.json updates
- Refuses fabricated / estimated values unless ``source`` is explicitly
  labeled as a proxy (and proxies stay out of strategy ranking by default)

See ``metric_is_usable_for_strategy`` and ``ingestion_plan``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence


class MetricSource(str, Enum):
    """Where a Studio-private metric came from."""

    MISSING = "missing"
    MANUAL_STUDIO = "manual_studio"
    YOUTUBE_ANALYTICS_API = "youtube_analytics_api"
    PROXY_ESTIMATE = "proxy_estimate"  # never use for strategy by default


# Fields that the public Data API cannot populate.
STUDIO_PRIVATE_FIELDS = (
    "ctr",
    "impressions",
    "engaged_views",
    "avg_view_duration",
    "avg_view_pct",
)


@dataclass(frozen=True)
class StudioMetricValue:
    field: str
    value: float | int | None
    source: MetricSource
    unit: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "field", str(self.field).strip())
        if self.field not in STUDIO_PRIVATE_FIELDS:
            raise ValueError(
                f"Unsupported studio field {self.field!r}. "
                f"Allowed: {', '.join(STUDIO_PRIVATE_FIELDS)}"
            )
        object.__setattr__(self, "source", MetricSource(self.source))
        if self.value is not None:
            object.__setattr__(self, "value", _validate_value(self.field, self.value))

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "value": self.value,
            "source": self.source.value,
            "unit": self.unit,
        }


def _validate_value(field: str, value: float | int) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number")
    if field == "ctr":
        # Store CTR as 0-100 percent (Studio UI), not 0-1 fraction.
        if not 0.0 <= float(value) <= 100.0:
            raise ValueError(f"ctr must be 0-100 percent, got {value}")
        return float(value)
    if field == "avg_view_pct":
        if not 0.0 <= float(value) <= 100.0:
            raise ValueError(f"avg_view_pct must be 0-100, got {value}")
        return float(value)
    if field in {"impressions", "engaged_views"}:
        if int(value) != value or value < 0:
            raise ValueError(f"{field} must be a non-negative integer")
        return int(value)
    if field == "avg_view_duration":
        if float(value) < 0:
            raise ValueError("avg_view_duration must be >= 0 seconds")
        return float(value)
    return value


def metric_is_usable_for_strategy(
    metric: StudioMetricValue | Mapping[str, Any],
) -> bool:
    """True only for non-missing, non-proxy values with a real number."""
    if isinstance(metric, StudioMetricValue):
        source = metric.source
        value = metric.value
    else:
        try:
            source = MetricSource(str(metric.get("source") or "missing"))
        except ValueError:
            return False
        value = metric.get("value")
    if value is None:
        return False
    return source in {
        MetricSource.MANUAL_STUDIO,
        MetricSource.YOUTUBE_ANALYTICS_API,
    }


def missing_studio_fields(entry: Mapping[str, Any] | None) -> list[str]:
    """Return private metric field names that are still unset on a video entry."""
    entry = entry or {}
    missing: list[str] = []
    meta = entry.get("metric_sources")
    meta_map = meta if isinstance(meta, Mapping) else {}
    for field in STUDIO_PRIVATE_FIELDS:
        if entry.get(field) is None:
            missing.append(field)
            continue
        src = str(meta_map.get(field) or "").strip().lower()
        if src == MetricSource.PROXY_ESTIMATE.value:
            missing.append(field)
    return missing


def build_metric_sources_update(
    metrics: Sequence[StudioMetricValue],
) -> dict[str, str]:
    """Map field → source.value for persistence beside numeric fields."""
    return {m.field: m.source.value for m in metrics}


def normalize_metrics(
    metrics: Sequence[StudioMetricValue | Mapping[str, Any]],
) -> list[StudioMetricValue]:
    result: list[StudioMetricValue] = []
    for item in metrics:
        if isinstance(item, StudioMetricValue):
            result.append(item)
            continue
        result.append(
            StudioMetricValue(
                field=str(item["field"]),
                value=item.get("value"),
                source=MetricSource(str(item.get("source") or "missing")),
                unit=str(item.get("unit") or ""),
            )
        )
    return result


def ingestion_plan() -> dict[str, Any]:
    """Machine-readable plan for closing the analytics loop without proxies."""
    return {
        "schema_version": 1,
        "public_api_fills": ["views", "likes", "comments"],
        "studio_private_fields": list(STUDIO_PRIVATE_FIELDS),
        "allowed_sources_for_strategy": [
            MetricSource.MANUAL_STUDIO.value,
            MetricSource.YOUTUBE_ANALYTICS_API.value,
        ],
        "forbidden_for_strategy": [
            MetricSource.MISSING.value,
            MetricSource.PROXY_ESTIMATE.value,
        ],
        "phases": [
            {
                "id": "manual_ctr_retention",
                "description": (
                    "Operator pastes Studio CTR and avg % viewed via CLI/WebUI; "
                    "source=manual_studio."
                ),
                "status": "implemented",
            },
            {
                "id": "youtube_analytics_api",
                "description": (
                    "OAuth YouTube Analytics API for impressions/CTR/APV; "
                    "source=youtube_analytics_api. Not implemented yet."
                ),
                "status": "planned",
            },
            {
                "id": "strategy_gate",
                "description": (
                    "performance_insights only ranks on metric_is_usable_for_strategy."
                ),
                "status": "implemented_helpers",
            },
        ],
    }
