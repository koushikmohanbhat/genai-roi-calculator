"""Import measured workloads from a GenAI Eval Framework (4.1) result file.

For each target (or experiment variant) in `result.json` (schema `genai-evals/result` 1.x):
  - tokens per task: samples are averaged over repeats per case, then over cases (mean and p95).
    `input_tokens` in 4.1 includes cached tokens, so fresh input = input - cached. Reasoning tokens are counted inside
    output tokens (the OpenAI convention) and are not added again.
  - measured cost: when samples carry `cost_usd` but no token counts, the mean becomes `measured_cost_usd`.
  - quality: the chosen grader's mean (and CI low) becomes the option's containment, labelled with its source.
  - the model id is matched to the catalog by id or alias, or mapped with `model_map`.

Eval pass rates are measured on a test set, not in production: reports say so next to any imported containment.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

from . import catalog as cat


class ImportErrorEvals(ValueError):
    pass


def _p95(xs: list[float]) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    k = 0.95 * (len(xs) - 1)
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def _match_model(cats: dict[str, Any], model: str | None, model_map: dict[str, str]) -> tuple[str, str] | None:
    if model and model in model_map:
        ref = model_map[model]
        provider, _, mid = ref.partition(":")
        if not mid:
            raise ImportErrorEvals(f"model_map value {ref!r}: expected provider:model")
        cat.find_model(cats, provider, mid)
        return provider, mid
    if not model:
        return None
    for provider in cats:
        try:
            mid, _ = cat.find_model(cats, provider, model)
            return provider, mid
        except cat.CatalogError:
            continue
    return None


def load_result(path: str | Path) -> dict[str, Any]:
    r = json.loads(Path(path).read_text(encoding="utf-8"))
    if r.get("schema") != "genai-evals/result" or not str(r.get("schema_version", "")).startswith("1."):
        raise ImportErrorEvals(f"{path}: not a genai-evals result file (schema genai-evals/result 1.x)")
    return r


def workloads(result: dict[str, Any], grader: str | None = None, targets: list[str] | None = None,
              model_map: dict[str, str] | None = None, cats: dict[str, Any] | None = None,
              default_route: str = "global", conservative: bool = False) -> list[dict[str, Any]]:
    cats = cats if cats is not None else cat.load()
    model_map = model_map or {}
    names = [t["name"] for t in result["targets"]]
    for t in targets or []:
        if t not in names:
            raise ImportErrorEvals(f"target {t!r} not in the result (has: {', '.join(names)})")
    out = []
    for name in targets or names:
        per_case: dict[str, list[dict[str, Any]]] = {}
        for s in result["samples"]:
            if s["target"] == name:
                per_case.setdefault(s["case_id"], []).append(s)
        if not per_case:
            continue
        rows = []
        for samples in per_case.values():
            u = [x.get("usage") or {} for x in samples]
            rows.append({
                "input": statistics.mean(float(x.get("input_tokens", 0)) for x in u),
                "cached": statistics.mean(float(x.get("cached_tokens", 0)) for x in u),
                "output": statistics.mean(float(x.get("output_tokens", 0)) for x in u),
                "cost": statistics.mean(float(x["cost_usd"]) for x in samples if x.get("cost_usd") is not None)
                if any(x.get("cost_usd") is not None for x in samples) else None,
                "latency": statistics.mean(float(x["latency_ms"]) for x in samples if x.get("latency_ms") is not None)
                if any(x.get("latency_ms") is not None for x in samples) else None,
                "model": next((x.get("model") for x in samples if x.get("model")), None),
            })
        pick = _p95 if conservative else statistics.mean
        inp = pick([r["input"] for r in rows])
        cached = pick([r["cached"] for r in rows])
        output = pick([r["output"] for r in rows])
        costs = [r["cost"] for r in rows if r["cost"] is not None]
        model = next((r["model"] for r in rows if r["model"]), None)
        matched = _match_model(cats, model, model_map)
        call: dict[str, Any] = {}
        if inp or output:
            if matched is None:
                raise ImportErrorEvals(f"target {name}: model {model!r} is not in the catalog; pass model_map "
                                       f"(e.g. {model or 'model-id'}=bedrock:openai.gpt-6.1-sol)")
            call = {"provider": matched[0], "model": matched[1], "route": default_route, "calls": 1,
                    "input_tokens": round(max(inp - cached, 0.0), 1), "cached_tokens": round(cached, 1),
                    "output_tokens": round(output, 1)}
        elif costs:
            call = {"provider": matched[0] if matched else "measured", "model": matched[1] if matched else (model or name),
                    "calls": 1, "measured_cost_usd": round(pick(costs), 6)}
        else:
            raise ImportErrorEvals(f"target {name}: samples have neither token usage nor cost_usd")
        call["note"] = (f"from 4.1 run {result.get('run_id')} ({len(rows)} cases, "
                        f"{'p95' if conservative else 'mean'} per task)")
        opt: dict[str, Any] = {"name": name, "description": f"Imported from 4.1 result {result.get('run_id')}",
                               "calls": [call]}
        if grader:
            g = ((result.get("summary") or {}).get(name) or {}).get("graders", {}).get(grader)
            if g is None or g.get("mean") is None:
                raise ImportErrorEvals(f"target {name}: grader {grader!r} has no mean in the result summary")
            value = g.get("ci_low") if conservative and g.get("ci_low") is not None else g["mean"]
            opt["containment"] = round(float(max(0.0, min(1.0, value))), 4)
            opt["containment_source"] = (f"4.1 {grader} {'CI low' if conservative and g.get('ci_low') is not None else 'mean'}"
                                         f" over {g.get('n')} cases (test set, not production)")
        lat = [r["latency"] for r in rows if r["latency"] is not None]
        if lat:
            opt["description"] += f"; mean latency {statistics.mean(lat):.0f} ms, p95 {_p95(lat):.0f} ms"
        out.append(opt)
    if not out:
        raise ImportErrorEvals("no samples for the selected targets")
    return out


def merge_into(scenario: dict[str, Any], options: list[dict[str, Any]], replace: bool = False) -> dict[str, Any]:
    s = dict(scenario)
    existing = [] if replace else list(s.get("options") or [])
    names = {o["name"] for o in options}
    s["options"] = [o for o in existing if o.get("name") not in names] + options
    return s
