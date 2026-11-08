# Outputs

```bash
roi run case.yaml --out out/ --format xlsx,html,md,json     # default: all four
roi compare case.yaml                                       # table in the terminal
roi sensitivity case.yaml [--option NAME]                   # tornado and break-even
roi web --out site/                                         # the calculator page
```

## Excel workbook (`business-case.xlsx`)

Built for the customer's finance team to check and change.

| Sheet | Contents |
|---|---|
| Summary | KPIs per option (formulas over the monthly sheets), the best option, notes |
| Inputs | every driver as a **named cell** (`Volume`, `HandleMinutes`, `Containment`, `FxUSD`, …), blue for inputs |
| Costs | one-offs and run costs |
| Per task | each option's calls with their resolved rates and token counts, and the cost per task **as a formula** |
| Monthly 1…n | one sheet per option: volume, ramp, AI tasks, savings, costs, cash flow, cumulative. All formulas. |
| Sensitivity | tornado and break-even (values from the engine, recomputed by `roi run`) |
| Sources | each price used, with `as_of` and source URL, and the assumptions |

Change an input and Summary updates in Excel, LibreOffice or Google Sheets. Each option's containment is an input cell on
Per task, so imported or what-if containment can be changed there. The sensitivity sheet is the exception: it is values, so re-run `roi run` after changing
inputs if you rely on it.

## Reports

- `report.html`: a self-contained page (no external assets) with the options compared, cumulative cash flow, the
  tornado for the best option, break-even, per-call cost breakdown, inputs, assumptions and notes. Prints well.
- `summary.md`: the same content in Markdown, for a proposal or a pull request.
- `result.json`: schema `roi-calc/result` 1.0: per option KPIs, cost breakdown, tornado, break-even and months; plus
  the price dates used and the notes. Use it to feed a CRM, a deck generator or a dashboard.

Notes are generated for: prices marked `verify`, promotional rates, overrides, imported containment, options that
never pay back, and the 4.1 gates reminder.

## Web calculator

`roi web --out site/` writes one `index.html` with the engine, the catalog and the examples embedded. Open it from
disk or host it anywhere static (the CI publishes it to GitHub Pages). Everything runs in the browser; there are no
network calls, and nothing is stored.

It loads a bundled example or a scenario saved as JSON, lets you edit the drivers
and options, and shows the same KPIs, chart and tornado. "Download scenario" saves the edited scenario so it can go
through `roi run` for the workbook.

## Keeping the three in step

The engine exists twice: Python (`engine.py`) and JavaScript (`web/calc.js`), and the workbook re-implements the
schedule as formulas. The tests hold them together:

- Python vs JavaScript on every bundled example: cost per task, every month's cash flow, NPV, ROI, IRR, payback and
  the tornado, to 1e-9 relative.
- Python vs the workbook after a LibreOffice headless recalculation: NPV, total costs, ROI, payback, IRR and cost per
  task for every option.

Change one engine and the tests fail until the others match.
