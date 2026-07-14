"""Operator CLI for the disabled-by-default Trend-to-Archive MVP."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any

from brand_switcher import load_brand
from config import ROOT_DIR, get_ollama_base_url, get_ollama_model
from research_brief import collect_sources
from trend_bridges import (
    build_bridge_prompt,
    parse_bridge_candidates,
    verify_historical_sources,
    with_detected_risks,
)
from trend_catalog import TrendCatalog
from trend_entities import cluster_signals
from trend_models import TrendRequest, ValidationError, utc_now
from trend_pipeline import (
    approve_opportunity,
    content_mix_status,
    load_trend_strategy,
    reject_opportunity,
)
from trend_providers import CollectionCoordinator, ProviderSettings, provider_from_name
from trend_scoring import TrendPolicy, build_opportunity
from trend_store import TrendStore


LIVE_PROVIDERS = ("gdelt", "wikimedia", "youtube")
STUB_PROVIDERS = ("x", "google_trends")


def _print_json(value: Any) -> None:
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    elif hasattr(value, "__dataclass_fields__"):
        value = asdict(value)
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _manifest(brand_id: str) -> dict[str, Any]:
    value = load_brand(brand_id)
    if not value:
        raise ValidationError(f"unknown brand: {brand_id}")
    return value


def _provider_config(manifest: dict[str, Any], name: str) -> dict[str, Any]:
    strategy = ((manifest.get("production") or {}).get("trend_strategy") or {})
    providers = strategy.get("providers") or {}
    value = providers.get(name) or {}
    return value if isinstance(value, dict) else {}


def _dedicated_youtube_key() -> str:
    """Read only the dedicated YouTube key; never reuse an AI-provider key."""
    value = os.environ.get("YOUTUBE_API_KEY", "").strip()
    path = os.path.join(ROOT_DIR, "config.json")
    if value or not os.path.isfile(path):
        return value
    try:
        with open(path, encoding="utf-8") as file:
            return str(json.load(file).get("youtube_api_key") or "").strip()
    except (OSError, ValueError, TypeError):
        return ""


def _settings(manifest: dict[str, Any], name: str) -> ProviderSettings:
    raw = _provider_config(manifest, name)
    return ProviderSettings(
        enabled=bool(raw.get("enabled", False)),
        timeout_seconds=float(raw.get("timeout_seconds", 12)),
        cache_ttl_minutes=max(0, int(raw.get("cache_ttl_minutes", 180))),
        daily_cost_limit_usd=max(0.0, float(raw.get("daily_cost_limit_usd", 0))),
        monthly_cost_limit_usd=max(0.0, float(raw.get("monthly_cost_limit_usd", 0))),
        daily_request_limit=max(0, int(raw.get("daily_request_limit", 0))),
        api_key=_dedicated_youtube_key() if name == "youtube" else "",
    )


def _request(args, terms: list[str]) -> TrendRequest:
    return TrendRequest.from_dict(
        {
            "brand_id": args.brand,
            "terms": terms,
            "geographies": args.geography,
            "languages": args.language,
            "window_hours": args.window_hours,
            "max_results": args.max_results,
            "dry_run": not args.live,
            "requested_at": args.now or utc_now(),
        }
    )


def _collect(args, store: TrendStore) -> int:
    manifest = _manifest(args.brand)
    signals = []
    results = []
    initial_terms = list(dict.fromkeys(args.term))
    if args.manual:
        manual = provider_from_name("manual", ProviderSettings(enabled=True), manual_path=args.manual)
        result = manual.collect(_request(args, initial_terms))
        results.append(result)
        signals.extend(result.signals)
        initial_terms = list(
            dict.fromkeys([*initial_terms, *(signal.normalized_entity for signal in result.signals)])
        )

    selected = args.provider or list(LIVE_PROVIDERS)
    coordinator = CollectionCoordinator(store)
    for name in selected:
        if name in STUB_PROVIDERS:
            settings = ProviderSettings(enabled=False)
            result = provider_from_name(name, settings).collect(_request(args, initial_terms))
        else:
            settings = _settings(manifest, name)
            provider = provider_from_name(name, settings)
            result = coordinator.collect(provider, _request(args, initial_terms), settings)
        results.append(result)
        signals.extend(result.signals)

    for signal in signals:
        store.save_signal(signal)
    clusters = cluster_signals(signals, now=args.now or utc_now()) if signals else []
    for cluster in clusters:
        store.save_cluster(cluster)
    _print_json(
        {
            "dry_run": not args.live,
            "signals_saved": len(signals),
            "clusters_saved": len(clusters),
            "clusters": [
                {
                    "cluster_id": item.cluster_id,
                    "entity": item.canonical_entity,
                    "providers": item.cross_source_count,
                    "unknowns": item.unknowns,
                }
                for item in clusters
            ],
            "providers": [
                {
                    "provider": item.provider,
                    "signals": len(item.signals),
                    "cache_hit": item.cache_hit,
                    "errors": [asdict(error) for error in item.errors],
                }
                for item in results
            ],
        }
    )
    return 0


def _list(args, store: TrendStore) -> int:
    if args.kind == "signals":
        values = store.list_signals(args.provider)
    elif args.kind == "clusters":
        values = store.list_clusters()
    else:
        values = store.list_opportunities(args.brand)
    _print_json([value.to_dict() for value in values])
    return 0


def _inspect(args, store: TrendStore) -> int:
    cluster = store.get_cluster(args.cluster_id)
    if not cluster:
        raise ValidationError(f"unknown cluster: {args.cluster_id}")
    _print_json(cluster)
    return 0


def _local_completion(prompt: str) -> str:
    model = get_ollama_model()
    if not model:
        raise ValidationError("ollama_model must be configured for local bridge generation")
    import ollama

    response = ollama.Client(host=get_ollama_base_url()).chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    return str(response["message"]["content"] or "").strip()


def _expiry(cluster, now: str) -> str:
    values = [signal.expires_at for signal in cluster.signals if signal.expires_at]
    if values:
        return min(values)
    current = datetime.fromisoformat(now.replace("Z", "+00:00")).astimezone(timezone.utc)
    return (current + timedelta(hours=48)).isoformat().replace("+00:00", "Z")


def _policy(manifest: dict[str, Any]) -> TrendPolicy:
    raw = ((manifest.get("production") or {}).get("trend_strategy") or {}).get("scoring") or {}
    return TrendPolicy(
        minimum_cross_source_count=int(raw.get("minimum_cross_source_count", 2)),
        minimum_opportunity_score=float(raw.get("minimum_opportunity_score", 75)),
        minimum_archive_fit_score=float(raw.get("minimum_archive_fit_score", 80)),
        minimum_sourceability_score=float(raw.get("minimum_sourceability_score", 70)),
        estimated_production_hours=float(raw.get("estimated_production_hours", 4)),
    )


def _bridge(args, store: TrendStore) -> int:
    manifest = _manifest(args.brand)
    strategy = load_trend_strategy(manifest)
    if not strategy.enabled or strategy.mode.value != "suggest":
        raise ValidationError("trend SUGGEST mode is not enabled for this brand")
    cluster = store.get_cluster(args.cluster_id)
    if not cluster:
        raise ValidationError(f"unknown cluster: {args.cluster_id}")
    if args.bridge_file:
        with open(args.bridge_file, encoding="utf-8") as file:
            raw_value = json.load(file)
        raw = json.dumps(raw_value.get("bridges", raw_value) if isinstance(raw_value, dict) else raw_value)
        fixture = True
    else:
        raw = _local_completion(build_bridge_prompt(cluster, manifest))
        fixture = False
    candidates = parse_bridge_candidates(raw, cluster)
    catalog = TrendCatalog.from_repository(args.brand)
    now = args.now or utc_now()
    saved = []
    for candidate in candidates:
        bridge = candidate
        if not fixture or len(bridge.historical_sources) < 2:
            bridge = verify_historical_sources(bridge, collect_sources)
        bridge = with_detected_risks(cluster, bridge)
        match = catalog.best_match(bridge, cluster.canonical_entity)
        opportunity = build_opportunity(
            cluster,
            bridge,
            args.brand,
            match,
            _expiry(cluster, now),
            now,
            _policy(manifest),
        )
        store.save_opportunity(opportunity)
        saved.append(opportunity)
    _print_json([item.to_dict() for item in saved])
    return 0


def _opportunities(args, store: TrendStore) -> int:
    items = store.list_opportunities(args.brand)
    _print_json(
        [
            {
                "opportunity_id": item.opportunity_id,
                "entity": item.trend.canonical_entity,
                "historical_event": item.bridge.historical_event,
                "score": item.opportunity_score,
                "eligible": item.eligible,
                "action": item.recommended_action.value,
                "status": item.status.value,
                "expires_at": item.expires_at,
                "unknowns": item.unknowns,
                "failures": item.eligibility_failures,
            }
            for item in items
        ]
    )
    return 0


def _approve(args, store: TrendStore) -> int:
    manifest = _manifest(args.brand)
    approval, seed, mix = approve_opportunity(
        store,
        args.opportunity_id,
        manifest,
        operator=args.operator,
        reason=args.reason,
        override_reason=args.override_reason,
        now=args.now,
    )
    _print_json(
        {
            "approval": approval.to_dict(),
            "topic_seed": seed.to_dict(),
            "content_mix": asdict(mix),
            "next_command": f"python scripts/run_brand_short.py {args.brand} --trend-seed {seed.seed_id}",
            "upload_triggered": False,
        }
    )
    return 0


def _reject(args, store: TrendStore) -> int:
    opportunity = store.get_opportunity(args.opportunity_id)
    if not opportunity or opportunity.brand_id != args.brand:
        raise ValidationError("opportunity does not exist for this brand")
    _print_json(
        reject_opportunity(
            store,
            args.opportunity_id,
            operator=args.operator,
            reason=args.reason,
            now=args.now,
        )
    )
    return 0


def _report(args, store: TrendStore) -> int:
    manifest = _manifest(args.brand)
    strategy = load_trend_strategy(manifest)
    mix = content_mix_status(args.brand, strategy, store, now=args.now)
    strategy_payload = asdict(strategy)
    strategy_payload["mode"] = strategy.mode.value
    _print_json({"brand_id": args.brand, "strategy": strategy_payload, "content_mix": asdict(mix)})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", default="", help="SQLite path (defaults to .mp/trends.sqlite3)")
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect", help="Import fixtures and optionally query enabled providers")
    collect.add_argument("--brand", required=True)
    collect.add_argument("--manual", default="", help="Manual JSON or CSV fixture/import")
    collect.add_argument("--provider", action="append", choices=[*LIVE_PROVIDERS, *STUB_PROVIDERS])
    collect.add_argument("--term", action="append", default=[])
    collect.add_argument("--geography", action="append", default=["US"])
    collect.add_argument("--language", action="append", default=["en"])
    collect.add_argument("--window-hours", type=float, default=24)
    collect.add_argument("--max-results", type=int, default=25)
    collect.add_argument("--live", action="store_true", help="Permit requests to explicitly enabled providers")
    collect.add_argument("--now", default="")
    collect.set_defaults(handler=_collect)

    listing = sub.add_parser("list", help="List persisted trend records")
    listing.add_argument("kind", choices=["signals", "clusters", "opportunities"])
    listing.add_argument("--provider", default="")
    listing.add_argument("--brand", default="")
    listing.set_defaults(handler=_list)

    inspect = sub.add_parser("inspect", help="Inspect one trend cluster")
    inspect.add_argument("cluster_id")
    inspect.set_defaults(handler=_inspect)

    bridge = sub.add_parser("bridge", help="Generate or import historical bridges and score them")
    bridge.add_argument("cluster_id")
    bridge.add_argument("--brand", required=True)
    bridge.add_argument("--bridge-file", default="", help="Offline JSON bridge candidates")
    bridge.add_argument("--now", default="")
    bridge.set_defaults(handler=_bridge)

    opportunities = sub.add_parser("opportunities", help="Show review-ready opportunities")
    opportunities.add_argument("--brand", required=True)
    opportunities.set_defaults(handler=_opportunities)

    for name, handler in (("approve", _approve), ("reject", _reject)):
        decision = sub.add_parser(name, help=f"{name.title()} one opportunity")
        decision.add_argument("opportunity_id")
        decision.add_argument("--brand", required=True)
        decision.add_argument("--operator", required=True)
        decision.add_argument("--reason", required=True)
        decision.add_argument("--now", default="")
        if name == "approve":
            decision.add_argument("--override-reason", default="")
        decision.set_defaults(handler=handler)

    report = sub.add_parser("report", help="Report trend-assisted content mix")
    report.add_argument("--brand", required=True)
    report.add_argument("--now", default="")
    report.set_defaults(handler=_report)
    return parser


def main(argv: list[str] | None = None, *, store: TrendStore | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = store or TrendStore(args.store or None)
    try:
        return int(args.handler(args, store))
    except (ValidationError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
