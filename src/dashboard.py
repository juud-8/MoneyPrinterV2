"""CLI and HTML dashboards for brand analytics."""

import html
import json
import os
from collections import defaultdict

from analytics import ROOT_DIR, get_dashboard_data, get_asset_spend_alert_threshold_usd


def _dashboard_html_path() -> str:
    return os.path.join(ROOT_DIR, ".mp", "dashboard.html")


def print_cli_dashboard(days: int = 7) -> None:
    data = get_dashboard_data(days=days)
    totals = data["totals"]

    print("\n=== Brand Dashboard ===")
    print(f"Generated: {data['generated_at']}  |  Window: last {days} days\n")

    header = (
        f"{'Brand':<28} {'Posts':>5} {'Up':>4} {'Views*':>8} "
        f"{f'Spend ({days}d)':>12} {'Spend (all)':>12}"
    )
    print(header)
    print("-" * len(header))

    for brand in data["brands"]:
        if brand["post_count"] == 0 and brand["spend_all_time_usd"] == 0:
            continue
        views = brand["tracked_views"]
        views_label = str(views) if views is not None else "—"
        print(
            f"{brand['channel_name'][:28]:<28} "
            f"{brand['post_count']:>5} "
            f"{brand['uploaded_count']:>4} "
            f"{views_label:>8} "
            f"${brand.get('spend_window_usd', 0):>10.2f} "
            f"${brand['spend_all_time_usd']:>10.2f}"
        )

    print("-" * len(header))
    print(
        f"{'TOTAL':<28} {totals['videos']:>5} {totals['uploaded']:>4} "
        f"{'—':>8} ${totals.get('spend_window_usd', 0):>10.2f} "
        f"${totals['spend_all_time_usd']:>10.2f}"
    )
    print("\n* Views fill in after YouTube metrics refresh (web UI button or youtube_metrics.py)")

    if data["recent_spend"]:
        print("\n=== Premium Spend (last {0} days) ===".format(days))
        by_tier = data["spend_by_tier"]
        by_provider = data["spend_by_provider"]
        if by_tier:
            print("By tier:", ", ".join(f"{k}: ${v:.2f}" for k, v in sorted(by_tier.items())))
        if by_provider:
            print(
                "By provider:",
                ", ".join(f"{k}: ${v:.2f}" for k, v in sorted(by_provider.items())),
            )

        threshold = get_asset_spend_alert_threshold_usd()
        recent_total = totals.get("spend_window_usd", 0)
        if recent_total > threshold:
            print(
                f"\n⚠ Recent spend ${recent_total:.2f} exceeds alert threshold ${threshold:.2f}"
            )

    print("\n=== Recent Posts ===")
    shown = 0
    for brand in data["brands"]:
        for post in brand.get("recent_posts", []):
            status = post.get("status") or "generated"
            title = (post.get("title") or "")[:55]
            brand_name = brand["channel_name"]
            print(f"- [{post.get('date', '')}] {brand_name} ({status}): {title}")
            if post.get("url"):
                print(f"    {post['url']}")
            shown += 1
            if shown >= 15:
                break
        if shown >= 15:
            break

    if shown == 0:
        print("No posts logged yet.")


def _chart_rows(mapping: dict[str, float]) -> list[dict]:
    return [{"label": key, "value": value} for key, value in sorted(mapping.items())]


