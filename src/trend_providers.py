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
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import quote, urljoin, urlparse

import requests

from trend_models import ProviderError, ProviderResult, TrendRequest, TrendSignal, utc_now
from trend_store import TrendStore


JsonFetcher = Callable[[str, dict[str, Any], dict[str, str], float], dict[str, Any]]
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
ALLOWED_PROVIDER_HOSTS = {
    "api.gdeltproject.org": {"api.gdeltproject.org"},
    "wikimedia.org": {"wikimedia.org"},
    "www.googleapis.com": {"www.googleapis.com"},
}

_SECRET_NAME = r"(?:key|api_key|access_token|bearer|authorization|token|client_secret|xi-api-key)"


def sanitize_provider_error(value: object) -> str:
    """Remove credentials from provider failures before they cross a boundary."""
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = "".join(character for character in text if unicodedata.category(character) != "Cc")
    text = re.sub(
        rf"(?i)([?&]{_SECRET_NAME}=)[^&\s]+",
        r"\1[REDACTED]",
        text,
    )
    text = re.sub(
        rf"(?i)\b({_SECRET_NAME})\s*[:=]\s*(?:Bearer\s+)?[^\s,;]+",
        r"\1=[REDACTED]",
        text,
    )
    text = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", text)
    return text[:500]


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
    min_retry_delay: float = 0.0,
) -> dict[str, Any]:
    parsed_initial = urlparse(url)
    if parsed_initial.scheme != "https" or parsed_initial.hostname not in ALLOWED_PROVIDER_HOSTS:
        raise ValueError("provider URL scheme or host is not allowlisted")
    allowed_hosts = ALLOWED_PROVIDER_HOSTS[parsed_initial.hostname]
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            current_url = url
            for redirect_count in range(MAX_REDIRECTS + 1):
                response = requests.get(
                    current_url, params=params if redirect_count == 0 else None,
                    # Scalar, not a (connect, read) tuple. Measured against
                    # api.gdeltproject.org on requests 2.34.2/urllib3 2.7.0: a
                    # short connect value stays on the socket for the read, so
                    # (5.0, 30.0) and even Timeout(connect=5, read=30) both die
                    # at ~5s with "read timeout=5.0". GDELT needs ~13s to first
                    # byte, so the old cap made it permanently unusable and
                    # silently limited every provider to a 5s read.
                    headers=headers, timeout=timeout,
                    allow_redirects=False, stream=True,
                )
                try:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        if redirect_count >= MAX_REDIRECTS:
                            raise ValueError("provider response exceeded redirect limit")
                        location = response.headers.get("Location") or ""
                        current_url = urljoin(current_url, location)
                        parsed_redirect = urlparse(current_url)
                        if parsed_redirect.scheme != "https" or parsed_redirect.hostname not in allowed_hosts:
                            raise ValueError("provider redirect target is not allowlisted")
                        continue
                    if response.status_code == 429 and attempt + 1 < attempts:
                        # Honour the provider's own floor. GDELT asks for one
                        # request every 5s and answers 429 in plain text; the
                        # old 1s default retried well inside that window and
                        # just collected more 429s.
                        retry_after = min(float(response.headers.get("Retry-After", "1") or 1), 30.0)
                        time.sleep(max(retry_after, min_retry_delay, 0))
                        break
                    response.raise_for_status()
                    length = response.headers.get("Content-Length")
                    if length and int(length) > MAX_RESPONSE_BYTES:
                        raise ValueError("provider response exceeds maximum size")
                    body = bytearray()
                    for chunk in response.iter_content(chunk_size=65536):
                        body.extend(chunk)
                        if len(body) > MAX_RESPONSE_BYTES:
                            raise ValueError("provider response exceeds maximum size")
                    payload = json.loads(body.decode("utf-8"))
                    return payload if isinstance(payload, dict) else {}
                finally:
                    try:
                        response.close()
                    except Exception:
                        pass
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                # Ordinary backoff. The provider rate floor deliberately does
                # not apply here — it answers 429s, not connection errors, and
                # forcing it on every failure just slows the whole run down.
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


