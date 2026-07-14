"""Provider adapters and collection controls for trend intelligence.

Live calls are made only when a provider is explicitly enabled and the caller
does not request a dry run. X and Google Trends intentionally remain disabled
stubs in the MVP.
"""

from __future__ import annotations

import csv
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import quote

import requests

from trend_models import ProviderError, ProviderResult, TrendRequest, TrendSignal, utc_now
from trend_store import TrendStore


JsonFetcher = Callable[[str, dict[str, Any], dict[str, str], float], dict[str, Any]]


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def fetch_json_with_retries(
    url: str,
    params: dict[str, Any],
    headers: dict[str, str],
    timeout: float,
    *,
    attempts: int = 3,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=timeout)
            if response.status_code == 429 and attempt + 1 < attempts:
                retry_after = min(float(response.headers.get("Retry-After", "1") or 1), 5.0)
                time.sleep(max(retry_after, 0))
                continue
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else {}
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.25 * (2**attempt))
    assert last_error is not None
    raise last_error


class TrendProvider(Protocol):
    name: str
    enabled: bool
    cache_ttl_minutes: int
    estimated_max_cost_usd: float

    def collect(self, request: TrendRequest) -> ProviderResult:
        ...


@dataclass
class ProviderSettings:
    enabled: bool = False
    timeout_seconds: float = 12.0
    cache_ttl_minutes: int = 180
    daily_cost_limit_usd: float = 0.0
    monthly_cost_limit_usd: float = 0.0
    daily_request_limit: int = 0
    api_key: str = ""
    user_agent: str = "MoneyPrinterV2/2.0 (trend intelligence; local operator)"


class BaseProvider:
    name = "base"
    estimated_max_cost_usd = 0.0

    def __init__(self, settings: ProviderSettings | None = None, fetch_json: JsonFetcher = fetch_json_with_retries):
        self.settings = settings or ProviderSettings()
        self.enabled = self.settings.enabled
        self.cache_ttl_minutes = self.settings.cache_ttl_minutes
        self.fetch_json = fetch_json

    def error_result(self, code: str, message: str, *, retryable: bool = False) -> ProviderResult:
        return ProviderResult(
            provider=self.name,
            signals=[],
            errors=[ProviderError(code=code, message=message, retryable=retryable)],
            cache_hit=False,
            request_count=0,
            resource_count=0,
            estimated_cost_usd=0,
            actual_cost_usd=None,
            collected_at=utc_now(),
        )

    def estimated_max_requests(self, request: TrendRequest) -> int:
        return min(len(request.terms), request.max_results)


