"""The three surfaces agree: Python engine, JavaScript engine (Node) and the Excel workbook (LibreOffice recalculation)."""
import json
import shutil
import subprocess
from pathlib import Path

import openpyxl
import pytest

from roi_calc import catalog, engine, report, web
from roi_calc.cli import main
from roi_calc.evals_import import ImportErrorEvals, load_result, merge_into, workloads
from roi_calc.scenario import Scenario, load_scenario

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = sorted((ROOT / "examples").glob("*.yaml"))
FIX = Path(__file__).parent / "fixtures"
JS = ROOT / "src" / "roi_calc" / "web" / "calc.js"


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_js_engine_matches_python(path):
    cats = catalog.load()
    s = load_scenario(path)
    py = engine.run(s, cats)
    code = (f"const c=require({json.dumps(str(JS))});let d='';process.stdin.on('data',x=>d+=x).on('end',()=>{{"
            "const p=JSON.parse(d);console.log(JSON.stringify(c.run(p.s,p.c).map(r=>({k:r.kpis,t:r.task.total,"
            "m:r.months.map(x=>x.cash_flow),top:r.tornado.map(x=>[x.driver,x.low,x.high])}))))})")
    out = subprocess.run(["node", "-e", code], input=json.dumps({"s": s.model_dump(mode="json"), "c": catalog.to_json(cats)}),
                         capture_output=True, text=True, check=True)
    for p, j in zip(py, json.loads(out.stdout), strict=True):
        assert j["t"] == pytest.approx(p.task.total, rel=1e-12)
        assert j["m"] == pytest.approx([m["cash_flow"] for m in p.months], rel=1e-9, abs=1e-6)
        for key in ("npv", "roi", "total_costs", "total_savings"):
            assert j["k"][key] == pytest.approx(p.kpis[key], rel=1e-9)
        assert j["k"]["payback_month"] == p.kpis["payback_month"]
        assert j["k"]["irr_annual"] == pytest.approx(p.kpis["irr_annual"], rel=1e-6)
        pt = engine.tornado(s, p)
        jt = {d: (lo, hi) for d, lo, hi in j["top"]}
        for x in pt:
            assert jt[x["driver"]] == pytest.approx((x["low"], x["high"]), rel=1e-9)


@pytest.mark.skipif(not shutil.which("soffice"), reason="LibreOffice not installed")
@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_workbook_formulas_match_python(path, tmp_path):
    s = load_scenario(path)
    written = report.export(s, tmp_path / "out", ["xlsx"])
    subprocess.run(["soffice", "--headless", "--calc", "--convert-to", "xlsx", "--outdir", str(tmp_path / "re"),
                    str(written["xlsx"])], check=True, capture_output=True, timeout=180)
    ws = openpyxl.load_workbook(tmp_path / "re" / "business-case.xlsx", data_only=True)["Summary"]
    rows = {r[0]: r[1:] for r in ws.iter_rows(min_row=5, max_row=16, values_only=True) if r[0]}
    for i, res in enumerate(engine.run(s)):
        assert rows["NPV"][i] == pytest.approx(res.kpis["npv"], rel=1e-9)
        assert rows["Total costs"][i] == pytest.approx(res.kpis["total_costs"], rel=1e-9)
        assert rows["ROI (cash flow / costs)"][i] == pytest.approx(res.kpis["roi"], rel=1e-9)
        pb = res.kpis["payback_month"]
        assert rows["Payback month"][i] == (pb if pb is not None else "not within horizon")
        assert rows["IRR (annualised)"][i] == pytest.approx(res.kpis["irr_annual"], rel=1e-5)
        assert rows[f"AI cost per task ({s.currency})"][i] == pytest.approx(res.task.total, rel=1e-9)


def test_reports_and_json(tmp_path):
    s = load_scenario(ROOT / "examples" / "claims-intake-inr.yaml")
    w = report.export(s, tmp_path, ["html", "md", "json"])
    html = w["html"].read_text()
    assert "Options compared" in html and "<svg" in html and "check against the Amazon Bedrock price page" in html
    data = json.loads(w["json"].read_text())
    assert data["schema"] == "roi-calc/result" and len(data["options"]) == 4 and data["notes"]
    assert "| Option | NPV |" in w["md"].read_text()


def test_web_page_embeds_everything(tmp_path):
    p = web.build(tmp_path)
    t = p.read_text()
    assert "ROICalc" in t and "/*__CATALOG__*/" not in t and "openai.gpt-6.1-sol" in t and "Claims intake agent" in t


def test_import_experiment_measured_cost_and_containment():
    r = load_result(FIX / "evals-experiment.json")
    opts = workloads(r, grader="task_success")
    assert [o["name"] for o in opts] == ["prod-1.3.2", "prompt-1.4.0", "fast-model"]
    assert opts[2]["calls"][0]["measured_cost_usd"] == pytest.approx(0.001852, rel=1e-3)
    assert opts[0]["containment"] == 0.75 and "not production" in opts[0]["containment_source"]
    cons = workloads(r, grader="task_success", conservative=True)
    assert cons[0]["containment"] <= 0.75


def test_import_tokens_with_model_map():
    r = load_result(FIX / "evals-online.json")
    with pytest.raises(ImportErrorEvals, match="model_map"):
        workloads(r, targets=["claims-agent-aws"])
    mm = {"anthropic.claude-sonnet-v1": "bedrock:anthropic.claude-sonnet-5-5"}
    o = workloads(r, targets=["claims-agent-aws"], model_map=mm)[0]
    c = o["calls"][0]
    assert c["provider"] == "bedrock" and c["model"] == "anthropic.claude-sonnet-5-5" and c["input_tokens"] > 3000
    base = load_scenario(ROOT / "examples" / "it-helpdesk-usd.yaml").model_dump(mode="json")
    merged = merge_into(base, [o])
    assert len(Scenario(**merged).options) == 3


def test_cli(tmp_path, capsys):
    assert main(["init", str(tmp_path / "s")]) == 0
    sc = tmp_path / "s" / "it-helpdesk-usd.yaml"
    assert main(["run", str(sc), "--out", str(tmp_path / "o"), "--format", "html,json,md,xlsx"]) == 0
    assert (tmp_path / "o" / "business-case.xlsx").is_file()
    assert main(["compare", str(sc)]) == 0 and "Human cost per task" in capsys.readouterr().out
    assert main(["sensitivity", str(sc)]) == 0 and "break-even containment" in capsys.readouterr().out
    assert main(["prices", "--check"]) == 0 and "to review" in capsys.readouterr().out
    assert main(["prices", "--provider", "openai", "--model", "gpt-6-luna", "--tier", "batch"]) == 0
    assert "0.0500" in capsys.readouterr().out
    out = tmp_path / "merged.yaml"
    assert main(["import-evals", str(FIX / "evals-experiment.json"), "--grader", "task_success", "--into", str(sc),
                 "--out", str(out)]) == 0
    assert len(load_scenario(out).options) == 5
    assert main(["web", "--out", str(tmp_path / "site")]) == 0
    bad = tmp_path / "bad.yaml"
    bad.write_text(sc.read_text().replace("currency: USD", "currency: INR"))
    assert main(["compare", str(bad)]) == 2
