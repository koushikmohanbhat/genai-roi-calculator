# Changelog

## 0.1.0 (2026-11-08)

First release.

- Engine: cost per task (model calls, long context, measured cost, AgentCore and Guardrails platform costs), monthly
  schedule with ramp, coverage, containment, growth and benefit realisation; NPV, payback, ROI, IRR, TCO; tornado and
  break-even.
- Price catalog for the OpenAI API and Amazon Bedrock (OpenAI, Anthropic, Amazon and Meta models; AgentCore Runtime,
  Gateway, Memory; Guardrails), dated and sourced, with routes, tiers, long-context rules, promotions and overrides.
  `roi prices --check` lists entries to verify and stale prices.
- Outputs: Excel workbook with live formulas and named inputs; HTML, Markdown and JSON (`roi-calc/result` 1.0)
  reports; a static web calculator running the same engine in JavaScript.
- Import from the eval framework (4.1): tokens or measured cost per task, and a grader's pass rate as containment.
- Parity tests: Python vs JavaScript (Node) and vs the workbook recalculated in LibreOffice.
- Examples: claims intake (INR, 4 options) and IT helpdesk (USD, 2 options).