class ManualProvider(BaseProvider):
    name = "manual"

    def __init__(self, path: str):
        super().__init__(ProviderSettings(enabled=True, cache_ttl_minutes=0))
        self.path = Path(path)

    def collect(self, request: TrendRequest) -> ProviderResult:
        try:
            if self.path.suffix.lower() == ".csv":
                with self.path.open(encoding="utf-8-sig", newline="") as file:
                    rows = list(csv.DictReader(file))
                payloads = [self._csv_payload(row, request) for row in rows]
            else:
                with self.path.open(encoding="utf-8") as file:
                    raw = json.load(file)
                payloads = raw.get("signals", []) if isinstance(raw, dict) else raw
            signals = [TrendSignal.from_dict(item) for item in payloads]
            return ProviderResult(
                provider=self.name,
                signals=signals[: request.max_results],
                errors=[],
                cache_hit=False,
                request_count=0,
                resource_count=min(len(signals), request.max_results),
                estimated_cost_usd=0,
                actual_cost_usd=0,
                collected_at=request.requested_at,
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return self.error_result("manual_import_failed", str(exc))

    def estimated_max_requests(self, request: TrendRequest) -> int:
        return 0

    @staticmethod
    def _csv_payload(row: dict[str, str], request: TrendRequest) -> dict[str, Any]:
        def items(name: str) -> list[str]:
            return [item.strip() for item in (row.get(name) or "").split("|") if item.strip()]

        def number(name: str):
            value = (row.get(name) or "").strip()
            return float(value) if value else None

        return {
            "provider": "manual",
            "provider_signal_id": row.get("provider_signal_id") or hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()[:16],
            "collected_at": row.get("collected_at") or request.requested_at,
            "term": row.get("term"),
            "normalized_entity": row.get("normalized_entity") or row.get("term"),
            "aliases": items("aliases"),
            "entity_type": row.get("entity_type") or "unknown",
            "geography": row.get("geography") or request.geographies[0],
            "language": row.get("language") or request.languages[0],
            "window_hours": number("window_hours") or request.window_hours,
            "rank": number("rank"),
            "volume": number("volume"),
            "volume_is_absolute": (row.get("volume_is_absolute") or "").lower() in {"true", "1", "yes"},
            "velocity": number("velocity"),
            "related_terms": items("related_terms"),
            "source_urls": items("source_urls"),
            "metric_type": row.get("metric_type") or "manual_import",
            "expires_at": row.get("expires_at") or "",
            "raw_metadata": {"import": "csv"},
        }


class GdeltProvider(BaseProvider):
    name = "gdelt"
    endpoint = "https://api.gdeltproject.org/api/v2/doc/doc"

    def collect(self, request: TrendRequest) -> ProviderResult:
        if not self.enabled:
            return self.error_result("disabled", "GDELT provider is disabled")
        if request.dry_run:
            return self.error_result("dry_run", "Dry run: no GDELT request made")
        if not request.terms:
            return self.error_result("missing_terms", "GDELT confirmation requires candidate terms")
        signals: list[TrendSignal] = []
        errors: list[ProviderError] = []
        requests_made = 0
        for term in request.terms[: request.max_results]:
            try:
                requests_made += 1
                payload = self.fetch_json(
                    self.endpoint,
                    {"query": term, "mode": "ArtList", "format": "json", "maxrecords": 25, "timespan": f"{int(request.window_hours)}h"},
                    {"User-Agent": self.settings.user_agent},
                    self.settings.timeout_seconds,
                )
                articles = payload.get("articles") or []
                if not isinstance(articles, list):
                    articles = []
                domains = {str(item.get("domain") or "").lower() for item in articles if item.get("domain")}
                urls = [str(item.get("url")) for item in articles if item.get("url")][:10]
                signals.append(
                    TrendSignal.from_dict(
                        {
                            "provider": self.name,
                            "provider_signal_id": hashlib.sha256(f"{term}|{request.requested_at}".encode()).hexdigest()[:20],
                            "collected_at": request.requested_at,
                            "term": term,
                            "normalized_entity": term,
                            "aliases": [],
                            "entity_type": "news_entity",
                            "geography": request.geographies[0],
                            "language": request.languages[0],
                            "window_hours": request.window_hours,
                            "volume": len(articles),
                            "volume_is_absolute": False,
                            "velocity": None,
                            "related_terms": [],
                            "source_urls": urls,
                            "metric_type": "gdelt_article_matches",
                            "raw_metadata": {"unique_domains": len(domains), "article_count": len(articles)},
                        }
                    )
                )
            except (requests.RequestException, ValueError, TypeError) as exc:
                errors.append(ProviderError("provider_request_failed", f"{term}: {exc}", True))
        return ProviderResult(self.name, signals, errors, False, requests_made, len(signals), 0, 0, request.requested_at)


class WikimediaProvider(BaseProvider):
    name = "wikimedia"
    endpoint_template = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/{project}/all-access/user/{article}/daily/{start}/{end}"

    def collect(self, request: TrendRequest) -> ProviderResult:
        if not self.enabled:
            return self.error_result("disabled", "Wikimedia provider is disabled")
        if request.dry_run:
            return self.error_result("dry_run", "Dry run: no Wikimedia request made")
        signals: list[TrendSignal] = []
        errors: list[ProviderError] = []
        end = _parse_time(request.requested_at).date() - timedelta(days=1)
        start = end - timedelta(days=13)
        for term in request.terms[: request.max_results]:
            try:
                article = quote(term.replace(" ", "_"), safe="")
                language = request.languages[0] if request.languages else "en"
                url = self.endpoint_template.format(
                    project=f"{language}.wikipedia.org",
                    article=article,
                    start=start.strftime("%Y%m%d"),
                    end=end.strftime("%Y%m%d"),
                )
                payload = self.fetch_json(url, {}, {"User-Agent": self.settings.user_agent}, self.settings.timeout_seconds)
                views = [int(item.get("views") or 0) for item in payload.get("items") or []]
                if not views:
                    continue
                recent = sum(views[-2:]) / min(2, len(views))
                baseline_values = views[:-2] or views
                baseline = sum(baseline_values) / len(baseline_values)
                velocity = min(100.0, max(0.0, ((recent / baseline) - 1) * 50)) if baseline else None
                signals.append(
                    TrendSignal.from_dict(
                        {
                            "provider": self.name,
                            "provider_signal_id": f"{language}:{term}:{end.isoformat()}",
                            "collected_at": request.requested_at,
                            "term": term,
                            "normalized_entity": term,
                            "entity_type": "wikimedia_article",
                            "geography": request.geographies[0],
                            "language": language,
                            "window_hours": 48,
                            "volume": sum(views[-2:]),
                            "volume_is_absolute": True,
                            "velocity": velocity,
                            "source_urls": [f"https://{language}.wikipedia.org/wiki/{article}"],
                            "metric_type": "wikimedia_pageviews",
                            "raw_metadata": {"baseline_daily_views": baseline, "recent_daily_views": recent},
                        }
                    )
                )
            except (requests.RequestException, ValueError, TypeError) as exc:
                errors.append(ProviderError("provider_request_failed", f"{term}: {exc}", True))
        return ProviderResult(self.name, signals, errors, False, len(request.terms[: request.max_results]), len(signals), 0, 0, request.requested_at)


class YouTubeTrendProvider(BaseProvider):
    name = "youtube"
    search_endpoint = "https://www.googleapis.com/youtube/v3/search"
    videos_endpoint = "https://www.googleapis.com/youtube/v3/videos"

    def estimated_max_requests(self, request: TrendRequest) -> int:
        return min(len(request.terms), request.max_results) * 2

    def collect(self, request: TrendRequest) -> ProviderResult:
        if not self.enabled:
            return self.error_result("disabled", "YouTube trend provider is disabled")
        if request.dry_run:
            return self.error_result("dry_run", "Dry run: no YouTube request made")
        if not self.settings.api_key:
            return self.error_result("missing_credentials", "Dedicated YouTube API key is required")
        signals: list[TrendSignal] = []
        errors: list[ProviderError] = []
        request_count = 0
        for term in request.terms[: request.max_results]:
            try:
                request_count += 1
                search = self.fetch_json(
                    self.search_endpoint,
                    {
                        "part": "snippet",
                        "type": "video",
                        "q": term,
                        "publishedAfter": _iso(_parse_time(request.requested_at) - timedelta(hours=request.window_hours)),
                        "maxResults": min(request.max_results, 25),
                        "order": "viewCount",
                        "regionCode": request.geographies[0] if len(request.geographies[0]) == 2 else "US",
                        "relevanceLanguage": request.languages[0],
                        "key": self.settings.api_key,
                    },
                    {},
                    self.settings.timeout_seconds,
                )
                ids = [str((item.get("id") or {}).get("videoId") or "") for item in search.get("items") or []]
                ids = [value for value in ids if value]
                stats_items: list[dict] = []
                if ids:
                    request_count += 1
                    stats = self.fetch_json(
                        self.videos_endpoint,
                        {"part": "snippet,statistics", "id": ",".join(ids), "key": self.settings.api_key},
                        {},
                        self.settings.timeout_seconds,
                    )
                    stats_items = stats.get("items") or []
                vph_values = []
                total_views = 0
                for item in stats_items:
                    published = _parse_time((item.get("snippet") or {}).get("publishedAt") or request.requested_at)
                    hours = max((_parse_time(request.requested_at) - published).total_seconds() / 3600, 1)
                    views = int((item.get("statistics") or {}).get("viewCount") or 0)
                    total_views += views
                    vph_values.append(views / hours)
                signals.append(
                    TrendSignal.from_dict(
                        {
                            "provider": self.name,
                            "provider_signal_id": hashlib.sha256(f"{term}|{request.requested_at}".encode()).hexdigest()[:20],
                            "collected_at": request.requested_at,
                            "term": term,
                            "normalized_entity": term,
                            "entity_type": "youtube_query",
                            "geography": request.geographies[0],
                            "language": request.languages[0],
                            "window_hours": request.window_hours,
                            "volume": len(stats_items),
                            "volume_is_absolute": False,
                            "velocity": None,
                            "source_urls": [f"https://www.youtube.com/watch?v={item.get('id')}" for item in stats_items[:10]],
                            "metric_type": "youtube_recent_video_count",
                            "raw_metadata": {
                                "result_count": len(stats_items),
                                "total_public_views": total_views,
                                "median_views_per_hour_proxy": sorted(vph_values)[len(vph_values) // 2] if vph_values else None,
                                "quota_calls": 2 if ids else 1,
                            },
                        }
                    )
                )
            except (requests.RequestException, ValueError, TypeError) as exc:
                errors.append(ProviderError("provider_request_failed", f"{term}: {exc}", True))
        return ProviderResult(self.name, signals, errors, False, request_count, len(signals), 0, 0, request.requested_at)


class XProviderStub(BaseProvider):
    name = "x"

    def collect(self, request: TrendRequest) -> ProviderResult:
        return self.error_result("mvp_stub", "X provider is a disabled fixture-only stub in the MVP")


class GoogleTrendsProviderStub(BaseProvider):
    name = "google_trends"

    def collect(self, request: TrendRequest) -> ProviderResult:
        return self.error_result("mvp_stub", "Google Trends requires official API access; use manual import in the MVP")


class CollectionCoordinator:
    def __init__(self, store: TrendStore):
        self.store = store

    @staticmethod
    def _cache_key(provider: TrendProvider, request: TrendRequest) -> str:
        payload = {
            "provider": provider.name,
            "brand_id": request.brand_id,
            "terms": sorted(request.terms),
            "geographies": sorted(request.geographies),
            "languages": sorted(request.languages),
            "window_hours": request.window_hours,
            "max_results": request.max_results,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def collect(self, provider: TrendProvider, request: TrendRequest, settings: ProviderSettings) -> ProviderResult:
        if not provider.enabled:
            return ProviderResult(provider.name, [], [ProviderError("disabled", f"{provider.name} provider is disabled")], False, 0, 0, 0, None, request.requested_at)
        key = self._cache_key(provider, request)
        cached = self.store.get_cache(key, request.requested_at)
        if cached:
            result = ProviderResult.from_dict(cached)
            return ProviderResult(result.provider, result.signals, result.errors, True, 0, result.resource_count, 0, 0, request.requested_at)

        now = _parse_time(request.requested_at)
        daily_since = _iso(now - timedelta(days=1))
        monthly_since = _iso(now - timedelta(days=30))
        daily_spend = self.store.usage_cost_since(provider.name, daily_since)
        monthly_spend = self.store.usage_cost_since(provider.name, monthly_since)
        daily_requests = self.store.usage_requests_since(provider.name, daily_since)
        estimate = max(float(provider.estimated_max_cost_usd), 0)
        request_estimator = getattr(provider, "estimated_max_requests", None)
        estimated_requests = int(request_estimator(request)) if request_estimator else 0
        if settings.daily_cost_limit_usd and daily_spend + estimate > settings.daily_cost_limit_usd:
            return ProviderResult(provider.name, [], [ProviderError("daily_budget_exceeded", "Provider daily cost ceiling reached")], False, 0, 0, 0, None, request.requested_at)
        if settings.monthly_cost_limit_usd and monthly_spend + estimate > settings.monthly_cost_limit_usd:
            return ProviderResult(provider.name, [], [ProviderError("monthly_budget_exceeded", "Provider monthly cost ceiling reached")], False, 0, 0, 0, None, request.requested_at)
        if settings.daily_request_limit and daily_requests + estimated_requests > settings.daily_request_limit:
            return ProviderResult(provider.name, [], [ProviderError("daily_quota_exceeded", "Provider daily request quota reached")], False, 0, 0, 0, None, request.requested_at)

        result = provider.collect(request)
        self.store.record_usage(
            provider.name,
            request.requested_at,
            result.request_count,
            result.resource_count,
            result.estimated_cost_usd,
            result.actual_cost_usd,
            {"errors": [error.code for error in result.errors]},
        )
        if not result.errors and provider.cache_ttl_minutes > 0:
            expires = _iso(now + timedelta(minutes=provider.cache_ttl_minutes))
            self.store.set_cache(key, provider.name, request.requested_at, expires, result.to_dict())
        return result


def provider_from_name(name: str, settings: ProviderSettings, *, manual_path: str = "") -> TrendProvider:
    normalized = name.strip().lower()
    if normalized == "manual":
        return ManualProvider(manual_path)
    if normalized == "gdelt":
        return GdeltProvider(settings)
    if normalized == "wikimedia":
        return WikimediaProvider(settings)
    if normalized == "youtube":
        return YouTubeTrendProvider(settings)
    if normalized == "x":
        return XProviderStub(ProviderSettings(enabled=False))
    if normalized == "google_trends":
        return GoogleTrendsProviderStub(ProviderSettings(enabled=False))
    raise ValueError(f"Unknown trend provider: {name}")
