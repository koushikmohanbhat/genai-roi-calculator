"""The price catalog: dated, cited rates per provider and model, with routes, tiers, long-context rules and promotions.

Rates are USD per 1M tokens for four token kinds: `input` (fresh input), `cached` (cache reads), `cache_write` and
`output` (reasoning tokens are output). A resolved rate is

    base[kind] x route multiplier x tier multiplier            (short prompts)
    ... x long_context[kind]                                    (prompts over the threshold)

A model may override the provider's route or tier multipliers, lists the tiers and routes it supports, and may carry
promotions (`promos: [{rates: {...}, valid_until: YYYY-MM-DD}]`) that apply until their end date.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

KINDS = ("input", "cached", "cache_write", "output")


class CatalogError(ValueError):
    pass


@dataclass
class Rates:
    provider: str
    model: str
    label: str
    route: str
    tier: str
    short: dict[str, float]                  # USD per 1M tokens, prompts at or below the threshold
    long: dict[str, float] | None            # prompts above the threshold, or None if the model has no long-context rule
    threshold_tokens: int | None
    source: str
    as_of: str
    verify: bool = False
    notes: list[str] = field(default_factory=list)
    override: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"provider": self.provider, "model": self.model, "label": self.label, "route": self.route,
                "tier": self.tier, "short": self.short, "long": self.long, "threshold_tokens": self.threshold_tokens,
                "source": self.source, "as_of": self.as_of, "verify": self.verify, "notes": self.notes,
                "override": self.override}


def _builtin_dir() -> Path:
    return Path(str(resources.files("roi_calc"))) / "catalog"


def load(extra_dirs: list[Path] | None = None) -> dict[str, dict[str, Any]]:
    """All catalogs by provider id. Files in extra_dirs replace built-in providers with the same id."""
    out: dict[str, dict[str, Any]] = {}
    for d in [_builtin_dir(), *(extra_dirs or [])]:
        for f in sorted(Path(d).glob("*.yaml")):
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or "provider" not in data:
                raise CatalogError(f"{f}: not a catalog (needs provider:)")
            validate(data, str(f))
            out[data["provider"]] = data
    return out


def validate(cat: dict[str, Any], where: str = "catalog") -> None:
    for k in ("provider", "as_of", "source", "routes", "tiers", "models"):
        if k not in cat:
            raise CatalogError(f"{where}: missing {k}")
    for mid, m in cat["models"].items():
        for k in ("rates", "tiers", "routes"):
            if k not in m:
                raise CatalogError(f"{where}: model {mid} missing {k}")
        missing = [k for k in KINDS if k not in m["rates"]]
        if missing:
            raise CatalogError(f"{where}: model {mid} rates missing {', '.join(missing)}")
        for t in m["tiers"]:
            if t not in cat["tiers"] and t not in m.get("tier_multipliers", {}):
                raise CatalogError(f"{where}: model {mid} tier {t} has no multiplier")
        for r in m["routes"]:
            if r not in cat["routes"] and r not in m.get("route_multipliers", {}):
                raise CatalogError(f"{where}: model {mid} route {r} has no multiplier")
        for p in m.get("promos", []) or []:
            if "valid_until" not in p or "rates" not in p:
                raise CatalogError(f"{where}: model {mid} promotion needs rates and valid_until")


def find_model(cats: dict[str, dict[str, Any]], provider: str, model: str) -> tuple[str, dict[str, Any]]:
    if provider not in cats:
        raise CatalogError(f"unknown provider {provider!r} (have: {', '.join(sorted(cats))})")
    models = cats[provider]["models"]
    if model in models:
        return model, models[model]
    for mid, m in models.items():
        if model in (m.get("aliases") or []):
            return mid, m
    raise CatalogError(f"{provider}: unknown model {model!r} (have: {', '.join(models)})")


def _as_date(v: Any) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v))


def resolve(cats: dict[str, dict[str, Any]], provider: str, model: str, route: str = "global", tier: str = "standard",
            on: date | None = None, overrides: list[dict[str, Any]] | None = None) -> Rates:
    mid, m = find_model(cats, provider, model)
    cat = cats[provider]
    if tier not in m["tiers"]:
        raise CatalogError(f"{provider} {mid}: tier {tier!r} is not supported (supported: {', '.join(m['tiers'])})")
    if route not in m["routes"]:
        raise CatalogError(f"{provider} {mid}: route {route!r} is not supported (supported: {', '.join(m['routes'])})")
    base = dict(m["rates"])
    notes = list(m.get("notes", []))
    source, as_of, verify, is_override = m.get("source", cat["source"]), str(m.get("as_of", cat["as_of"])), \
        bool(m.get("verify", False)), False
    on = on or date.today()
    for p in m.get("promos", []) or []:
        if on <= _as_date(p["valid_until"]):
            base.update(p["rates"])
            notes.append(f"promotional rate until {p['valid_until']}" + (f": {p['note']}" if p.get("note") else ""))
            break
    for o in overrides or []:
        if o.get("provider") == provider and o.get("model") in (mid, model):
            if o.get("route") not in (None, route) or o.get("tier") not in (None, tier):
                continue
            if o.get("final", False):
                short = {k: float(o["rates"].get(k, base[k])) for k in KINDS}
                return Rates(provider, mid, m.get("label", mid), route, tier, short, None, None,
                             o.get("source", "price override"), str(o.get("as_of", "")), False,
                             notes + ["final negotiated rates (no route / tier multipliers)"], True)
            base.update({k: float(v) for k, v in o["rates"].items()})
            source, as_of, verify, is_override = o.get("source", "price override"), str(o.get("as_of", "")), False, True
            notes.append("negotiated base rates from price_overrides")
    rm = float(m.get("route_multipliers", {}).get(route, cat["routes"].get(route, {}).get("multiplier", 1.0)))
    tm = float(m.get("tier_multipliers", {}).get(tier, cat["tiers"].get(tier, {}).get("multiplier", 1.0)))
    short = {k: round(float(base[k]) * rm * tm, 10) for k in KINDS}
    lc = m["long_context"] if "long_context" in m else cat.get("long_context")
    long = {k: round(short[k] * float(lc[k]), 10) for k in KINDS} if lc else None
    return Rates(provider, mid, m.get("label", mid), route, tier, short, long,
                 int(lc["threshold_tokens"]) if lc else None, source, as_of, verify, notes, is_override)


def check(cats: dict[str, dict[str, Any]], on: date | None = None) -> list[str]:
    """Catalog hygiene: missing sources, entries to verify, promotions that have ended, prices over 90 days old."""
    on = on or date.today()
    issues = []
    for pid, cat in cats.items():
        if cat.get("as_of") and (on - _as_date(cat["as_of"])).days > 90:
            issues.append(f"{pid}: prices are dated {cat['as_of']}, over 90 days ago; refresh from {cat.get('source')}")
        for mid, m in cat["models"].items():
            if not (m.get("source") or cat.get("source")):
                issues.append(f"{pid} {mid}: no source")
            if m.get("verify"):
                issues.append(f"{pid} {mid}: rates marked verify (third-party source); check against {pid}")
            for p in m.get("promos", []) or []:
                if on > _as_date(p["valid_until"]):
                    issues.append(f"{pid} {mid}: promotion ended {p['valid_until']} (list price applies)")
        for sid, s in (cat.get("services") or {}).items():
            if s.get("verify"):
                issues.append(f"{pid} service {sid}: marked verify")
    return issues


def to_json(cats: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """A JSON-safe copy (dates as strings), for the web calculator."""
    def fix(v):
        if isinstance(v, date):
            return v.isoformat()
        if isinstance(v, dict):
            return {k: fix(x) for k, x in v.items()}
        if isinstance(v, list):
            return [fix(x) for x in v]
        return v
    return fix(copy.deepcopy(cats))