def render_html_dashboard(days: int = 7) -> str:
    data = get_dashboard_data(days=days)
    totals = data["totals"]
    posts_by_day: dict[str, int] = defaultdict(int)
    for video in data["videos"]:
        day = (video.get("date") or "")[:10]
        if day:
            posts_by_day[day] += 1
    timeline = sorted(posts_by_day.items())

    brand_cards = []
    for brand in data["brands"]:
        if brand["post_count"] == 0 and brand["spend_all_time_usd"] == 0:
            continue
        recent_rows = []
        for post in brand.get("recent_posts", []):
            recent_rows.append(
                "<li>"
                f"<span class='muted'>{html.escape(post.get('date', ''))}</span> "
                f"<span class='pill'>{html.escape(post.get('status') or 'generated')}</span> "
                f"{html.escape((post.get('title') or '')[:80])}"
                + (
                    f"<br><a href='{html.escape(post['url'])}' target='_blank' rel='noopener'>"
                    f"{html.escape(post['url'])}</a>"
                    if post.get("url")
                    else ""
                )
                + "</li>"
            )
        brand_cards.append(
            f"""
            <article class="card">
              <h3>{html.escape(brand['channel_name'])}</h3>
              <p class="muted">{html.escape(brand['brand_id'])}</p>
              <div class="stats">
                <div><strong>{brand['post_count']}</strong><span>Posts</span></div>
                <div><strong>{brand['uploaded_count']}</strong><span>Uploaded</span></div>
                <div><strong>{brand['metrics_filled']}</strong><span>With metrics</span></div>
                <div><strong>${brand.get('spend_window_usd', 0):.2f}</strong><span>Spend ({days}d)</span></div>
              </div>
              <ul class="recent">{''.join(recent_rows) or '<li class="muted">No posts yet</li>'}</ul>
            </article>
            """
        )

    payload = {
        "timeline_labels": [row[0] for row in timeline],
        "timeline_values": [row[1] for row in timeline],
        "tier_labels": [row["label"] for row in _chart_rows(data["spend_by_tier"])],
        "tier_values": [row["value"] for row in _chart_rows(data["spend_by_tier"])],
        "provider_labels": [row["label"] for row in _chart_rows(data["spend_by_provider"])],
        "provider_values": [row["value"] for row in _chart_rows(data["spend_by_provider"])],
    }

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MoneyPrinterV2 Brand Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #0f1419;
      --panel: #1a2332;
      --text: #e6edf3;
      --muted: #8b949e;
      --accent: #58a6ff;
      --border: #30363d;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Segoe UI, system-ui, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
    }}
    header, main {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}
    h1 {{ margin: 0 0 8px; font-size: 1.8rem; }}
    .muted {{ color: var(--muted); }}
    .totals {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 12px;
      margin: 24px 0;
    }}
    .totals div {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 16px;
    }}
    .totals strong {{ display: block; font-size: 1.5rem; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 16px;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 18px;
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 8px;
      margin: 12px 0;
    }}
    .stats div {{
      text-align: center;
      background: rgba(255,255,255,0.03);
      border-radius: 8px;
      padding: 10px 6px;
    }}
    .stats strong {{ display: block; font-size: 1.2rem; }}
    .stats span {{ color: var(--muted); font-size: 0.8rem; }}
    .recent {{ list-style: none; padding: 0; margin: 0; }}
    .recent li {{ padding: 8px 0; border-top: 1px solid var(--border); font-size: 0.92rem; }}
    .recent a {{ color: var(--accent); word-break: break-all; }}
    .pill {{
      display: inline-block;
      font-size: 0.72rem;
      padding: 2px 8px;
      border-radius: 999px;
      background: rgba(88,166,255,0.15);
      color: var(--accent);
      margin-right: 6px;
    }}
    .charts {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 16px;
      margin-top: 24px;
    }}
    canvas {{ max-height: 260px; }}
  </style>
</head>
<body>
  <header>
    <h1>Brand Dashboard</h1>
    <p class="muted">Generated {html.escape(data['generated_at'])} · Window: last {days} days</p>
    <div class="totals">
      <div><strong>{totals['videos']}</strong><span class="muted">Total posts (deduped)</span></div>
      <div><strong>{totals['uploaded']}</strong><span class="muted">Uploaded</span></div>
      <div><strong>${totals.get('spend_window_usd', 0):.2f}</strong><span class="muted">Premium spend ({days}d)</span></div>
      <div><strong>${totals['spend_all_time_usd']:.2f}</strong><span class="muted">Premium spend (all time)</span></div>
    </div>
  </header>
  <main>
    <h2>Brands</h2>
    <div class="grid">{''.join(brand_cards) or '<p class="muted">No brand activity yet.</p>'}</div>
    <h2>Charts</h2>
    <div class="charts">
      <div class="card"><h3>Posts over time</h3><canvas id="timelineChart"></canvas></div>
      <div class="card"><h3>Spend by tier ({days}d)</h3><canvas id="tierChart"></canvas></div>
      <div class="card"><h3>Spend by provider ({days}d)</h3><canvas id="providerChart"></canvas></div>
    </div>
  </main>
  <script>
    const payload = {json.dumps(payload)};
    const chartDefaults = {{
      responsive: true,
      plugins: {{ legend: {{ labels: {{ color: '#e6edf3' }} }} }},
      scales: {{
        x: {{ ticks: {{ color: '#8b949e' }}, grid: {{ color: '#30363d' }} }},
        y: {{ ticks: {{ color: '#8b949e' }}, grid: {{ color: '#30363d' }} }}
      }}
    }};
    if (payload.timeline_labels.length) {{
      new Chart(document.getElementById('timelineChart'), {{
        type: 'bar',
        data: {{
          labels: payload.timeline_labels,
          datasets: [{{ label: 'Posts', data: payload.timeline_values, backgroundColor: '#58a6ff' }}]
        }},
        options: chartDefaults
      }});
    }}
    if (payload.tier_labels.length) {{
      new Chart(document.getElementById('tierChart'), {{
        type: 'doughnut',
        data: {{
          labels: payload.tier_labels,
          datasets: [{{ data: payload.tier_values, backgroundColor: ['#58a6ff','#3fb950','#d29922','#f85149'] }}]
        }},
        options: {{ responsive: true, plugins: {{ legend: {{ labels: {{ color: '#e6edf3' }} }} }} }}
      }});
    }}
    if (payload.provider_labels.length) {{
      new Chart(document.getElementById('providerChart'), {{
        type: 'pie',
        data: {{
          labels: payload.provider_labels,
          datasets: [{{ data: payload.provider_values, backgroundColor: ['#58a6ff','#a371f7','#3fb950','#d29922'] }}]
        }},
        options: {{ responsive: true, plugins: {{ legend: {{ labels: {{ color: '#e6edf3' }} }} }} }}
      }});
    }}
  </script>
</body>
</html>
"""


def write_html_dashboard(days: int = 7) -> str:
    path = _dashboard_html_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    content = render_html_dashboard(days=days)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path
