"""The Excel business case. Inputs, rates, per-task costs, the monthly model and the summary are live formulas, so a
CFO can change a volume, a rate or a token count and see payback and NPV move. Sensitivity values are computed by the
engine at export (marked as such). The monthly sheets have one row per month of the exported horizon.

Sheets: Summary · Inputs · Costs · Per task · Monthly <n> (one per option) · Sensitivity · Sources
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.workbook.defined_name import DefinedName

from . import __version__
from .engine import OptionResult
from .scenario import Scenario

HEAD = PatternFill("solid", fgColor="1F3A5F")
INPUT = PatternFill("solid", fgColor="FFF4CC")
NOTE = Font(italic=True, color="666666", size=9)
BOLD = Font(bold=True)
WHITE = Font(bold=True, color="FFFFFF")


def _name(wb: Workbook, name: str, ref: str) -> None:
    wb.defined_names[name] = DefinedName(name, attr_text=ref)


def _header(ws, row: int, cols: list[str], widths: list[int] | None = None) -> None:
    for i, c in enumerate(cols, 1):
        cell = ws.cell(row=row, column=i, value=c)
        cell.fill, cell.font = HEAD, WHITE
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        if widths:
            ws.column_dimensions[get_column_letter(i)].width = widths[i - 1]


def _money_fmt(cur: str) -> str:
    return '#,##0;[Red]-#,##0' if cur in ("INR", "JPY", "KRW", "IDR") else '#,##0.00;[Red]-#,##0.00'


def build(s: Scenario, results: list[OptionResult], summary: dict[str, Any], path: str | Path) -> Path:
    wb = Workbook()
    money = _money_fmt(s.currency)

    # Inputs ---------------------------------------------------------------------------------------------------
    ws = wb.active
    ws.title = "Inputs"
    ws["A1"] = f"{s.name}: inputs"
    ws["A1"].font = Font(bold=True, size=13)
    ws["A2"] = f"Yellow cells are inputs. Money in {s.currency} unless marked USD."
    ws["A2"].font = NOTE
    b, a = s.baseline, s.adoption
    inputs = [
        ("Fx", "USD to scenario currency (1 USD =)", s.fx_usd, "0.0000"),
        ("Horizon", "Horizon, months (rows are fixed at export)", s.horizon_months, "0"),
        ("DiscountRate", "Discount rate, annual", s.discount_rate_annual, "0.0%"),
        ("Volume0", "Tasks per month today", b.volume_per_month, "#,##0"),
        ("Growth", "Volume growth per month", b.growth_per_month, "0.00%"),
        ("HandleMin", "Human handling time, minutes per task", b.handle_minutes, "0.00"),
        ("Rate", f"Loaded cost per hour ({s.currency})", b.loaded_cost_per_hour, money),
        ("ErrRate", "Error rate today", b.error_rate, "0.00%"),
        ("CostPerError", f"Cost per error ({s.currency})", b.cost_per_error, money),
        ("FixedPM", f"Fixed cost of today's process per month ({s.currency})", b.fixed_per_month, money),
        ("AvoidablePM", f"Part of the fixed cost removed at full adoption ({s.currency})", b.avoidable_fixed_per_month, money),
        ("GoLive", "Go-live month", a.go_live_month, "0"),
        ("RampMonths", "Months to full adoption", a.ramp_months, "0"),
        ("Coverage", "Share of tasks sent to the AI at full adoption", a.coverage, "0.0%"),
        ("Review", "Human review minutes per contained task", a.review_minutes, "0.00"),
        ("AiErrRate", "Error rate on contained tasks", a.ai_error_rate, "0.00%"),
        ("Realisation", "Benefit realisation (labour savings that become real)", a.benefit_realisation, "0.0%"),
        ("MaintPct", "Maintenance per year, share of one-off costs", s.costs.maintenance_pct_per_year, "0.0%"),
    ]
    _header(ws, 4, ["Input", "Value", "Name"], [58, 18, 16])
    for i, (nm, label, val, fmt) in enumerate(inputs, 5):
        ws.cell(row=i, column=1, value=label)
        c = ws.cell(row=i, column=2, value=val)
        c.fill, c.number_format = INPUT, fmt
        ws.cell(row=i, column=3, value=nm).font = NOTE
        _name(wb, nm, f"Inputs!$B${i}")
    r = 5 + len(inputs)
    ws.cell(row=r, column=1, value="Monthly discount rate")
    ws.cell(row=r, column=2, value="=(1+DiscountRate)^(1/12)-1").number_format = "0.0000%"
    ws.cell(row=r, column=3, value="MonthlyRate").font = NOTE
    _name(wb, "MonthlyRate", f"Inputs!$B${r}")
    r += 1
    ws.cell(row=r, column=1, value=f"Human cost per task ({s.currency})")
    ws.cell(row=r, column=2, value="=HandleMin/60*Rate+ErrRate*CostPerError").number_format = money
    ws.cell(row=r, column=3, value="HumanCPT").font = NOTE
    _name(wb, "HumanCPT", f"Inputs!$B${r}")

    # Costs ----------------------------------------------------------------------------------------------------
    wc = wb.create_sheet("Costs")
    wc["A1"] = "One-off costs"
    wc["A1"].font = BOLD
    _header(wc, 2, ["Item", f"Amount ({s.currency})", "Month"], [44, 18, 10])
    n1 = max(len(s.costs.one_off), 1)
    for i in range(n1):
        x = s.costs.one_off[i] if i < len(s.costs.one_off) else None
        wc.cell(row=3 + i, column=1, value=x.name if x else "(none)")
        c = wc.cell(row=3 + i, column=2, value=x.amount if x else 0)
        c.fill, c.number_format = INPUT, money
        wc.cell(row=3 + i, column=3, value=x.month if x else 1).fill = INPUT
    o_lo, o_hi = 3, 2 + n1
    _name(wb, "OneOffAmt", f"Costs!$B${o_lo}:$B${o_hi}")
    _name(wb, "OneOffMonth", f"Costs!$C${o_lo}:$C${o_hi}")
    rr = o_hi + 2
    wc.cell(row=rr, column=1, value="Total one-off")
    wc.cell(row=rr, column=2, value=f"=SUM(B{o_lo}:B{o_hi})").number_format = money
    _name(wb, "OneOffTotal", f"Costs!$B${rr}")
    rr += 2
    wc.cell(row=rr, column=1, value="Recurring costs per month").font = BOLD
    _header(wc, rr + 1, ["Item", f"Per month ({s.currency})", "From month"])
    n2 = max(len(s.costs.run_per_month), 1)
    r_lo = rr + 2
    for i in range(n2):
        x = s.costs.run_per_month[i] if i < len(s.costs.run_per_month) else None
        wc.cell(row=r_lo + i, column=1, value=x.name if x else "(none)")
        c = wc.cell(row=r_lo + i, column=2, value=x.amount if x else 0)
        c.fill, c.number_format = INPUT, money
        fm = wc.cell(row=r_lo + i, column=3, value=(x.from_month if (x and x.from_month) else "=GoLive"))
        fm.fill = INPUT
    r_hi = r_lo + n2 - 1
    _name(wb, "RunAmt", f"Costs!$B${r_lo}:$B${r_hi}")
    _name(wb, "RunFrom", f"Costs!$C${r_lo}:$C${r_hi}")
    wc.cell(row=r_hi + 2, column=1, value="Recurring items without a start month start at go-live (=GoLive).").font = NOTE

    # Per task -------------------------------------------------------------------------------------------------
    wt = wb.create_sheet("Per task")
    wt["A1"] = "Cost per AI task, by option (USD unless marked)"
    wt["A1"].font = Font(bold=True, size=13)
    wt["A2"] = ("Rates are USD per 1M tokens, resolved from the catalog for the route and tier (editable). Long-context "
                "rates apply to the share of calls above the model's threshold.")
    wt["A2"].font = NOTE
    cols = ["Option / line", "Provider", "Model", "Route", "Tier", "Share", "Calls", "Fresh in", "Cached", "Cache write",
            "Output", "Long-ctx share", "$ in", "$ cached", "$ write", "$ out", "$ in (long)", "$ cached (long)",
            "$ write (long)", "$ out (long)", "Measured $/call", "USD per task"]
    _header(wt, 4, cols, [34, 10, 26, 10, 10, 7, 7, 10, 10, 10, 10, 9, 8, 8, 8, 8, 9, 9, 9, 9, 10, 12])
    row = 5
    opt_cells: list[dict[str, str]] = []
    for o, res in zip(s.options, results, strict=True):
        wt.cell(row=row, column=1, value=o.name).font = BOLD
        row += 1
        first = row
        for c, cc in zip(o.calls, res.task.calls, strict=True):
            rates = cc.rates
            vals = [f"  {c.model}", c.provider, cc.model, c.route, c.tier, c.share, c.calls, c.input_tokens,
                    c.cached_tokens, c.cache_write_tokens, c.output_tokens, c.long_context_share]
            for j, v in enumerate(vals, 1):
                cell = wt.cell(row=row, column=j, value=v)
                if j >= 6:
                    cell.fill = INPUT
            if rates:
                short = [rates.short[k] for k in ("input", "cached", "cache_write", "output")]
                long = [rates.long[k] for k in ("input", "cached", "cache_write", "output")] if rates.long else short
                for j, v in enumerate(short + long, 13):
                    cell = wt.cell(row=row, column=j, value=v)
                    cell.fill, cell.number_format = INPUT, "0.0000"
                wt.cell(row=row, column=21, value=None)
            else:
                for j in range(13, 21):
                    wt.cell(row=row, column=j, value=0)
                m = wt.cell(row=row, column=21, value=c.measured_cost_usd)
                m.fill, m.number_format = INPUT, "0.000000"
            R = row
            wt.cell(row=R, column=22, value=(
                f'=IF(U{R}<>"",F{R}*G{R}*U{R},F{R}*G{R}*((1-L{R})*(H{R}*M{R}+I{R}*N{R}+J{R}*O{R}+K{R}*P{R})'
                f'+L{R}*(H{R}*Q{R}+I{R}*R{R}+J{R}*S{R}+K{R}*T{R}))/1000000)')).number_format = "0.000000"
            row += 1
        plat = o.platform
        prov = (plat.provider if plat else "bedrock")
        svc = summary.get("_services", {}).get(prov, {})
        plines: list[tuple[str, float, float, float]] = []      # label, quantity, unit price, divisor
        if plat and plat.runtime and (plat.runtime.vcpu_seconds or plat.runtime.gb_seconds):
            rt = svc.get(f"agentcore_runtime_{plat.runtime.version}", {})
            plines += [(f"  Runtime {plat.runtime.version}: vCPU-seconds x $/vCPU-hour", plat.runtime.vcpu_seconds,
                        rt.get("vcpu_hour", 0), 3600),
                       (f"  Runtime {plat.runtime.version}: GB-seconds x $/GB-hour", plat.runtime.gb_seconds,
                        rt.get("gb_hour", 0), 3600)]
        if plat and plat.gateway_calls:
            plines.append(("  Gateway invocations x $/1,000", plat.gateway_calls,
                           svc.get("agentcore_gateway", {}).get("per_1k_invocations", 0), 1000))
        if plat and (plat.memory_events or plat.memory_records):
            mm = svc.get("agentcore_memory", {})
            plines += [("  Memory events x $/1,000", plat.memory_events, mm.get("per_1k_short_term_events", 0), 1000),
                       ("  Memory records x $/1,000", plat.memory_records, mm.get("per_1k_long_term_records", 0), 1000)]
        if plat and plat.guardrails:
            g = svc.get("guardrails", {})
            for k in ("content_filter", "denied_topics", "sensitive_info", "grounding"):
                q = getattr(plat.guardrails, k)
                if q:
                    plines.append((f"  Guardrails {k.replace('_', ' ')}: text units x $/1,000", q, g.get(k, 0), 1000))
        if plat and plat.other_usd:
            plines.append(("  Other per task (USD)", plat.other_usd, 1, 1))
        for label, q, price, div in plines:
            wt.cell(row=row, column=1, value=label)
            qc = wt.cell(row=row, column=8, value=q)
            qc.fill = INPUT
            pc = wt.cell(row=row, column=13, value=price)
            pc.fill, pc.number_format = INPUT, "0.000000"
            wt.cell(row=row, column=14, value=div).font = NOTE
            wt.cell(row=row, column=22, value=f"=H{row}*M{row}/N{row}").number_format = "0.000000"
            row += 1
        last = row - 1
        wt.cell(row=row, column=1, value="  Total per task, USD").font = BOLD
        wt.cell(row=row, column=22, value=f"=SUM(V{first}:V{last})" if last >= first else 0).number_format = "0.000000"
        usd_cell = f"'Per task'!$V${row}"
        row += 1
        wt.cell(row=row, column=1, value=f"  Total per task, {s.currency}").font = BOLD
        wt.cell(row=row, column=22, value=f"=V{row - 1}*Fx").number_format = "0.0000"
        cpt = f"'Per task'!$V${row}"
        row += 1
        wt.cell(row=row, column=1, value="  Platform fixed per month, USD")
        pf = wt.cell(row=row, column=22, value=o.platform_fixed_usd_per_month)
        pf.fill = INPUT
        pfx = f"'Per task'!$V${row}"
        row += 1
        wt.cell(row=row, column=1, value="  Containment (share of AI tasks completed without a handler)")
        cn = wt.cell(row=row, column=22, value=res.containment)
        cn.fill, cn.number_format = INPUT, "0.0%"
        if o.containment_source:
            wt.cell(row=row, column=2, value=o.containment_source).font = NOTE
        cont = f"'Per task'!$V${row}"
        row += 2
        opt_cells.append({"cpt": cpt, "usd": usd_cell, "pf": pfx, "cont": cont})

    # Monthly sheets -------------------------------------------------------------------------------------------
    mcols = ["Month", "Volume", "Ramp", "AI tasks", "Contained", "Escalated", "Human only", "Baseline cost",
             "Labour with AI", "Errors with AI", "Fixed with AI", "Savings", "AI usage", "One-off", "Run", "Maintenance",
             "Costs", "Cash flow", "Cumulative", "Discount factor", "PV"]
    H = s.horizon_months
    sheets = []
    for oi, o in enumerate(s.options):
        title = f"Monthly {oi + 1}"
        wm = wb.create_sheet(title)
        sheets.append(title)
        wm["A1"] = f"{o.name}: monthly model ({s.currency})"
        wm["A1"].font = BOLD
        _header(wm, 3, mcols, [7] + [13] * (len(mcols) - 1))
        oc = opt_cells[oi]
        for m in range(1, H + 1):
            R = 3 + m
            f = {
                "A": m,
                "B": f"=Volume0*(1+Growth)^(A{R}-1)",
                "C": f"=IF(A{R}<GoLive,0,MIN(1,(A{R}-GoLive+1)/RampMonths))",
                "D": f"=B{R}*C{R}*MIN(1,Coverage)",
                "E": f"=D{R}*MIN(1,{oc['cont']})",
                "F": f"=D{R}-E{R}",
                "G": f"=B{R}-D{R}",
                "H": f"=B{R}*HandleMin/60*Rate+B{R}*ErrRate*CostPerError+FixedPM",
                "I": f"=(G{R}+F{R})*HandleMin/60*Rate+E{R}*Review/60*Rate",
                "J": f"=(G{R}+F{R})*ErrRate*CostPerError+E{R}*AiErrRate*CostPerError",
                "K": f"=FixedPM-AvoidablePM*C{R}",
                "L": f"=(H{R}-I{R}-J{R}-K{R})*MIN(1,Realisation)",
                "M": f"=D{R}*{oc['cpt']}+IF(A{R}>=GoLive,{oc['pf']}*Fx,0)",
                "N": f"=SUMIF(OneOffMonth,A{R},OneOffAmt)",
                "O": f'=SUMIF(RunFrom,"<="&A{R},RunAmt)',
                "P": f"=IF(A{R}>=GoLive,OneOffTotal*MaintPct/12,0)",
                "Q": f"=M{R}+N{R}+O{R}+P{R}",
                "R": f"=L{R}-Q{R}",
                "S": f"=R{R}" if m == 1 else f"=S{R - 1}+R{R}",
                "T": f"=1/(1+MonthlyRate)^A{R}",
                "U": f"=R{R}*T{R}",
            }
            for col, v in f.items():
                c = wm[f"{col}{R}"]
                c.value = v
                if col in "BDEFG":
                    c.number_format = "#,##0"
                elif col == "C":
                    c.number_format = "0%"
                elif col == "T":
                    c.number_format = "0.0000"
                elif col != "A":
                    c.number_format = money
        wm.freeze_panes = "B4"

    # Summary --------------------------------------------------------------------------------------------------
    sm = wb.create_sheet("Summary", 0)
    sm["A1"] = s.name
    sm["A1"].font = Font(bold=True, size=14)
    sm["A2"] = (f"{s.horizon_months}-month business case in {s.currency}, starting {s.start_date.isoformat()}. "
                f"Prices as of {', '.join(summary.get('price_dates', [])) or 'n/a'}. Generated {date.today().isoformat()} "
                f"by genai-roi-calculator {__version__}.")
    sm["A2"].font = NOTE
    _header(sm, 4, ["Measure"] + [o.name for o in s.options], [40] + [26] * len(s.options))
    rows = [
        ("NPV", lambda t: f"=SUM('{t}'!U4:U{3 + H})", money),
        ("Total cash flow", lambda t: f"=SUM('{t}'!R4:R{3 + H})", money),
        ("Total savings", lambda t: f"=SUM('{t}'!L4:L{3 + H})", money),
        ("Total costs", lambda t: f"=SUM('{t}'!Q4:Q{3 + H})", money),
        ("ROI (cash flow / costs)", lambda t: f"=IF(SUM('{t}'!Q4:Q{3 + H})=0,\"n/a\",SUM('{t}'!R4:R{3 + H})/SUM('{t}'!Q4:Q{3 + H}))",
         "0.0%"),
        ("Payback month", lambda t: (f"=IF(COUNTIF('{t}'!S4:S{3 + H},\"<0\")=0,0,IF(_xlfn.MAXIFS('{t}'!A4:A{3 + H},'{t}'!S4:S{3 + H},"
                                     f"\"<0\")>={H},\"not within horizon\",_xlfn.MAXIFS('{t}'!A4:A{3 + H},'{t}'!S4:S{3 + H},\"<0\")+1))"),
         "0"),
        ("IRR (annualised)", lambda t: f"=IFERROR((1+IRR('{t}'!R4:R{3 + H}))^12-1,\"n/a\")", "0.0%"),
        ("Cash flow in the last month", lambda t: f"='{t}'!R{3 + H}", money),
    ]
    for i, (label, fn, fmt) in enumerate(rows, 5):
        sm.cell(row=i, column=1, value=label).font = BOLD
        for j, t in enumerate(sheets, 2):
            c = sm.cell(row=i, column=j, value=fn(t))
            c.number_format = fmt
    i = 5 + len(rows)
    sm.cell(row=i, column=1, value=f"AI cost per task ({s.currency})").font = BOLD
    for j, oc in enumerate(opt_cells, 2):
        sm.cell(row=i, column=j, value=f"={oc['cpt']}").number_format = "0.0000"
    i += 1
    sm.cell(row=i, column=1, value=f"Human cost per task ({s.currency})").font = BOLD
    for j in range(2, 2 + len(opt_cells)):
        sm.cell(row=i, column=j, value="=HumanCPT").number_format = money
    i += 1
    sm.cell(row=i, column=1, value="Containment").font = BOLD
    for j, oc in enumerate(opt_cells, 2):
        sm.cell(row=i, column=j, value=f"={oc['cont']}").number_format = "0.0%"
    i += 2
    notes = list(summary.get("_notes", [])) + list(s.assumptions)
    if notes:
        sm.cell(row=i, column=1, value="Notes").font = BOLD
        for k, n in enumerate(notes, 1):
            sm.cell(row=i + k, column=1, value=f"- {n}").font = NOTE

    # Sensitivity (values) -------------------------------------------------------------------------------------
    se = wb.create_sheet("Sensitivity")
    se["A1"] = (f"Sensitivity of NPV to +/-{int(s.sensitivity.pct * 100)}% on each driver, and break-even points. "
                "Values computed by the engine at export: they do not recalculate.")
    se["A1"].font = NOTE
    row = 3
    for o in summary["options"]:
        se.cell(row=row, column=1, value=o["name"]).font = BOLD
        row += 1
        _header(se, row, ["Driver", f"NPV at -{int(s.sensitivity.pct * 100)}%", f"NPV at +{int(s.sensitivity.pct * 100)}%",
                          "Swing"], [34, 20, 20, 20])
        row += 1
        for t in o["tornado"]:
            se.cell(row=row, column=1, value=t["driver"])
            for j, k in enumerate(("low", "high", "swing"), 2):
                se.cell(row=row, column=j, value=t[k]).number_format = money
            row += 1
        be = o["break_even"]
        for label, k, fmt in (("Break-even containment", "containment", "0.0%"),
                              ("Break-even volume (x today)", "volume_multiplier", "0.00"),
                              (f"Max AI cost per task at break-even ({s.currency})", "max_ai_cost_per_task", "0.00")):
            se.cell(row=row, column=1, value=label)
            c = se.cell(row=row, column=2, value=be[k] if be[k] is not None else "none in range")
            c.number_format = fmt
            row += 1
        row += 1

    # Sources ----------------------------------------------------------------------------------------------------
    so = wb.create_sheet("Sources")
    _header(so, 1, ["Option", "Provider", "Model", "Route", "Tier", "Source", "As of", "Check", "Notes"],
            [30, 10, 26, 10, 10, 60, 11, 8, 60])
    row = 2
    for o in summary["options"]:
        for c in o["task_cost"]["calls"]:
            rt = c["rates"]
            vals = [o["name"], c["provider"], c["model"], c["route"], c["tier"],
                    rt["source"] if rt else "measured (4.1)", rt["as_of"] if rt else "",
                    "verify" if rt and rt["verify"] else "", "; ".join(rt["notes"]) if rt else ""]
            for j, v in enumerate(vals, 1):
                so.cell(row=row, column=j, value=v)
            row += 1
    for prov, svcs in summary.get("_services", {}).items():
        for name, sv in svcs.items():
            for j, v in enumerate(["(run costs)", prov, name, "", "", sv.get("source", ""), sv.get("as_of", ""),
                                   "verify" if sv.get("verify") else "", "; ".join(sv.get("notes", []))], 1):
                so.cell(row=row, column=j, value=v)
            row += 1
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out
