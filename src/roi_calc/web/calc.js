/* genai-roi-calculator engine, JavaScript port of roi_calc/engine.py and roi_calc/catalog.py (resolve).
   Same formulas; tests run both on the same scenarios and require them to agree. Works in browsers and Node. */
(function (root) {
  "use strict";
  const KINDS = ["input", "cached", "cache_write", "output"];
  const TOK = { input: "input_tokens", cached: "cached_tokens", cache_write: "cache_write_tokens", output: "output_tokens" };
  const DRIVERS = ["volume", "handle_minutes", "loaded_cost_per_hour", "coverage", "containment", "review_minutes",
    "ai_cost_per_task", "one_off", "run_costs", "benefit_realisation"];

  function findModel(cats, provider, model) {
    const cat = cats[provider];
    if (!cat) throw new Error("unknown provider " + provider);
    if (cat.models[model]) return [model, cat.models[model]];
    for (const [mid, m] of Object.entries(cat.models)) if ((m.aliases || []).includes(model)) return [mid, m];
    throw new Error(provider + ": unknown model " + model);
  }

  function round10(x) { return Math.round(x * 1e10) / 1e10; }

  function resolve(cats, provider, model, route, tier, onDate, overrides) {
    route = route || "global"; tier = tier || "standard";
    const [mid, m] = findModel(cats, provider, model);
    const cat = cats[provider];
    if (!m.tiers.includes(tier)) throw new Error(provider + " " + mid + ": tier " + tier + " is not supported");
    if (!m.routes.includes(route)) throw new Error(provider + " " + mid + ": route " + route + " is not supported");
    const base = Object.assign({}, m.rates);
    const on = onDate || new Date().toISOString().slice(0, 10);
    for (const p of (m.promos || [])) { if (on <= String(p.valid_until)) { Object.assign(base, p.rates); break; } }
    for (const o of (overrides || [])) {
      if (o.provider === provider && (o.model === mid || o.model === model)) {
        if ((o.route != null && o.route !== route) || (o.tier != null && o.tier !== tier)) continue;
        if (o.final) {
          const short = {}; for (const k of KINDS) short[k] = Number(o.rates[k] != null ? o.rates[k] : base[k]);
          return { model: mid, label: m.label || mid, short, long: null };
        }
        for (const [k, v] of Object.entries(o.rates)) base[k] = Number(v);
      }
    }
    const rm = Number(((m.route_multipliers || {})[route]) != null ? m.route_multipliers[route] : ((cat.routes[route] || {}).multiplier != null ? cat.routes[route].multiplier : 1));
    const tm = Number(((m.tier_multipliers || {})[tier]) != null ? m.tier_multipliers[tier] : ((cat.tiers[tier] || {}).multiplier != null ? cat.tiers[tier].multiplier : 1));
    const short = {}; for (const k of KINDS) short[k] = round10(Number(base[k]) * rm * tm);
    const lc = ("long_context" in m) ? m.long_context : cat.long_context;
    let long = null;
    if (lc) { long = {}; for (const k of KINDS) long[k] = round10(short[k] * Number(lc[k])); }
    return { model: mid, label: m.label || mid, short, long };
  }

  function n(v, d) { return v == null ? d : Number(v); }

  function callCost(c, rates) {
    const share = n(c.share, 1), calls = n(c.calls, 1);
    if (c.measured_cost_usd != null) return share * calls * Number(c.measured_cost_usd);
    let short = 0; for (const k of KINDS) short += n(c[TOK[k]], 0) * rates.short[k];
    const lc = n(c.long_context_share, 0);
    let long = short;
    if (rates.long && lc) { long = 0; for (const k of KINDS) long += n(c[TOK[k]], 0) * rates.long[k]; }
    return share * calls * ((1 - lc) * short + lc * long) / 1e6;
  }

  function platformCost(p, cats) {
    const out = {};
    if (!p) return out;
    const prov = p.provider || "bedrock";
    const svc = (cats[prov] || {}).services || {};
    const need = (name) => { if (!svc[name]) throw new Error(prov + ": no service " + name); return svc[name]; };
    const rt = p.runtime;
    if (rt && (n(rt.vcpu_seconds, 0) || n(rt.gb_seconds, 0))) {
      const r = need("agentcore_runtime_" + (rt.version || "v2"));
      out.runtime = n(rt.vcpu_seconds, 0) / 3600 * r.vcpu_hour + n(rt.gb_seconds, 0) / 3600 * r.gb_hour;
    }
    if (n(p.gateway_calls, 0)) out.gateway = n(p.gateway_calls, 0) / 1000 * need("agentcore_gateway").per_1k_invocations;
    if (n(p.memory_events, 0) || n(p.memory_records, 0)) {
      const m = need("agentcore_memory");
      out.memory = n(p.memory_events, 0) / 1000 * m.per_1k_short_term_events + n(p.memory_records, 0) / 1000 * m.per_1k_long_term_records;
    }
    if (p.guardrails) {
      const g = need("guardrails"); let v = 0;
      for (const k of ["content_filter", "denied_topics", "sensitive_info", "grounding"]) v += n(p.guardrails[k], 0) / 1000 * g[k];
      if (v) out.guardrails = v;
    }
    if (n(p.other_usd, 0)) out.other = n(p.other_usd, 0);
    return out;
  }

  function taskCost(s, o, cats) {
    const lines = (o.calls || []).map((c) => {
      const rates = c.measured_cost_usd != null ? null : resolve(cats, c.provider, c.model, c.route, c.tier, s.start_date, s.price_overrides);
      return { model: rates ? rates.model : c.model, label: rates ? rates.label : c.model + " (measured)", usd: callCost(c, rates) };
    });
    const plat = platformCost(o.platform, cats);
    const modelUsd = lines.reduce((a, x) => a + x.usd, 0);
    const totalUsd = modelUsd + Object.values(plat).reduce((a, x) => a + x, 0);
    return { lines, platform: plat, modelUsd, totalUsd, total: totalUsd * s.fx_usd,
      platformFixed: n(o.platform_fixed_usd_per_month, 0) * s.fx_usd };
  }

  function ramp(m, goLive, rampMonths) { return m < goLive ? 0 : Math.min(1, (m - goLive + 1) / rampMonths); }

  function schedule(s, cpt, platformFixed, containment, adj) {
    const a = {}; for (const d of DRIVERS) a[d] = 1; Object.assign(a, adj || {});
    const b = s.baseline, ad = s.adoption, c = s.costs || {};
    const oneOffs = c.one_off || [], runs = c.run_per_month || [];
    const handle = b.handle_minutes * a.handle_minutes, rate = b.loaded_cost_per_hour * a.loaded_cost_per_hour;
    const coverage = Math.min(1, ad.coverage * a.coverage), contain = Math.min(1, containment * a.containment);
    const review = n(ad.review_minutes, 0) * a.review_minutes, realise = Math.min(1, n(ad.benefit_realisation, 1) * a.benefit_realisation);
    const goLive = n(ad.go_live_month, 1), rampMonths = n(ad.ramp_months, 1);
    const err = n(b.error_rate, 0), cpe = n(b.cost_per_error, 0), fixed = n(b.fixed_per_month, 0), avoid = n(b.avoidable_fixed_per_month, 0);
    const aiErr = n(ad.ai_error_rate, 0), maintPct = n(c.maintenance_pct_per_year, 0);
    const oneOffTotal = oneOffs.reduce((x, y) => x + y.amount, 0) * a.one_off;
    const rows = []; let cum = 0;
    for (let m = 1; m <= s.horizon_months; m++) {
      const V = b.volume_per_month * a.volume * Math.pow(1 + n(b.growth_per_month, 0), m - 1);
      const r = ramp(m, goLive, rampMonths);
      const T = V * r * coverage, C = T * contain, E = T - C, H = V - T, live = m >= goLive;
      const baseline = V * handle / 60 * rate + V * err * cpe + fixed;
      const labour = (H + E) * handle / 60 * rate + C * review / 60 * rate;
      const errors = (H + E) * err * cpe + C * aiErr * cpe;
      const fixedAi = fixed - avoid * r;
      const savings = (baseline - labour - errors - fixedAi) * realise;
      const aiCost = T * cpt * a.ai_cost_per_task + (live ? platformFixed : 0);
      const oneOff = oneOffs.filter((x) => n(x.month, 1) === m).reduce((x, y) => x + y.amount, 0) * a.one_off;
      const run = runs.filter((x) => m >= (x.from_month != null ? x.from_month : goLive)).reduce((x, y) => x + y.amount, 0) * a.run_costs;
      const maint = live ? oneOffTotal * maintPct / 12 : 0;
      const costs = aiCost + oneOff + run + maint;
      cum += savings - costs;
      rows.push({ month: m, volume: V, ramp: r, ai_tasks: T, contained: C, escalated: E, human_only: H, baseline_cost: baseline,
        labour_with_ai: labour, errors_with_ai: errors, fixed_with_ai: fixedAi, savings, ai_cost: aiCost, one_off: oneOff,
        run, maintenance: maint, costs, cash_flow: savings - costs, cumulative: cum });
    }
    return rows;
  }

  function monthlyRate(annual) { return Math.pow(1 + annual, 1 / 12) - 1; }
  function npv(cfs, annual) { const rm = monthlyRate(annual); return cfs.reduce((a, cf, i) => a + cf / Math.pow(1 + rm, i + 1), 0); }
  function irrAnnual(cfs) {
    if (!(cfs.some((x) => x < 0) && cfs.some((x) => x > 0))) return null;
    const f = (r) => cfs.reduce((a, cf, i) => a + cf / Math.pow(1 + r, i + 1), 0);
    let lo = -0.99, hi = 1.0, flo = f(lo), fhi = f(hi);
    while (flo * fhi > 0 && hi < 1e6) { hi *= 2; fhi = f(hi); }
    if (flo * fhi > 0) return null;
    for (let i = 0; i < 200; i++) {
      const mid = (lo + hi) / 2, fm = f(mid);
      if (Math.abs(fm) < 1e-9) break;
      if (flo * fm < 0) hi = mid; else { lo = mid; flo = fm; }
    }
    return Math.pow(1 + (lo + hi) / 2, 12) - 1;
  }
  function payback(rows) {
    const neg = rows.filter((r) => r.cumulative < 0).map((r) => r.month);
    if (!neg.length) return 0;
    const last = Math.max(...neg);
    return last >= rows.length ? null : last + 1;
  }

  function kpis(s, rows, cpt) {
    const cfs = rows.map((r) => r.cash_flow);
    const totalCosts = rows.reduce((a, r) => a + r.costs, 0);
    const total = cfs.reduce((a, x) => a + x, 0);
    const b = s.baseline;
    return { npv: npv(cfs, s.discount_rate_annual), total_cash_flow: total, total_savings: rows.reduce((a, r) => a + r.savings, 0),
      total_costs: totalCosts, roi: totalCosts ? total / totalCosts : null, payback_month: payback(rows),
      irr_annual: irrAnnual(cfs), ai_cost_per_task: cpt,
      human_cost_per_task: b.handle_minutes / 60 * b.loaded_cost_per_hour + n(b.error_rate, 0) * n(b.cost_per_error, 0),
      steady_state_monthly_cash_flow: cfs.length ? cfs[cfs.length - 1] : 0 };
  }

  function tornado(s, opt, tc, containment) {
    const pct = (s.sensitivity && s.sensitivity.pct) || 0.2;
    const drivers = (s.sensitivity && s.sensitivity.drivers) || ["volume", "handle_minutes", "loaded_cost_per_hour", "coverage",
      "containment", "ai_cost_per_task", "one_off", "run_costs"];
    const base = npv(schedule(s, tc.total, tc.platformFixed, containment).map((r) => r.cash_flow), s.discount_rate_annual);
    return drivers.map((d) => {
      const v = {};
      for (const sign of [-1, 1]) {
        const adj = {}; adj[d] = 1 + sign * pct;
        v[sign] = npv(schedule(s, tc.total, tc.platformFixed, containment, adj).map((r) => r.cash_flow), s.discount_rate_annual);
      }
      return { driver: d, low: v[-1], high: v[1], swing: Math.abs(v[1] - v[-1]), base };
    }).sort((x, y) => y.swing - x.swing);
  }

  function prepare(s) {
    s = JSON.parse(JSON.stringify(s));
    s.currency = String(s.currency || "USD").toUpperCase();
    if (s.currency === "USD") s.fx_usd = 1;
    if (!(s.fx_usd > 0)) throw new Error("fx_usd is required when currency is " + s.currency);
    s.horizon_months = n(s.horizon_months, 36);
    s.discount_rate_annual = n(s.discount_rate_annual, 0.1);
    s.start_date = String(s.start_date);
    return s;
  }

  function run(scenario, cats) {
    const s = prepare(scenario);
    return s.options.map((o) => {
      const tc = taskCost(s, o, cats);
      const containment = o.containment != null ? o.containment : s.adoption.containment;
      const rows = schedule(s, tc.total, tc.platformFixed, containment);
      return { option: o.name, task: tc, containment, kpis: kpis(s, rows, tc.total), months: rows,
        tornado: tornado(s, o, tc, containment) };
    });
  }

  const api = { resolve, callCost, platformCost, taskCost, schedule, npv, irrAnnual, payback, kpis, run, monthlyRate };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.ROICalc = api;
})(typeof window !== "undefined" ? window : this);
