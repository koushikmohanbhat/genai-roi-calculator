import pytest

from roi_calc import engine
from roi_calc.scenario import Scenario


def small(**over):
    d = {
        "name": "hand", "currency": "USD", "start_date": "2026-12-01", "horizon_months": 3, "discount_rate_annual": 0.0,
        "baseline": {"volume_per_month": 1000, "handle_minutes": 6, "loaded_cost_per_hour": 60},
        "adoption": {"go_live_month": 1, "ramp_months": 1, "coverage": 1.0, "containment": 0.5},
        "costs": {"one_off": [{"name": "build", "amount": 3000, "month": 1}]},
        "options": [{"name": "luna", "calls": [{"provider": "openai", "model": "gpt-6-luna", "input_tokens": 1000,
                                                "output_tokens": 1000}]}],
    }
    d.update(over)
    return Scenario(**d)


def test_hand_computed_case():
    s = small()
    r = engine.run(s)[0]
    assert r.task.total_usd == pytest.approx(0.0006)           # (1000 x 0.10 + 1000 x 0.50) / 1e6
    cfs = [m["cash_flow"] for m in r.months]
    assert cfs == pytest.approx([-0.6, 2999.4, 2999.4])         # savings 3000/month, AI 0.6, build 3000 in month 1
    k = r.kpis
    assert k["npv"] == pytest.approx(5998.2)
    assert k["payback_month"] == 2
    assert k["roi"] == pytest.approx(5998.2 / 3001.8)
    assert k["human_cost_per_task"] == pytest.approx(6.0)


def test_ramp_growth_fixed_and_realisation():
    s = small(horizon_months=6, baseline={"volume_per_month": 100, "growth_per_month": 0.1, "handle_minutes": 60,
                                         "loaded_cost_per_hour": 10, "fixed_per_month": 50, "avoidable_fixed_per_month": 40},
              adoption={"go_live_month": 3, "ramp_months": 2, "coverage": 1, "containment": 1, "benefit_realisation": 0.5})
    rows = engine.run(s)[0].months
    assert [round(r["ramp"], 2) for r in rows] == [0, 0, 0.5, 1, 1, 1]
    assert rows[1]["volume"] == pytest.approx(110)
    r4 = rows[3]                                                 # full adoption: all labour and 40 of fixed saved, halved
    assert r4["savings"] == pytest.approx((r4["volume"] * 10 + 40) * 0.5)
    assert rows[0]["savings"] == 0 and rows[0]["ai_cost"] == 0


def test_irr_npv_payback():
    assert engine.irr_annual([-100, 110]) == pytest.approx(1.1 ** 12 - 1, rel=1e-6)
    assert engine.irr_annual([100, 100]) is None
    assert engine.npv([100] * 12, 0.0) == 1200
    assert engine.npv([0] * 11 + [100], 0.12) == pytest.approx(100 / 1.12)
    assert engine.payback_month([{"month": 1, "cumulative": 5}]) == 0
    assert engine.payback_month([{"month": 1, "cumulative": -5}, {"month": 2, "cumulative": -1}]) is None


def test_long_context_measured_and_platform():
    s = small(options=[
        {"name": "lc", "calls": [{"provider": "openai", "model": "gpt-6.1-sol", "input_tokens": 1e6, "long_context_share": 0.25}]},
        {"name": "measured", "calls": [{"provider": "measured", "model": "x", "calls": 2, "share": 0.5, "measured_cost_usd": 0.01}]},
        {"name": "plat", "calls": [], "platform": {"runtime": {"vcpu_seconds": 3600, "gb_seconds": 3600}, "gateway_calls": 1000,
                                                    "memory_events": 1000, "guardrails": {"content_filter": 1000}, "other_usd": 1}}])
    lc, meas, plat = engine.run(s)
    assert lc.task.total_usd == pytest.approx(0.75 * 2 + 0.25 * 4)
    assert meas.task.total_usd == pytest.approx(0.01)
    assert plat.task.platform_usd == pytest.approx({"runtime": 0.1276 + 0.0169, "gateway": 0.005, "memory": 0.25,
                                                    "guardrails": 0.15, "other": 1})


def test_currency_needs_fx():
    with pytest.raises(ValueError, match="fx_usd is required"):
        small(currency="INR")
    s = small(currency="INR", fx_usd=90)
    assert engine.run(s)[0].task.total == pytest.approx(0.0006 * 90)


def test_option_containment_and_validation():
    s = small(options=[{"name": "a", "containment": 0.9, "calls": []}, {"name": "b", "calls": []}])
    a, b = engine.run(s)
    assert a.containment == 0.9 and b.containment == 0.5 and a.kpis["npv"] > b.kpis["npv"]
    with pytest.raises(ValueError, match="unique"):
        small(options=[{"name": "a"}, {"name": "a"}])
    with pytest.raises(ValueError, match="driver"):
        small(sensitivity={"drivers": ["moon"]})


def test_sensitivity_and_break_even():
    s = small(horizon_months=12)
    r = engine.run(s)[0]
    t = engine.tornado(s, r)
    assert t[0]["swing"] >= t[-1]["swing"]
    vol = next(x for x in t if x["driver"] == "volume")
    assert vol["high"] > r.kpis["npv"] > vol["low"]
    be = engine.break_even(s, r)
    rows = engine.schedule(s, r.task.total, 0, be["containment"])
    assert engine.npv([x["cash_flow"] for x in rows], 0) == pytest.approx(0, abs=1e-3)
