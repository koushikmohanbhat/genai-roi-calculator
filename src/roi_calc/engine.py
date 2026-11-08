"""The business case. Kept deliberately explicit: the same formulas run in the Excel workbook and the web calculator,
and tests check all three agree.

Per option, cost per AI task (USD, then x fx_usd):

    calls:    sum over calls of  share x calls x [ (1 - lc) x sum_k tokens_k x short_k + lc x sum_k tokens_k x long_k ] / 1e6
              (or share x calls x measured_cost_usd, when a call carries a measured cost)
    platform: vCPU-s / 3600 x vcpu_hour + GB-s / 3600 x gb_hour + gateway / 1000 x per_1k + memory / 1000 x per_1k
              + guardrail text units / 1000 x rate per policy + other_usd

Per month m (1..H):

    V   = V0 x (1 + g)^(m - 1)
    r   = 0 before go-live, else min(1, (m - go_live + 1) / ramp_months)
    T   = V x r x coverage          AI tasks        C = T x containment   (contained)    E = T - C   (escalated)
    H   = V - T                     human-only tasks
    baseline       = V x handle/60 x rate + V x err x cpe + fixed
    labour_ai      = (H + E) x handle/60 x rate + C x review/60 x rate
    errors_ai      = (H + E) x err x cpe + C x ai_err x cpe
    fixed_ai       = fixed - avoidable x r
    savings        = (baseline - labour_ai - errors_ai - fixed_ai) x realisation
    ai_cost        = T x cost_per_task + (platform fixed x fx, from go-live)
    other costs    = one-offs in their month + run costs from their month + maintenance (one-off total x pct / 12, from go-live)
    cash flow      = savings - ai_cost - other costs

KPIs: NPV at the monthly rate (1 + annual)^(1/12) - 1, discounting month m by (1 + rm)^m; payback = the month after the
last month with negative cumulative cash flow (0 if never negative, None if still negative at the horizon);
ROI = total cash flow / total costs; IRR (annualised) by bisection when cash flows change sign.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from . import catalog as cat
from .scenario import Option, Scenario

TOKEN_FIELDS = {"input": "input_tokens", "cached": "cached_tokens", "cache_write": "cache_write_tokens",
                "output": "output_tokens"}


@dataclass
class CallCost:
    index: int
    provider: str
    model: str
    route: str
    tier: str
    rates: cat.Rates | None
    usd_per_task: float
    measured: bool = False


@dataclass
class TaskCost:
    option: str
    calls: list[CallCost]
    platform_usd: dict[str, float]
    model_usd: float
    total_usd: float
    total: float                      # scenario currency
    platform_fixed: float             # scenario currency per month


@dataclass
class OptionResult:
    option: str
    task: TaskCost
    containment: float
    months: list[dict[str, float]]
    kpis: dict[str, Any]
    breakdown: dict[str, float] = field(default_factory=dict)


def call_cost(c, rates: cat.Rates | None) -> float:
    """USD per task for one call line."""
    if c.measured_cost_usd is not None:
        return c.share * c.calls * c.measured_cost_usd
    assert rates is not None
    short = sum(getattr(c, TOKEN_FIELDS[k]) * rates.short[k] for k in TOKEN_FIELDS)
    lc = c.long_context_share
    long = sum(getattr(c, TOKEN_FIELDS[k]) * rates.long[k] for k in TOKEN_FIELDS) if (rates.long and lc) else short
    return c.share * c.calls * ((1 - lc) * short + lc * long) / 1e6


def platform_cost(p, cats: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    if p is None:
        return out
    svc = (cats.get(p.provider) or {}).get("services") or {}

    def need(name: str) -> dict[str, Any]:
        if name not in svc:
            raise cat.CatalogError(f"{p.provider}: no service {name!r} in the catalog")
        return svc[name]
    if p.runtime and (p.runtime.vcpu_seconds or p.runtime.gb_seconds):
        r = need(f"agentcore_runtime_{p.runtime.version}")
        out["runtime"] = p.runtime.vcpu_seconds / 3600 * r["vcpu_hour"] + p.runtime.gb_seconds / 3600 * r["gb_hour"]
    if p.gateway_calls:
        out["gateway"] = p.gateway_calls / 1000 * need("agentcore_gateway")["per_1k_invocations"]
    if p.memory_events or p.memory_records:
        m = need("agentcore_memory")
        out["memory"] = p.memory_events / 1000 * m["per_1k_short_term_events"] + \
            p.memory_records / 1000 * m["per_1k_long_term_records"]
    if p.guardrails:
        g = need("guardrails")
        v = sum(getattr(p.guardrails, k) / 1000 * g[k] for k in ("content_filter", "denied_topics", "sensitive_info",
                                                                 "grounding"))
        if v:
            out["guardrails"] = v
    if p.other_usd:
        out["other"] = p.other_usd
    return out


def task_cost(s: Scenario, o: Option, cats: dict[str, Any]) -> TaskCost:
    lines = []
    for i, c in enumerate(o.calls):
        rates = None if c.measured_cost_usd is not None else cat.resolve(
            cats, c.provider, c.model, c.route, c.tier, s.start_date, s.price_overrides)
        lines.append(CallCost(i, c.provider, rates.model if rates else c.model, c.route, c.tier, rates,
                              call_cost(c, rates), c.measured_cost_usd is not None))
    plat = platform_cost(o.platform, cats)
    model_usd = sum(x.usd_per_task for x in lines)
    total_usd = model_usd + sum(plat.values())
    return TaskCost(o.name, lines, plat, model_usd, total_usd, total_usd * s.fx_usd, o.platform_fixed_usd_per_month * s.fx_usd)


def ramp(m: int, go_live: int, ramp_months: int) -> float:
    if m < go_live:
        return 0.0
    return min(1.0, (m - go_live + 1) / ramp_months)


def schedule(s: Scenario, cost_per_task: float, platform_fixed: float, containment: float,
             adj: dict[str, float] | None = None) -> list[dict[str, float]]:
    """Monthly rows. `adj` scales drivers for sensitivity (multipliers, default 1)."""
    a = {k: 1.0 for k in ("volume", "handle_minutes", "loaded_cost_per_hour", "coverage", "containment", "review_minutes",
                          "ai_cost_per_task", "one_off", "run_costs", "benefit_realisation")}
    a.update(adj or {})
    b, ad, c = s.baseline, s.adoption, s.costs
    handle, rate = b.handle_minutes * a["handle_minutes"], b.loaded_cost_per_hour * a["loaded_cost_per_hour"]
    coverage = min(1.0, ad.coverage * a["coverage"])
    contain = min(1.0, containment * a["containment"])
    review = ad.review_minutes * a["review_minutes"]
    realise = min(1.0, ad.benefit_realisation * a["benefit_realisation"])
    cpt = cost_per_task * a["ai_cost_per_task"]
    one_off_total = sum(x.amount for x in c.one_off) * a["one_off"]
    rows = []
    for m in range(1, s.horizon_months + 1):
        V = b.volume_per_month * a["volume"] * (1 + b.growth_per_month) ** (m - 1)
        r = ramp(m, ad.go_live_month, ad.ramp_months)
        T = V * r * coverage
        C = T * contain
        E = T - C
        H = V - T
        live = m >= ad.go_live_month
        baseline = V * handle / 60 * rate + V * b.error_rate * b.cost_per_error + b.fixed_per_month
        labour_ai = (H + E) * handle / 60 * rate + C * review / 60 * rate
        errors_ai = (H + E) * b.error_rate * b.cost_per_error + C * ad.ai_error_rate * b.cost_per_error
        fixed_ai = b.fixed_per_month - b.avoidable_fixed_per_month * r
        savings = (baseline - labour_ai - errors_ai - fixed_ai) * realise
        ai_cost = T * cpt + (platform_fixed if live else 0.0)
        one_off = sum(x.amount for x in c.one_off if x.month == m) * a["one_off"]
        run = sum(x.amount for x in c.run_per_month
                  if m >= (x.from_month or ad.go_live_month)) * a["run_costs"]
        maint = one_off_total * c.maintenance_pct_per_year / 12 if live else 0.0
        costs = ai_cost + one_off + run + maint
        rows.append({"month": m, "volume": V, "ramp": r, "ai_tasks": T, "contained": C, "escalated": E,
                     "human_only": H, "baseline_cost": baseline, "labour_with_ai": labour_ai,
                     "errors_with_ai": errors_ai, "fixed_with_ai": fixed_ai, "savings": savings, "ai_cost": ai_cost,
                     "one_off": one_off, "run": run, "maintenance": maint, "costs": costs, "cash_flow": savings - costs})
    cum = 0.0
    for row in rows:
        cum += row["cash_flow"]
        row["cumulative"] = cum
    return rows


def monthly_rate(annual: float) -> float:
    return (1 + annual) ** (1 / 12) - 1


def npv(cfs: list[float], annual: float) -> float:
    rm = monthly_rate(annual)
    return sum(cf / (1 + rm) ** (i + 1) for i, cf in enumerate(cfs))


def irr_annual(cfs: list[float]) -> float | None:
    if not (any(x < 0 for x in cfs) and any(x > 0 for x in cfs)):
        return None

    def f(r):
        return sum(cf / (1 + r) ** (i + 1) for i, cf in enumerate(cfs))
    lo, hi = -0.99, 1.0
    flo, fhi = f(lo), f(hi)
    while flo * fhi > 0 and hi < 1e6:
        hi *= 2
        fhi = f(hi)
    if flo * fhi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        fm = f(mid)
        if abs(fm) < 1e-9:
            break
        if flo * fm < 0:
            hi = mid
        else:
            lo, flo = mid, fm
    rm = (lo + hi) / 2
    return (1 + rm) ** 12 - 1


def payback_month(rows: list[dict[str, float]]) -> int | None:
    neg = [r["month"] for r in rows if r["cumulative"] < 0]
    if not neg:
        return 0
    last = max(neg)
    return None if last >= len(rows) else last + 1


def kpis(s: Scenario, rows: list[dict[str, float]], cost_per_task: float) -> dict[str, Any]:
    cfs = [r["cash_flow"] for r in rows]
    total_costs = sum(r["costs"] for r in rows)
    total_savings = sum(r["savings"] for r in rows)
    human_cost_per_task = s.baseline.handle_minutes / 60 * s.baseline.loaded_cost_per_hour + \
        s.baseline.error_rate * s.baseline.cost_per_error
    return {"npv": npv(cfs, s.discount_rate_annual), "total_cash_flow": sum(cfs), "total_savings": total_savings,
            "total_costs": total_costs, "roi": (sum(cfs) / total_costs) if total_costs else None,
            "payback_month": payback_month(rows), "irr_annual": irr_annual(cfs),
            "ai_cost_per_task": cost_per_task, "human_cost_per_task": human_cost_per_task,
            "steady_state_monthly_cash_flow": cfs[-1] if cfs else 0.0}


def run_option(s: Scenario, o: Option, cats: dict[str, Any]) -> OptionResult:
    tc = task_cost(s, o, cats)
    contain = o.containment if o.containment is not None else s.adoption.containment
    rows = schedule(s, tc.total, tc.platform_fixed, contain)
    k = kpis(s, rows, tc.total)
    breakdown = {"savings": k["total_savings"], "ai_usage": sum(r["ai_cost"] for r in rows),
                 "one_off": sum(r["one_off"] for r in rows), "run": sum(r["run"] for r in rows),
                 "maintenance": sum(r["maintenance"] for r in rows)}
    return OptionResult(o.name, tc, contain, rows, k, breakdown)


def run(s: Scenario, cats: dict[str, Any] | None = None) -> list[OptionResult]:
    cats = cats if cats is not None else cat.load()
    return [run_option(s, o, cats) for o in s.options]


# sensitivity ----------------------------------------------------------------------------------------------------------
def tornado(s: Scenario, res: OptionResult) -> list[dict[str, Any]]:
    base = res.kpis["npv"]
    out = []
    for d in s.sensitivity.drivers:
        vals = {}
        for sign in (-1, 1):
            rows = schedule(s, res.task.total, res.task.platform_fixed, res.containment, {d: 1 + sign * s.sensitivity.pct})
            vals[sign] = npv([r["cash_flow"] for r in rows], s.discount_rate_annual)
        out.append({"driver": d, "low": vals[-1], "high": vals[1], "swing": abs(vals[1] - vals[-1]), "base": base})
    return sorted(out, key=lambda x: -x["swing"])


def _solve(f, lo: float, hi: float) -> float | None:
    flo, fhi = f(lo), f(hi)
    if flo == 0:
        return lo
    if flo * fhi > 0:
        return None
    for _ in range(100):
        mid = (lo + hi) / 2
        fm = f(mid)
        if flo * fm <= 0:
            hi = mid
        else:
            lo, flo = mid, fm
    return (lo + hi) / 2


def break_even(s: Scenario, res: OptionResult) -> dict[str, float | None]:
    def npv_with(**adj):
        rows = schedule(s, res.task.total, res.task.platform_fixed, res.containment, adj)
        return npv([r["cash_flow"] for r in rows], s.discount_rate_annual)
    c = res.containment
    contain = _solve(lambda x: npv_with(containment=x / c) if c else -1, 0.0, 1.0) if c else None
    vol = _solve(lambda x: npv_with(volume=x), 0.0, 100.0)
    cpt = _solve(lambda x: npv_with(ai_cost_per_task=x), 0.0, 1e6) if res.task.total else None
    return {"containment": contain, "volume_multiplier": vol,
            "max_ai_cost_per_task": (cpt * res.task.total) if cpt is not None else None}


def summary(s: Scenario, results: list[OptionResult]) -> dict[str, Any]:
    """The JSON result (schema roi-calc/result 1.0)."""
    from . import __version__
    cats_used = sorted({c.rates.as_of for r in results for c in r.task.calls if c.rates})
    return {
        "schema": "roi-calc/result", "schema_version": "1.0", "calculator_version": __version__,
        "scenario": s.name, "currency": s.currency, "fx_usd": s.fx_usd, "start_date": s.start_date.isoformat(),
        "horizon_months": s.horizon_months, "discount_rate_annual": s.discount_rate_annual,
        "generated": date.today().isoformat(), "price_dates": cats_used,
        "options": [{
            "name": r.option, "containment": r.containment, "kpis": r.kpis, "breakdown": r.breakdown,
            "task_cost": {"total": r.task.total, "total_usd": r.task.total_usd, "model_usd": r.task.model_usd,
                          "platform_usd": r.task.platform_usd, "platform_fixed_per_month": r.task.platform_fixed,
                          "calls": [{"provider": c.provider, "model": c.model, "route": c.route, "tier": c.tier,
                                     "usd_per_task": c.usd_per_task, "measured": c.measured,
                                     "rates": c.rates.as_dict() if c.rates else None} for c in r.task.calls]},
            "tornado": tornado(s, r), "break_even": break_even(s, r), "months": r.months,
        } for r in results],
        "assumptions": s.assumptions,
    }

