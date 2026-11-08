"""scenario.yaml: the business case inputs. Money is in the scenario currency unless a field ends in `_usd`.
Catalog prices are USD and are converted with `fx_usd` (1 USD in the scenario currency), which must be given unless
the currency is USD: the calculator never assumes an exchange rate."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Baseline(_M):
    volume_per_month: float = Field(gt=0, description="tasks handled today per month")
    growth_per_month: float = Field(0.0, ge=-0.5, le=1.0)
    handle_minutes: float = Field(gt=0, description="human handling time per task")
    loaded_cost_per_hour: float = Field(ge=0, description="fully loaded cost of an hour of the people doing the task")
    error_rate: float = Field(0.0, ge=0, le=1)
    cost_per_error: float = Field(0.0, ge=0)
    fixed_per_month: float = Field(0.0, ge=0, description="fixed cost of today's process (tools, contracts)")
    avoidable_fixed_per_month: float = Field(0.0, ge=0, description="part of the fixed cost that goes away at full adoption")

    @model_validator(mode="after")
    def _avoidable(self):
        if self.avoidable_fixed_per_month > self.fixed_per_month:
            raise ValueError("avoidable_fixed_per_month cannot exceed fixed_per_month")
        return self


class Adoption(_M):
    go_live_month: int = Field(1, ge=1)
    ramp_months: int = Field(1, ge=1)
    coverage: float = Field(ge=0, le=1, description="share of tasks sent to the AI at full adoption")
    containment: float = Field(ge=0, le=1, description="share of AI tasks completed without full human handling")
    review_minutes: float = Field(0.0, ge=0, description="human review time per contained task")
    ai_error_rate: float = Field(0.0, ge=0, le=1, description="errors on contained tasks")
    benefit_realisation: float = Field(1.0, ge=0, le=1, description="share of labour savings that become real savings")
    containment_source: str | None = None


class OneOff(_M):
    name: str
    amount: float = Field(ge=0)
    month: int = Field(1, ge=1)


class Recurring(_M):
    name: str
    amount: float = Field(ge=0, description="per month")
    from_month: int | None = Field(None, ge=1, description="default: go-live month")


class Costs(_M):
    one_off: list[OneOff] = Field(default_factory=list)
    run_per_month: list[Recurring] = Field(default_factory=list)
    maintenance_pct_per_year: float = Field(0.0, ge=0, le=2, description="of total one-off cost, from go-live")


class Call(_M):
    provider: str
    model: str
    route: str = "global"
    tier: str = "standard"
    share: float = Field(1.0, ge=0, le=1, description="share of tasks that make this call")
    calls: float = Field(1.0, ge=0, description="calls per task (for tasks that make it)")
    input_tokens: float = Field(0.0, ge=0, description="fresh (uncached) input tokens per call")
    cached_tokens: float = Field(0.0, ge=0, description="input tokens read from cache per call")
    cache_write_tokens: float = Field(0.0, ge=0, description="input tokens written to cache per call")
    output_tokens: float = Field(0.0, ge=0, description="output tokens per call, including reasoning")
    long_context_share: float = Field(0.0, ge=0, le=1, description="share of calls above the long-context threshold")
    measured_cost_usd: float | None = Field(None, ge=0, description="measured cost per call (e.g. from 4.1); replaces token pricing")
    note: str | None = None


class Runtime(_M):
    version: str = "v2"
    vcpu_seconds: float = Field(0.0, ge=0, description="active vCPU-seconds per task")
    gb_seconds: float = Field(0.0, ge=0, description="memory GB-seconds per task")


class Guardrails(_M):
    content_filter: float = Field(0.0, ge=0, description="text units per task")
    denied_topics: float = Field(0.0, ge=0)
    sensitive_info: float = Field(0.0, ge=0)
    grounding: float = Field(0.0, ge=0)


class Platform(_M):
    provider: str = "bedrock"
    runtime: Runtime | None = None
    gateway_calls: float = Field(0.0, ge=0, description="tool gateway invocations per task")
    memory_events: float = Field(0.0, ge=0, description="short-term memory events per task")
    memory_records: float = Field(0.0, ge=0, description="long-term memory records per task")
    guardrails: Guardrails | None = None
    other_usd: float = Field(0.0, ge=0, description="other cost per task, USD")


class Option(_M):
    name: str
    description: str = ""
    calls: list[Call] = Field(default_factory=list)
    platform: Platform | None = None
    platform_fixed_usd_per_month: float = Field(0.0, ge=0)
    containment: float | None = Field(None, ge=0, le=1, description="overrides adoption.containment for this option")
    containment_source: str | None = None


class Sensitivity(_M):
    pct: float = Field(0.2, gt=0, lt=1)
    drivers: list[str] = Field(default_factory=lambda: ["volume", "handle_minutes", "loaded_cost_per_hour", "coverage",
                                                        "containment", "ai_cost_per_task", "one_off", "run_costs"])


DRIVERS = ("volume", "handle_minutes", "loaded_cost_per_hour", "coverage", "containment", "review_minutes",
           "ai_cost_per_task", "one_off", "run_costs", "benefit_realisation")


class Scenario(_M):
    name: str
    description: str = ""
    currency: str = "USD"
    fx_usd: float | None = Field(None, gt=0, description="1 USD in the scenario currency")
    start_date: date
    horizon_months: int = Field(36, ge=1, le=120)
    discount_rate_annual: float = Field(0.10, ge=0, le=1)
    baseline: Baseline
    adoption: Adoption
    costs: Costs = Field(default_factory=Costs)
    options: list[Option] = Field(min_length=1)
    price_overrides: list[dict[str, Any]] = Field(default_factory=list)
    sensitivity: Sensitivity = Field(default_factory=Sensitivity)
    assumptions: list[str] = Field(default_factory=list, description="free-text assumptions shown in reports")

    @field_validator("currency")
    @classmethod
    def _cur(cls, v: str) -> str:
        return v.upper()

    @model_validator(mode="after")
    def _check(self):
        if self.currency != "USD" and self.fx_usd is None:
            raise ValueError(f"fx_usd is required when currency is {self.currency} (1 USD in {self.currency})")
        if self.currency == "USD":
            self.fx_usd = 1.0
        names = [o.name for o in self.options]
        if len(names) != len(set(names)):
            raise ValueError("option names must be unique")
        for d in self.sensitivity.drivers:
            if d not in DRIVERS:
                raise ValueError(f"unknown sensitivity driver {d!r} (choose from {', '.join(DRIVERS)})")
        return self


def load_scenario(path: str | Path) -> Scenario:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return Scenario(**data)
