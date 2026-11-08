# Importing eval results (4.1)

The [GenAI Eval Framework](https://github.com/koushikmohanbhat/genai-eval-framework) writes `result.json`
(schema `genai-evals/result` 1.x) for a run, an experiment or an online sample. The calculator turns each target or
experiment variant in it into an option, so the cost per task and the containment come from the customer's own data
rather than a guess.

```bash
roi import-evals runs/exp-42/result.json --grader task_success --into case.yaml
roi import-evals online.json --target claims-agent-aws \
    --model-map anthropic.claude-sonnet-v1=bedrock:anthropic.claude-sonnet-5-5 --into case.yaml --out case-v2.yaml
roi compare case-v2.yaml
```

| Flag | Meaning |
|---|---|
| `--grader` | the grader whose pass rate becomes the option's containment; without it, options use `adoption.containment` |
| `--target` | only these targets or variants (repeatable) |
| `--model-map model=provider:id` | when the model id in the result isn't in the catalog |
| `--route` | route for the imported calls (default `global`) |
| `--conservative` | p95 tokens instead of the mean, and the grader's CI low instead of its mean |
| `--into`, `--out`, `--replace` | the scenario to add to, where to write it, and whether to replace its options |

## What's taken from the result

- **Tokens per task**: samples are averaged over repeats for each case, then over cases. 4.1's `input_tokens`
  includes cached tokens, so fresh input = input − cached. Reasoning tokens are inside output tokens and are not added
  again.
- **Measured cost**: if samples have `cost_usd` but no token counts (e.g. a hosted agent that reports cost only), the
  mean becomes `measured_cost_usd`, priced as is.
- **Containment**: the grader's mean (or CI low), with a `containment_source` such as
  `task_success on 40 eval cases (exp-42), not production`.
- **Model**: matched to the catalog by id or alias.

## Read this before using imported numbers

An eval pass rate is measured on a test set, not in production; reports say so next to any imported containment. And
the business case ranks options on money only. An option that is cheapest may be the one that failed the release
gates in 4.1 (in the bundled fixture, `fast-model` has the best NPV but regresses on a gated grader). **Only put options
in front of a customer that passed the 4.1 gates**; the reports carry a note to that effect.
