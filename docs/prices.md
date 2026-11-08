# Prices and catalogs

The bundled catalogs are in `src/roi_calc/catalog/`: `openai.yaml` (OpenAI API) and `bedrock.yaml` (Amazon Bedrock,
including OpenAI, Anthropic, Amazon and Meta models, plus AgentCore and Guardrails). Every provider, model and service
carries `as_of` and `source`. Entries marked `verify: true` came from third-party write-ups and must be checked against
the provider before use. Reports list them.

```bash
roi prices                                  # every model, standard tier, global route
roi prices --provider bedrock --model openai.gpt-6.1-sol --route geo --tier priority
roi prices --check                          # entries to verify, ended promotions, prices older than 90 days
```

**Prices change. Check the catalog before a customer sees a number**, and put the date on the slide. The catalog was
last refreshed on the `as_of` date in each file.

## Resolution

```
rate[kind] = base[kind] × tier multiplier × route multiplier      kinds: input, cached, cache_write, output
long rate  = rate × long_context[kind]                             for the share of calls over the threshold
```

- A model lists the tiers and routes it supports; anything else is refused with an error, not priced silently. For
  example, Bedrock Priority and Flex are not offered for GPT-6 Astra, and Amazon Nova Micro is in-Region only.
- A model can override the provider's multipliers (`tier_multipliers`, `route_multipliers`). Bedrock Priority is 1.75×
  for most models and 2× for OpenAI models.
- `promos: [{rates: {...}, valid_until: YYYY-MM-DD}]` apply up to and including their end date; pricing a later month
  uses list price, and reports note that a promotional rate was used.

Summary of the bundled multipliers (see the files for the detail):

| | OpenAI API | Amazon Bedrock |
|---|---|---|
| Routes | global 1.0, regional processing 1.1 | global 1.0, geo 1.1, in-Region 1.1 (OpenAI and Anthropic models) |
| Tiers | Batch 0.5, Flex 0.5, Fast 2.0 | Flex 0.5, Priority 1.75 (2.0 for OpenAI models), Batch 0.5 (selected models) |
| Long context | over 272K tokens: input and cache 2×, output 1.5× | same, for OpenAI models |

OpenAI models on Bedrock with global cross-Region inference are priced at OpenAI's first-party rates, so the main
differences between the two routes to market are the regional premium, tier availability, and the platform around
the model (AgentCore, Guardrails, commit discounts through AWS).

## Overrides

Negotiated pricing goes in the scenario, not the catalog:

```yaml
price_overrides:
  # a discount on base rates; tiers and routes still apply on top
  - {provider: openai, model: gpt-6.1-sol, rates: {input: 1.6, cached: 0.08, cache_write: 2.0, output: 8.0}}
  # final rates for one tier and route (a private offer); nothing is applied on top, and long context is not priced
  - {provider: bedrock, model: openai.gpt-6.1-terra, tier: standard, route: geo, final: true,
     rates: {input: 0.9, output: 4.5}}
```

Kinds you leave out keep the catalog value. Reports say which options used overrides.

## Your own catalog

`roi --catalog ./my-prices run scenario.yaml` loads every `*.yaml` in the folder. A file with the same `provider` id
replaces the bundled one, so a partner can keep a private price list (with committed-use discounts, or another region)
without changing the package. A new provider, e.g. an Azure or a self-hosted endpoint, follows the same shape:
`provider`, `as_of`, `source`, `routes`, `tiers`, optional `long_context`, and `models` with `rates`, `tiers` and
`routes`. The file is validated on load.

To refresh the bundled catalog, change the rates and the `as_of`, cite the page in `source`, and run the tests.
