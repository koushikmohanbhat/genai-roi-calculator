# Scenario reference

A scenario is one YAML file. Money is in the scenario `currency` unless a field ends in `_usd`. Catalog prices are in
USD and are converted with `fx_usd`. Unknown fields are rejected, so a typo fails loudly rather than being ignored.
`roi init <dir>` copies two complete examples to start from.

## Top level

| Field | Default | Meaning |
|---|---|---|
| `name` | required | shown on every output |
| `description` | `""` | |
| `currency` | `USD` | ISO code; any currency works |
| `fx_usd` | required unless USD | 1 USD in the scenario currency (e.g. `94.5` for INR). The calculator never assumes a rate. |
| `start_date` | required | month 1 |
| `horizon_months` | 36 | 1–120 |
| `discount_rate_annual` | 0.10 | used for NPV; monthly rate = (1 + r)^(1/12) − 1 |
| `baseline`, `adoption`, `costs`, `options` | | below |
| `price_overrides` | `[]` | see [prices](prices.md#overrides) |
| `sensitivity` | ±20% on 8 drivers | `pct` and `drivers` (volume, handle_minutes, loaded_cost_per_hour, coverage, containment, review_minutes, ai_cost_per_task, one_off, run_costs, benefit_realisation) |
| `assumptions` | `[]` | free text, printed in the reports and the workbook |

## `baseline`: the process today

| Field | Default | Meaning |
|---|---|---|
| `volume_per_month` | required | tasks per month in month 1 |
| `growth_per_month` | 0 | compound monthly growth |
| `handle_minutes` | required | human time per task |
| `loaded_cost_per_hour` | required | salary plus on-costs, overheads, management |
| `error_rate`, `cost_per_error` | 0 | today's errors and what each costs (rework, leakage, penalties) |
| `fixed_per_month` | 0 | fixed cost of today's process (tools, an outsourcing contract) |
| `avoidable_fixed_per_month` | 0 | the part of it that ends at full adoption (scaled by the ramp) |

## `adoption`: what changes

| Field | Default | Meaning |
|---|---|---|
| `go_live_month` | 1 | first month with AI traffic, AI cost and maintenance |
| `ramp_months` | 1 | months from go-live to full adoption (linear) |
| `coverage` | required | share of tasks sent to the AI at full adoption |
| `containment` | required | share of AI tasks completed without full human handling. Options may override it. |
| `review_minutes` | 0 | human time spent checking a contained task |
| `ai_error_rate` | 0 | errors on contained tasks (escalated tasks keep today's rate) |
| `benefit_realisation` | 1 | share of the labour saving that becomes a real saving (redeployment, attrition, not hiring) |

Per month: volume V; AI tasks T = V × ramp × coverage; contained C = T × containment; escalated E = T − C; human-only
H = V − T. Escalated tasks cost both the AI call and the full human time.

```
savings = (baseline cost − labour with AI − errors with AI − fixed with AI) × benefit_realisation
costs   = T × AI cost per task + platform fixed + one-offs + run costs + maintenance
```

## `costs`

| Field | Meaning |
|---|---|
| `one_off: [{name, amount, month}]` | build, integration, change management, evals |
| `run_per_month: [{name, amount, from_month}]` | people and tools to run it; `from_month` defaults to go-live |
| `maintenance_pct_per_year` | of total one-off cost, charged monthly from go-live |

## `options`: what you're comparing

Each option is one way to run the workload. All options share the baseline, adoption and costs; they differ in cost
per task and, optionally, containment.

| Field | Meaning |
|---|---|
| `name` | unique |
| `calls` | model calls per task (below) |
| `platform` | Bedrock AgentCore and Guardrails usage per task (below) |
| `platform_fixed_usd_per_month` | fixed platform cost (e.g. provisioned throughput, a gateway cluster), from go-live |
| `containment`, `containment_source` | overrides `adoption.containment`; the source is shown in reports |

### `calls`

| Field | Default | Meaning |
|---|---|---|
| `provider` | required | `openai`, `bedrock`, a provider in your own catalog, or `measured` |
| `model` | required | catalog id or alias (e.g. `global.openai.gpt-6.1-sol`) |
| `route` | `global` | OpenAI: `global`, `regional`. Bedrock: `global`, `geo`, `in_region` |
| `tier` | `standard` | OpenAI: `standard`, `batch`, `flex`, `fast`. Bedrock: `standard`, `flex`, `priority`, `batch` (per model) |
| `share` | 1 | share of tasks that make this call (routing, fallbacks) |
| `calls` | 1 | calls per task, for tasks that make it |
| `input_tokens` | 0 | **fresh** input tokens per call (not counting cache reads) |
| `cached_tokens`, `cache_write_tokens` | 0 | cache reads and writes per call |
| `output_tokens` | 0 | including reasoning tokens |
| `long_context_share` | 0 | share of calls whose prompt is over the provider's long-context threshold |
| `measured_cost_usd` | none | a measured cost per call; replaces token pricing |

A routed design is several calls with shares, e.g. 85% to a small model and 15% escalated to a large one.

### `platform` (Bedrock)

`runtime: {version: v2, vcpu_seconds, gb_seconds}` (active vCPU and memory per task), `gateway_calls`,
`memory_events`, `memory_records`, `guardrails: {content_filter, denied_topics, sensitive_info, grounding}` in text
units per task, and `other_usd` per task.
