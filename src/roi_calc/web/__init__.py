"""The static web calculator: one self-contained HTML page with the catalog, the example scenarios and the JavaScript
engine (calc.js) embedded. Works offline and on GitHub Pages."""
from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

import yaml

from .. import catalog as cat
from ..scenario import Scenario


def _read(name: str) -> str:
    return (Path(str(resources.files("roi_calc"))) / "web" / name).read_text(encoding="utf-8")


def page(examples: dict[str, dict] | None = None, cats: dict | None = None) -> str:
    cats = cats if cats is not None else cat.load()
    ex = examples if examples is not None else builtin_examples()
    html = _read("index.html")
    safe = lambda obj: json.dumps(obj, separators=(",", ":")).replace("</", "<\\/")  # noqa: E731
    html = html.replace("/*__CALC__*/", _read("calc.js"))
    html = html.replace("/*__CATALOG__*/{}", safe(cat.to_json(cats)))
    html = html.replace("/*__EXAMPLES__*/{}", safe(ex))
    return html


def builtin_examples() -> dict[str, dict]:
    here = Path(str(resources.files("roi_calc")))
    d = here / "examples" if (here / "examples").is_dir() else here.parents[1] / "examples"
    out = {}
    for f in sorted(d.glob("*.yaml")):
        s = Scenario(**yaml.safe_load(f.read_text(encoding="utf-8")))
        out[s.name] = s.model_dump(mode="json")
    return out


def build(out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    p = out / "index.html"
    p.write_text(page(), encoding="utf-8")
    return p
