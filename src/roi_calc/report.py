"""Reports: a self-contained HTML business case (inline SVG charts), Markdown, JSON and the Excel workbook."""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from jinja2 import Environment

from . import catalog as cat
from . import engine
from .scenario import Scenario

PALETTE = ["#2563EB", "#D97706", "#059669", "#7C3AED", "#DC2626", "#0891B2"]


def build_summary(s: Scenario, results: list[engine.OptionResult], cats: dict[str, Any]) -> dict[str, Any]:
    summ = engine.summary(s, results)
    providers = {c.provider for r in results for c in r.task.calls if c.rates} | \
        {o.platform.provider for o in s.options if o.platform}
    summ["_services"] = {p: (cats.get(p) or {}).get("services", {}) for p in sorted(providers) if p in cats}
    notes = []
    for r in results:
        for c in r.task.calls:
            if c.rates and c.rates.verify:
                notes.append(f"{c.rates.label}: rates come from a third-party source; check against the "
                             f"{(cats.get(c.provider) or {}).get('label', c.provider)} price page before use.")
            if c.rates:
                notes += [f"{c.rates.label}: {n}" for n in c.rates.notes if "promotional" in n]
            if c.rates and c.rates.override:
                notes.append(f"{r.option}: {c.rates.label} uses negotiated rates from price_overrides.")
            if c.measured:
                notes.append(f"{r.option}: cost per call measured in a 4.1 eval run, not priced from the catalog.")
        if r.kpis["payback_month"] is None:
            notes.append(f"{r.option}: does not pay back within {s.horizon_months} months.")
        o = next(x for x in s.options if x.name == r.option)
        if o.containment_source:
            notes.append(f"{r.option}: containment {r.containment:.0%} from {o.containment_source}. Use it only if the "
                         f"option also passes the 4.1 release gates (other graders, critical cases).")
    for p in sorted(providers):
        if p in cats:
            notes.append(f"{cats[p].get('label', p)} prices as of {cats[p]['as_of']} ({cats[p]['source']}).")
    summ["_notes"] = list(dict.fromkeys(notes))
    return summ


def _fmt(v: Any, cur: str, kind: str = "money") -> str:
    if v is None:
        return "n/a"
    if kind == "pct":
        return f"{v * 100:,.1f}%"
    if kind == "month":
        return "immediately" if v == 0 else f"month {v}"
    if abs(v) >= 1e7 and cur == "INR":
        return f"{cur} {v / 1e7:,.2f} cr"
    if abs(v) >= 1e6:
        return f"{cur} {v / 1e6:,.2f}M"
    return f"{cur} {v:,.0f}" if abs(v) >= 100 else f"{cur} {v:,.2f}"