class ProviderNotDispatchedError(RuntimeError):
    """A provider failure proven to have happened before external dispatch."""


@dataclass
class ProviderSettings:
    enabled: bool = False
    timeout_seconds: float = 12.0
    # Minimum spacing between consecutive requests to this provider. Providers
    # that publish a rate floor set their own default; 0 means no pacing.
    min_request_interval_seconds: float = 0.0
    # Attempts per request. Providers that 429 transiently raise their own.
    max_attempts: int = 3
    cache_ttl_minutes: int = 180
    daily_cost_limit_usd: float = 0.0
    monthly_cost_limit_usd: float = 0.0
    daily_request_limit: int = 0
    api_key: str = ""
    youtube_retention_verified: bool = False
    refresh_after_hours: int = 24
    retention_days: int = 30
    user_agent: str = "MoneyPrinterV2/2.0 (trend intelligence; local operator)"


class BaseProvider:
    name = "base"
    estimated_max_cost_usd = 0.0

    def __init__(
        self, settings: ProviderSettings | None = None,
        fetch_json: JsonFetcher = fetch_json_with_retries, *, clock=utc_now,
    ):
        self.settings = settings or ProviderSettings()
        self.enabled = self.settings.enabled
        if self.name == "youtube":
            self.enabled = self.enabled and self.settings.youtube_retention_verified
        self.cache_ttl_minutes = self.settings.cache_ttl_minutes
        self.fetch_json = fetch_json
        self.clock = clock

    def error_result(self, code: str, message: str, *, retryable: bool = False) -> ProviderResult:
        return ProviderResult(
            provider=self.name,
            signals=[],
            errors=[ProviderError(code=code, message=sanitize_provider_error(message), retryable=retryable)],
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
            is_csv = self.path.suffix.lower() == ".csv"
            if self.path.suffix.lower() == ".csv":
                with self.path.open(encoding="utf-8-sig", newline="") as file:
                    payloads = list(csv.DictReader(file))
            else:
                with self.path.open(encoding="utf-8") as file:
                    raw = json.load(file)
                payloads = raw.get("signals", []) if isinstance(raw, dict) else raw
            if not isinstance(payloads, list):
                raise ValueError("manual signals must be a list")
            signals = []
            errors = []
            for item in payloads[: request.max_results]:
                if not isinstance(item, dict):
                    errors.append(ProviderError("malformed_response", "Manual record is not an object"))
                    continue
                try:
                    if is_csv:
                        item = self._csv_payload(item, request)
                    signals.append(TrendSignal.from_dict(item))
                except (ValueError, TypeError) as exc:
                    errors.append(ProviderError("malformed_response", sanitize_provider_error(exc)))
            return ProviderResult(
                provider=self.name,
                signals=signals[: request.max_results],
                errors=errors,
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
    # GDELT's 429 body states: "Please limit requests to one every 5 seconds."
    # Measured time-to-first-byte is ~13s, so the 12s default timeout is also
    # too tight; brands should raise timeout_seconds for this provider.
    default_min_request_interval_seconds = 5.0
    # Measured 2026-07-31: GDELT still answered 429 to two of three probes
    # spaced 12s apart, so its 429s are load-shedding rather than a penalty
    # that pacing alone clears. Retrying is what actually gets a 200, and
    # GDELT is the only news source feeding minimum_cross_source_count.
    default_max_attempts = 5

    def __init__(
        self, settings: ProviderSettings | None = None,
        fetch_json: JsonFetcher = fetch_json_with_retries, *, clock=utc_now,
    ):
        super().__init__(settings, fetch_json, clock=clock)
        if fetch_json is fetch_json_with_retries:
            # Bind the rate floor and attempt budget into real calls only, so
            # the injected-fetcher contract stays four positional arguments.
            self.fetch_json = partial(
                fetch_json_with_retries,
                min_retry_delay=self._pace(),
                attempts=self._attempts(),
            )

    def _pace(self) -> float:
        configured = float(self.settings.min_request_interval_seconds or 0.0)
        return max(configured, self.default_min_request_interval_seconds)

    def _attempts(self) -> int:
        return max(int(self.settings.max_attempts or 0), self.default_max_attempts)

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
        pace = self._pace()
        for index, term in enumerate(request.terms[: request.max_results]):
            try:
                # Space consecutive terms. Without this every term after the
                # first fires immediately and comes back 429.
                if index and pace > 0:
                    time.sleep(pace)
                requests_made += 1
                payload = self.fetch_json(
                    self.endpoint,
                    {"query": term, "mode": "ArtList", "format": "json", "maxrecords": 25, "timespan": f"{int(request.window_hours)}h"},
                    {"User-Agent": self.settings.user_agent},
                    self.settings.timeout_seconds,
                )
                articles = payload.get("articles") or []
                if not isinstance(articles, list):
                    errors.append(ProviderError("malformed_response", "GDELT articles must be a list"))
                    articles = []
                valid_articles = [item for item in articles[:100] if isinstance(item, dict)]
                if len(valid_articles) != len(articles[:100]):
                    errors.append(ProviderError("malformed_response", "GDELT returned malformed article records"))
                domains = {str(item.get("domain") or "").lower() for item in valid_articles if item.get("domain")}
                urls = [str(item.get("url")) for item in valid_articles if item.get("url")][:10]
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
                            "volume": len(valid_articles),
                            "volume_is_absolute": False,
                            "velocity": None,
                            "related_terms": [],
                            "source_urls": urls,
                            "metric_type": "gdelt_article_matches",
                            "raw_metadata": {"unique_domains": len(domains), "article_count": len(valid_articles)},
                        }
                    )
                )
            except (requests.RequestException, ValueError, TypeError) as exc:
                errors.append(ProviderError("provider_request_failed", sanitize_provider_error(f"{term}: {exc}"), True))
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
                raw_items = payload.get("items") or []
                if not isinstance(raw_items, list):
                    raw_items = []
                    errors.append(ProviderError("malformed_response", "Wikimedia items must be a list"))
                views = []
                malformed = False
                for item in raw_items[:100]:
                    try:
                        if not isinstance(item, dict):
                            raise TypeError("record is not an object")
                        views.append(int(item.get("views") or 0))
                    except (TypeError, ValueError):
                        malformed = True
                if malformed:
                    errors.append(ProviderError("malformed_response", "Wikimedia returned malformed records"))
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
                errors.append(ProviderError("provider_request_failed", sanitize_provider_error(f"{term}: {exc}"), True))
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
                search_items = search.get("items") or []
                if not isinstance(search_items, list):
                    search_items = []
                    errors.append(ProviderError("malformed_response", "YouTube search items must be a list"))
                ids = []
                malformed = False
                for item in search_items[:100]:
                    if not isinstance(item, dict) or not isinstance(item.get("id"), dict):
                        malformed = True
                        continue
                    value = str(item["id"].get("videoId") or "")
                    if value:
                        ids.append(value)
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
                    raw_stats = stats.get("items") or []
                    if isinstance(raw_stats, list):
                        stats_items = [item for item in raw_stats[:100] if isinstance(item, dict)]
                        malformed = malformed or len(stats_items) != len(raw_stats[:100])
                    else:
                        malformed = True
                if malformed:
                    errors.append(ProviderError("malformed_response", "YouTube returned malformed nested records"))
                vph_values = []
                total_views = 0
                for item in stats_items:
                    try:
                        snippet = item.get("snippet") or {}
                        statistics = item.get("statistics") or {}
                        if not isinstance(snippet, dict) or not isinstance(statistics, dict):
                            raise TypeError("nested record is not an object")
                        published = _parse_time(snippet.get("publishedAt") or request.requested_at)
                        hours = max((_parse_time(request.requested_at) - published).total_seconds() / 3600, 1)
                        views = int(statistics.get("viewCount") or 0)
                        total_views += views
                        vph_values.append(views / hours)
                    except (TypeError, ValueError):
                        errors.append(ProviderError("malformed_response", "YouTube returned malformed statistics"))
                fetched_at = self.clock()
                fetched = _parse_time(fetched_at)
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
                                "fetched_at": fetched_at,
                                "refresh_due_at": _iso(fetched + timedelta(hours=self.settings.refresh_after_hours)),
                                "delete_or_expire_at": _iso(fetched + timedelta(days=self.settings.retention_days)),
                                "retention_policy": "youtube_public_data_local_cache_v1",
                                "source_provenance": "YouTube Data API v3 public search and statistics",
                            },
                        }
                    )
                )
            except (requests.RequestException, ValueError, TypeError) as exc:
                errors.append(ProviderError("provider_request_failed", sanitize_provider_error(f"{term}: {exc}"), True))
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
    def __init__(self, store: TrendStore, *, clock=utc_now):
        self.store = store
        self.clock = clock

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
        now_text = self.clock()
        cached = self.store.get_cache(key, now_text)
        if cached:
            result = ProviderResult.from_dict(cached)
            return ProviderResult(result.provider, result.signals, result.errors, True, 0, result.resource_count, 0, 0, now_text)

        now = _parse_time(now_text)
        daily_since = _iso(now - timedelta(days=1))
        monthly_since = _iso(now - timedelta(days=30))
        estimate = max(float(provider.estimated_max_cost_usd), 0)
        request_estimator = getattr(provider, "estimated_max_requests", None)
        estimated_requests = int(request_estimator(request)) if request_estimator else 0
        reservation_id, budget_error = self.store.reserve_provider_budget(
            provider.name, now_text, estimated_requests, estimate,
            daily_since=daily_since, monthly_since=monthly_since,
            daily_request_limit=settings.daily_request_limit,
            daily_cost_limit_usd=settings.daily_cost_limit_usd,
            monthly_cost_limit_usd=settings.monthly_cost_limit_usd,
        )
        if budget_error:
            messages = {
                "daily_quota_exceeded": "Provider daily request quota reached",
                "daily_budget_exceeded": "Provider daily cost ceiling reached",
                "monthly_budget_exceeded": "Provider monthly cost ceiling reached",
            }
            return ProviderResult(provider.name, [], [ProviderError(budget_error, messages[budget_error])], False, 0, 0, 0, None, now_text)
        try:
            result = provider.collect(request)
        except ProviderNotDispatchedError:
            self.store.release_provider_budget(reservation_id, reason="provider_not_dispatched")
            raise
        except Exception:
            self.store.charge_uncertain_provider_budget(
                reservation_id,
                metadata={"error": "provider exception after dispatch status became uncertain"},
            )
            raise
        if result.request_count == 0 and result.errors:
            self.store.release_provider_budget(
                reservation_id,
                reason="provider_reported_not_dispatched",
            )
            return result
        self.store.reconcile_provider_budget(
            reservation_id,
            request_count=result.request_count,
            resource_count=result.resource_count,
            estimated_cost_usd=result.estimated_cost_usd,
            actual_cost_usd=result.actual_cost_usd,
            metadata={"errors": [error.code for error in result.errors]},
            outcome="dispatched_failure" if result.errors else "dispatched_success",
        )
        if not result.errors and provider.cache_ttl_minutes > 0:
            expires = _iso(now + timedelta(minutes=provider.cache_ttl_minutes))
            self.store.set_cache(key, provider.name, now_text, expires, result.to_dict())
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
