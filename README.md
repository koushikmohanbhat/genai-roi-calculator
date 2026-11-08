# genai-roi-calculator

A business case for a GenAI workload that a partner can put in front of a customer's CFO: **cost per task, total cost of
ownership, NPV, payback, ROI and IRR**, compared across models, providers, tiers and routes. Built for OpenAI models on
the **OpenAI API** and on **Amazon Bedrock**, with Bedrock's non-OpenAI models and AgentCore platform costs alongside.

One scenario file goes in. Three things come out, and they always agree with each other:

| Output | For | What's in it |
|---|---|---|
| **Excel workbook** | the customer's finance team | live formulas, named inputs, monthly cash flows per option, sensitivity, sources |
| **HTML / Markdown / JSON report** | the deck, the proposal, a pipeline | options compared, cash-flow chart, tornado, break-even, per-call cost breakdown, notes |
| **Web calculator** | the first meeting | a single static page; change the drivers and see NPV move. No server, nothing leaves the browser |

It can also **import results from the eval framework (4.1)**: measured tokens or cost per task, and the grader's pass
rate as containment, so the business case uses numbers the customer saw on their own data.

```bash
pip install "genai-roi-calculator @ git+https://github.com/koushikmohanbhat/genai-roi-calculator"
roi init my-case                 # copies the two example scenarios
roi compare my-case/claims-intake-inr.yaml
roi run my-case/claims-intake-inr.yaml --out out/   # workbook + reports
roi web --out site/              # the static calculator page
```

```
Option                                                        NPV    Payback       ROI         AI/task    USD/task  Contain
Routed Terra + Luna on Bedrock (global)            INR 51,495,943         10    281.8%      INR 2.4506     0.02593  60%
GPT-6.1 Sol on Bedrock (global)                    INR 49,905,235         10    252.0%      INR 4.3118     0.04563  60%
Claude Sonnet 5.5 on Bedrock (geo)                 INR 49,581,763         10    246.5%      INR 4.6902     0.04963  60%
GPT-6.1 Sol, OpenAI API (regional processing)      INR 46,143,885         11    198.1%      INR 4.1632     0.04405  60%

Human cost per task: INR 227
```

The numbers in the examples are illustrative. Prices are from the bundled catalog, dated and sourced; check them before
you send anything (`roi prices --check`).

## How it works

```
scenario.yaml ──► catalog (prices, dated)  ──► cost per task (model calls + platform)
                                                    │
baseline, adoption, costs ─────────────────────────►├─► monthly schedule (ramp, coverage, containment, growth)
                                                    │        └─► NPV · payback · ROI · IRR · TCO
4.1 eval results (optional) ─► options + containment┘        └─► tornado · break-even
                                                    │
                                     ┌──────────────┼───────────────┐
                                   Excel        HTML/MD/JSON     web page
                               (live formulas)                 (same engine in JS)
```

- **Cost per task** = Σ over calls of `share × calls × (fresh input × in + cached × cached + cache writes × write + output × out) / 1M`,
  with the long-context rate for the share of calls above the threshold, plus platform costs (AgentCore Runtime
  vCPU/GB-seconds, Gateway calls, Memory events, Guardrails text units, anything else per task). A call can carry a
  measured cost instead of tokens.
- **Prices** resolve as base rate × tier multiplier × route multiplier, per model (some models have their own
  multipliers, e.g. Bedrock Priority is 2× for OpenAI models), then promotions with an end date, then your overrides
  (a negotiated discount, or `final` rates from a private offer).
- **The schedule**: volume grows monthly; from go-live the ramp takes adoption to `coverage`; of the covered tasks,
  `containment` are completed by the AI. Savings are the human time saved, less review time, plus the error-cost
  change and any avoidable fixed cost, times `benefit_realisation`. Costs are AI usage, run costs, one-offs and
  maintenance.
- **Payback** is the first month after the last month the cumulative cash flow is negative. **IRR** is annualised from
  the monthly IRR.

## Documentation

- [Scenario reference](docs/scenario.md): every field, with defaults
- [Prices and catalogs](docs/prices.md): what's bundled, how resolution works, overrides, adding a provider
- [Importing eval results](docs/evals-import.md): from the eval framework (4.1)
- [Outputs](docs/outputs.md): the workbook, reports, JSON schema and the web page; how they're kept in step
- [Using it with a customer](docs/playbook.md): a partner's walkthrough, and what not to claim

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
ruff check . && pytest -q
```

The parity tests run the JavaScript engine under Node and recalculate the workbook in LibreOffice
(`soffice --headless`), and compare both with the Python engine. They skip if those aren't installed; CI runs both.

Licensed under Apache 2.0.