def _line_chart(series: list[tuple[str, list[float]]], w: int = 760, h: int = 280) -> str:
    pad_l, pad_r, pad_t, pad_b = 70, 16, 16, 34
    allv = [v for _, vs in series for v in vs] + [0.0]
    lo, hi = min(allv), max(allv)
    if hi == lo:
        hi = lo + 1
    n = max(len(vs) for _, vs in series)

    def x(i):
        return pad_l + (w - pad_l - pad_r) * (i / max(n - 1, 1))

    def y(v):
        return pad_t + (h - pad_t - pad_b) * (1 - (v - lo) / (hi - lo))
    parts = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Cumulative cash flow by month" '
             f'style="width:100%;max-width:{w}px">']
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        parts.append(f'<line x1="{pad_l}" x2="{w - pad_r}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="#e5e7eb"/>'
                     f'<text x="{pad_l - 6}" y="{y(v) + 4:.1f}" font-size="11" text-anchor="end" fill="#6b7280">'
                     f'{v / 1e6:,.1f}M</text>')
    parts.append(f'<line x1="{pad_l}" x2="{w - pad_r}" y1="{y(0):.1f}" y2="{y(0):.1f}" stroke="#9ca3af"/>')
    for i in range(0, n, max(1, n // 12)):
        parts.append(f'<text x="{x(i):.1f}" y="{h - 12}" font-size="11" text-anchor="middle" fill="#6b7280">{i + 1}</text>')
    for k, (name, vs) in enumerate(series):
        pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(vs))
        parts.append(f'<polyline fill="none" stroke="{PALETTE[k % len(PALETTE)]}" stroke-width="2.2" points="{pts}">'
                     f'<title>{html.escape(name)}</title></polyline>')
    parts.append("</svg>")
    return "".join(parts)


def _tornado(rows: list[dict[str, Any]], cur: str, w: int = 760) -> str:
    if not rows:
        return ""
    base = rows[0]["base"]
    span = max(max(abs(r["low"] - base), abs(r["high"] - base)) for r in rows) or 1
    bh, gap, lab = 22, 8, 170
    h = len(rows) * (bh + gap) + 30
    mid = lab + (w - lab - 20) / 2
    scale = (w - lab - 20) / 2 / span
    parts = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="NPV sensitivity" style="width:100%;max-width:{w}px">',
             f'<line x1="{mid}" x2="{mid}" y1="0" y2="{h - 24}" stroke="#9ca3af"/>']
    for i, r in enumerate(rows):
        yy = i * (bh + gap) + 4
        for v, color in ((r["low"], "#DC2626"), (r["high"], "#059669")):
            d = (v - base) * scale
            x0 = mid + min(0, d)
            parts.append(f'<rect x="{x0:.1f}" y="{yy}" width="{abs(d):.1f}" height="{bh}" fill="{color}" opacity="0.75">'
                         f'<title>{html.escape(r["driver"])}: {_fmt(v, cur)}</title></rect>')
        parts.append(f'<text x="{lab - 8}" y="{yy + 15}" font-size="12" text-anchor="end">{html.escape(r["driver"])}</text>')
    parts.append(f'<text x="{mid}" y="{h - 6}" font-size="11" text-anchor="middle" fill="#6b7280">NPV {_fmt(base, cur)}'
                 f' (red: driver down, green: driver up)</text></svg>')
    return "".join(parts)


