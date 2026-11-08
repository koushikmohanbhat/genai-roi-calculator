"""roi: the GenAI ROI and TCO calculator.

  roi init [DIR]                                  example scenarios to start from
  roi run SCENARIO [--out DIR] [--format ...]     business case: html, md, xlsx, json (default: all)
  roi compare SCENARIO                            options side by side in the terminal
  roi sensitivity SCENARIO [--option NAME]        NPV tornado and break-even points
  roi import-evals RESULT --grader G [--into SCENARIO --out FILE] [--target T] [--model-map A=provider:model]
                                                  workload options from a GenAI Eval Framework (4.1) result
  roi prices [--provider P] [--model M] [--route R] [--tier T] [--check]
                                                  resolved rates; --check lists catalog issues
  roi web [--out DIR]                             the static web calculator (index.html)
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import date
from importlib import resources
from pathlib import Path

import yaml

from . import __version__
from . import catalog as cat


def _cats(a) -> dict:
    return cat.load([Path(d) for d in (a.catalog or [])])


def _scenario(path: str):
    from .scenario import load_scenario
    return load_scenario(path)


def cmd_init(a) -> int:
    here = Path(str(resources.files("roi_calc")))
    src = here / "examples" if (here / "examples").is_dir() else here.parents[1] / "examples"
    dest = Path(a.dir)
    dest.mkdir(parents=True, exist_ok=True)
    for f in sorted(src.glob("*.yaml")):
        target = dest / f.name
        if target.exists() and not a.force:
            print(f"skip {target} (exists)")
            continue
        shutil.copy(f, target)
        print(f"wrote {target}")
    print(f"next: roi run {dest / 'claims-intake-inr.yaml'} --out {dest / 'out'}")
    return 0


def cmd_run(a) -> int:
    from .report import export
    s = _scenario(a.scenario)
    formats = [f.strip() for f in a.format.split(",") if f.strip()]
    written = export(s, a.out, formats, _cats(a))
    for k, p in written.items():
        print(f"{k:5} {p}")
    return 0


def _money(v, cur):
    return "n/a" if v is None else f"{cur} {v:,.0f}" if abs(v) >= 100 else f"{cur} {v:,.4f}"


def cmd_compare(a) -> int:
    from . import engine
    s = _scenario(a.scenario)
    res = engine.run(s, _cats(a))
    w = max(len(r.option) for r in res)
    print(f"{'Option':{w}}  {'NPV':>18}  {'Payback':>9}  {'ROI':>8}  {'AI/task':>14}  {'USD/task':>10}  Contain")
    for r in sorted(res, key=lambda x: -x.kpis["npv"]):
        k = r.kpis
        pb = "never" if k["payback_month"] is None else str(k["payback_month"])
        roi = "n/a" if k["roi"] is None else f"{k['roi'] * 100:.1f}%"
        print(f"{r.option:{w}}  {_money(k['npv'], s.currency):>18}  {pb:>9}  {roi:>8}  "
              f"{_money(k['ai_cost_per_task'], s.currency):>14}  {r.task.total_usd:>10.5f}  {r.containment:.0%}")
    print(f"\nHuman cost per task: {_money(res[0].kpis['human_cost_per_task'], s.currency)}")
    return 0


def cmd_sensitivity(a) -> int:
    from . import engine
    s = _scenario(a.scenario)
    res = engine.run(s, _cats(a))
    r = next((x for x in res if x.option == a.option), None) if a.option else max(res, key=lambda x: x.kpis["npv"])
    if r is None:
        print(f"no option {a.option!r}")
        return 2
    print(f"{r.option}: NPV {_money(r.kpis['npv'], s.currency)}; each driver +/-{s.sensitivity.pct:.0%}")
    for t in engine.tornado(s, r):
        print(f"  {t['driver']:22} {_money(t['low'], s.currency):>18}  {_money(t['high'], s.currency):>18}")
    be = engine.break_even(s, r)
    c, v = be["containment"], be["volume_multiplier"]
    print("break-even containment: " + ("none in range" if c is None else f"{c:.1%}"))
    print("break-even volume: " + ("none in range" if v is None else f"{v:.2f}x today"))
    print(f"max AI cost per task at break-even: {_money(be['max_ai_cost_per_task'], s.currency)}")
    return 0


def cmd_import(a) -> int:
    from . import evals_import as ei
    mm = {}
    for x in a.model_map or []:
        k, _, v = x.partition("=")
        mm[k] = v
    result = ei.load_result(a.result)
    opts = ei.workloads(result, a.grader, a.target or None, mm, _cats(a), a.route, a.conservative)
    if a.into:
        scenario = yaml.safe_load(Path(a.into).read_text(encoding="utf-8"))
        merged = ei.merge_into(scenario, opts, a.replace)
        from .scenario import Scenario
        Scenario(**merged)
        out = Path(a.out or a.into)
        out.write_text(yaml.safe_dump(merged, sort_keys=False, allow_unicode=True), encoding="utf-8")
        print(f"wrote {len(opts)} option(s) into {out}")
    else:
        print(yaml.safe_dump({"options": opts}, sort_keys=False, allow_unicode=True))
    return 0


def cmd_prices(a) -> int:
    cats = _cats(a)
    on = date.fromisoformat(a.on) if a.on else date.today()
    if a.check:
        issues = cat.check(cats, on)
        for i in issues:
            print(f"- {i}")
        print(f"{len(issues)} item(s) to review")
        return 0
    for pid, c in cats.items():
        if a.provider and pid != a.provider:
            continue
        print(f"{c.get('label', pid)}  (as of {c['as_of']}, {c['source']})")
        for mid, m in c["models"].items():
            if a.model and a.model not in (mid, *(m.get("aliases") or [])):
                continue
            routes = [a.route] if a.route else m["routes"]
            tiers = [a.tier] if a.tier else m["tiers"]
            for r in routes:
                for t in tiers:
                    try:
                        x = cat.resolve(cats, pid, mid, r, t, on)
                    except cat.CatalogError as e:
                        print(f"  {mid:30} {r:9} {t:9} {e}")
                        continue
                    sh = x.short
                    print(f"  {mid:30} {r:9} {t:9} in {sh['input']:>8.4f}  cached {sh['cached']:>8.4f}  "
                          f"write {sh['cache_write']:>8.4f}  out {sh['output']:>8.4f}{'  [verify]' if x.verify else ''}")
    return 0


def cmd_web(a) -> int:
    from .web import build
    print(f"wrote {build(a.out)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="roi", description="GenAI ROI and TCO calculator")
    ap.add_argument("--version", action="version", version=f"genai-roi-calculator {__version__}")
    ap.add_argument("--catalog", action="append", help="extra catalog folder (replaces providers with the same id)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init")
    p.add_argument("dir", nargs="?", default="roi-scenarios")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_init)
    p = sub.add_parser("run")
    p.add_argument("scenario")
    p.add_argument("--out", default="out")
    p.add_argument("--format", default="html,md,xlsx,json")
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("compare")
    p.add_argument("scenario")
    p.set_defaults(fn=cmd_compare)
    p = sub.add_parser("sensitivity")
    p.add_argument("scenario")
    p.add_argument("--option")
    p.set_defaults(fn=cmd_sensitivity)
    p = sub.add_parser("import-evals")
    p.add_argument("result")
    p.add_argument("--grader", help="grader whose pass rate becomes the option's containment")
    p.add_argument("--target", action="append", help="only these targets / variants")
    p.add_argument("--model-map", action="append", help="model-id=provider:model, for ids not in the catalog")
    p.add_argument("--route", default="global")
    p.add_argument("--conservative", action="store_true", help="p95 tokens and the grader's CI low")
    p.add_argument("--into", help="scenario file to add the options to")
    p.add_argument("--out", help="where to write the merged scenario (default: --into)")
    p.add_argument("--replace", action="store_true", help="replace the scenario's options instead of adding")
    p.set_defaults(fn=cmd_import)
    p = sub.add_parser("prices")
    p.add_argument("--provider")
    p.add_argument("--model")
    p.add_argument("--route")
    p.add_argument("--tier")
    p.add_argument("--on", help="date for promotions (YYYY-MM-DD, default today)")
    p.add_argument("--check", action="store_true")
    p.set_defaults(fn=cmd_prices)
    p = sub.add_parser("web")
    p.add_argument("--out", default="site")
    p.set_defaults(fn=cmd_web)
    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except (cat.CatalogError, ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