TEMPLATE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ s.name }}: business case</title>
<style>
body{font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;color:#111827;margin:0;background:#f9fafb}
main{max-width:1000px;margin:0 auto;padding:28px 20px 60px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:32px 0 10px}.muted{color:#6b7280;font-size:13px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:18px 0}
.card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px}.card b{display:block;font-size:22px}
table{border-collapse:collapse;width:100%;background:#fff;border:1px solid #e5e7eb;border-radius:8px;font-size:14px}
th,td{padding:8px 10px;border-bottom:1px solid #f0f0f0;text-align:right}th:first-child,td:first-child{text-align:left}
th{background:#f3f4f6;font-weight:600}.best{background:#ecfdf5}
.legend span{display:inline-block;margin-right:14px;font-size:13px}.legend i{display:inline-block;width:12px;height:3px;margin-right:5px;vertical-align:middle}
.panel{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px}
ul.notes{font-size:13px;color:#374151}
</style></head><body><main>
<h1>{{ s.name }}</h1>
<div class="muted">{{ s.horizon_months }}-month business case in {{ s.currency }}{% if s.currency != 'USD' %} (1 USD = {{ s.fx_usd }} {{ s.currency }}){% endif %}, starting {{ s.start_date }}; discount rate {{ (s.discount_rate_annual*100)|round(1) }}% a year. Generated {{ generated }} by genai-roi-calculator {{ version }}.</div>
{% if s.description %}<p>{{ s.description }}</p>{% endif %}
<div class="cards">
<div class="card"><span class="muted">Best option</span><b style="font-size:16px">{{ best.option }}</b></div>
<div class="card"><span class="muted">NPV</span><b>{{ fmt(best.kpis.npv) }}</b></div>
<div class="card"><span class="muted">Payback</span><b>{{ fmtm(best.kpis.payback_month) }}</b></div>
<div class="card"><span class="muted">ROI over the horizon</span><b>{{ fmtp(best.kpis.roi) }}</b></div>
<div class="card"><span class="muted">Cost per task, AI vs human</span><b style="font-size:18px">{{ fmt(best.kpis.ai_cost_per_task) }} vs {{ fmt(best.kpis.human_cost_per_task) }}</b></div>
</div>
<h2>Options compared</h2>
<table><tr><th>Option</th><th>NPV</th><th>Payback</th><th>ROI</th><th>IRR</th><th>AI cost per task</th><th>Containment</th></tr>
{% for r in results %}<tr class="{{ 'best' if r.option == best.option else '' }}"><td>{{ r.option }}</td><td>{{ fmt(r.kpis.npv) }}</td><td>{{ fmtm(r.kpis.payback_month) }}</td><td>{{ fmtp(r.kpis.roi) }}</td><td>{{ fmtp(r.kpis.irr_annual) }}</td><td>{{ fmt(r.kpis.ai_cost_per_task) }}</td><td>{{ fmtp(r.containment) }}</td></tr>{% endfor %}
</table>
<h2>Cumulative cash flow</h2>
<div class="panel">{{ chart|safe }}<div class="legend">{% for r in results %}<span><i style="background:{{ palette[loop.index0 % 6] }}"></i>{{ r.option }}</span>{% endfor %}</div></div>
<h2>Where the money goes ({{ best.option }})</h2>
<table><tr><th>Over {{ s.horizon_months }} months</th><th>{{ s.currency }}</th></tr>
<tr><td>Savings (labour, errors, avoidable fixed cost, after realisation)</td><td>{{ fmt(best.breakdown.savings) }}</td></tr>
<tr><td>AI usage (models and platform)</td><td>{{ fmt(best.breakdown.ai_usage) }}</td></tr>
<tr><td>One-off (build, integration, change)</td><td>{{ fmt(best.breakdown.one_off) }}</td></tr>
<tr><td>Run costs</td><td>{{ fmt(best.breakdown.run) }}</td></tr>
<tr><td>Maintenance</td><td>{{ fmt(best.breakdown.maintenance) }}</td></tr>
<tr><th>Net cash flow</th><th>{{ fmt(best.kpis.total_cash_flow) }}</th></tr></table>
<h2>Cost per AI task</h2>
<table><tr><th>Option / line</th><th>Route</th><th>Tier</th><th>USD per task</th></tr>
{% for r in results %}<tr><td><b>{{ r.option }}</b></td><td></td><td></td><td><b>{{ '%.5f'|format(r.task.total_usd) }}</b></td></tr>
{% for c in r.task.calls %}<tr><td>&nbsp;&nbsp;{{ c.rates.label if c.rates else c.model + ' (measured)' }}</td><td>{{ c.route }}</td><td>{{ c.tier }}</td><td>{{ '%.5f'|format(c.usd_per_task) }}</td></tr>{% endfor %}
{% for k, v in r.task.platform_usd.items() %}<tr><td>&nbsp;&nbsp;{{ k }}</td><td></td><td></td><td>{{ '%.5f'|format(v) }}</td></tr>{% endfor %}
{% endfor %}</table>
<h2>Sensitivity ({{ best.option }}): NPV with each driver &plusmn;{{ (s.sensitivity.pct*100)|round|int }}%</h2>
<div class="panel">{{ tornado|safe }}</div>
<p class="muted">Break-even: containment {{ fmtp(be.containment) }}; volume {{ ('%.2fx today'|format(be.volume_multiplier)) if be.volume_multiplier is not none else 'none in range' }}; AI cost per task up to {{ fmt(be.max_ai_cost_per_task) }}.</p>
<h2>Assumptions and sources</h2>
<ul class="notes">{% for n in notes %}<li>{{ n }}</li>{% endfor %}
<li>Baseline: {{ '{:,.0f}'.format(s.baseline.volume_per_month) }} tasks a month growing {{ (s.baseline.growth_per_month*100)|round(2) }}% a month, {{ s.baseline.handle_minutes }} minutes each at {{ fmt(s.baseline.loaded_cost_per_hour) }} an hour; error rate {{ fmtp(s.baseline.error_rate) }} at {{ fmt(s.baseline.cost_per_error) }} each.</li>
<li>Adoption: go-live in month {{ s.adoption.go_live_month }}, full adoption after {{ s.adoption.ramp_months }} months; {{ fmtp(s.adoption.coverage) }} of tasks to the AI; review {{ s.adoption.review_minutes }} minutes per contained task; benefit realisation {{ fmtp(s.adoption.benefit_realisation) }}.</li>
</ul>
</main></body></html>"""


def html_report(s: Scenario, results: list[engine.OptionResult], summ: dict[str, Any]) -> str:
    from . import __version__
    best = max(results, key=lambda r: r.kpis["npv"])
    bsum = next(o for o in summ["options"] if o["name"] == best.option)
    env = Environment(autoescape=True)
    return env.from_string(TEMPLATE).render(
        s=s, results=results, best=best, notes=summ.get("_notes", []) + list(s.assumptions), version=__version__,
        generated=summ["generated"], palette=PALETTE,
        chart=_line_chart([(r.option, [m["cumulative"] for m in r.months]) for r in results]),
        tornado=_tornado(bsum["tornado"], s.currency), be=bsum["break_even"],
        fmt=lambda v: _fmt(v, s.currency), fmtp=lambda v: _fmt(v, s.currency, "pct"),
        fmtm=lambda v: "not within horizon" if v is None else _fmt(v, s.currency, "month"))


def markdown_report(s: Scenario, results: list[engine.OptionResult], summ: dict[str, Any]) -> str:
    cur = s.currency
    lines = [f"# {s.name}", "", f"{s.horizon_months}-month business case in {cur}, starting {s.start_date}.", "",
             "| Option | NPV | Payback | ROI | AI cost per task | Containment |", "|---|---|---|---|---|---|"]
    for r in results:
        k = r.kpis
        pb = "not within horizon" if k["payback_month"] is None else _fmt(k["payback_month"], cur, "month")
        lines.append(f"| {r.option} | {_fmt(k['npv'], cur)} | {pb} | {_fmt(k['roi'], cur, 'pct')} | "
                     f"{_fmt(k['ai_cost_per_task'], cur)} | {_fmt(r.containment, cur, 'pct')} |")
    lines += ["", f"Human cost per task: {_fmt(results[0].kpis['human_cost_per_task'], cur)}.", "", "## Notes", ""]
    lines += [f"- {n}" for n in summ.get("_notes", []) + list(s.assumptions)]
    return "\n".join(lines) + "\n"


def export(s: Scenario, out_dir: str | Path, formats: list[str], cats: dict[str, Any] | None = None) -> dict[str, Path]:
    cats = cats if cats is not None else cat.load()
    results = engine.run(s, cats)
    summ = build_summary(s, results, cats)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    if "json" in formats:
        p = out / "result.json"
        p.write_text(json.dumps({k: v for k, v in summ.items() if not k.startswith("_")} | {"notes": summ["_notes"]},
                                indent=2, default=str), encoding="utf-8")
        written["json"] = p
    if "html" in formats:
        p = out / "report.html"
        p.write_text(html_report(s, results, summ), encoding="utf-8")
        written["html"] = p
    if "md" in formats:
        p = out / "summary.md"
        p.write_text(markdown_report(s, results, summ), encoding="utf-8")
        written["md"] = p
    if "xlsx" in formats:
        from .xlsx import build
        written["xlsx"] = build(s, results, summ, out / "business-case.xlsx")
    return written
