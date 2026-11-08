from datetime import date

import pytest

from roi_calc import catalog as cat


@pytest.fixture(scope="module")
def cats():
    return cat.load()


def test_every_entry_has_source_and_date(cats):
    for _pid, c in cats.items():
        assert c["as_of"] and c["source"]
        for mid, m in c["models"].items():
            assert m.get("source") or c.get("source"), mid
            assert m.get("as_of") or c.get("as_of"), mid


def test_openai_tiers_routes_long_context(cats):
    r = cat.resolve(cats, "openai", "gpt-6.1-sol")
    assert r.short == {"input": 2.0, "cached": 0.1, "cache_write": 2.5, "output": 10.0}
    assert r.long == {"input": 4.0, "cached": 0.2, "cache_write": 5.0, "output": 15.0}
    assert cat.resolve(cats, "openai", "gpt-6.1-sol", tier="batch").short["output"] == 5.0
    assert cat.resolve(cats, "openai", "gpt-6.1-sol", tier="fast").short["input"] == 4.0
    assert cat.resolve(cats, "openai", "gpt-6.1-sol", route="regional").short["input"] == pytest.approx(2.2)


def test_bedrock_openai_priority_is_2x_and_geo_is_10pct(cats):
    pri = cat.resolve(cats, "bedrock", "global.openai.gpt-6.1-sol", tier="priority")
    assert pri.model == "openai.gpt-6.1-sol" and pri.short["input"] == 4.0
    assert cat.resolve(cats, "bedrock", "openai.gpt-6.1-sol", route="geo").short["output"] == pytest.approx(11.0)
    assert cat.resolve(cats, "bedrock", "amazon.nova-pro", route="in_region").short["input"] == 0.8
    assert cat.resolve(cats, "bedrock", "anthropic.claude-sonnet-5-5").long is None


@pytest.mark.parametrize("kw", [{"tier": "priority", "model": "openai.gpt-6-astra"}, {"route": "global", "model": "amazon.nova-micro"},
                                {"tier": "fast", "model": "openai.gpt-6.1-sol"}])
def test_unsupported_refused(cats, kw):
    with pytest.raises(cat.CatalogError, match="not supported"):
        cat.resolve(cats, "bedrock", **kw)


def test_unknown_model_and_provider(cats):
    with pytest.raises(cat.CatalogError, match="unknown model"):
        cat.resolve(cats, "openai", "gpt-9")
    with pytest.raises(cat.CatalogError, match="unknown provider"):
        cat.resolve(cats, "azure", "x")


def test_promotions_and_overrides(cats):
    c = {**cats, "openai": {**cats["openai"], "models": {**cats["openai"]["models"]}}}
    c["openai"]["models"]["gpt-6.1-sol"] = {**c["openai"]["models"]["gpt-6.1-sol"],
                                           "promos": [{"rates": {"input": 1.0}, "valid_until": "2026-11-30"}]}
    assert cat.resolve(c, "openai", "gpt-6.1-sol", on=date(2026, 11, 30)).short["input"] == 1.0
    assert cat.resolve(c, "openai", "gpt-6.1-sol", on=date(2026, 12, 1)).short["input"] == 2.0
    assert any("ended" in i for i in cat.check(c, date(2026, 12, 1)))
    ov = [{"provider": "openai", "model": "gpt-6.1-sol", "rates": {"input": 1.5}}]
    r = cat.resolve(cats, "openai", "gpt-6.1-sol", tier="batch", overrides=ov)
    assert r.short["input"] == 0.75 and r.override
    fin = [{"provider": "openai", "model": "gpt-6.1-sol", "tier": "batch", "final": True, "rates": {"input": 0.6, "output": 3}}]
    r = cat.resolve(cats, "openai", "gpt-6.1-sol", tier="batch", overrides=fin)
    assert r.short["input"] == 0.6 and r.short["cached"] == 0.1 and r.long is None


def test_validation():
    bad = {"provider": "x", "as_of": "2026-01-01", "source": "s", "routes": {"global": {"multiplier": 1}},
           "tiers": {"standard": {"multiplier": 1}}, "models": {"m": {"rates": {"input": 1}, "tiers": ["standard"], "routes": ["global"]}}}
    with pytest.raises(cat.CatalogError, match="rates missing"):
        cat.validate(bad)
    bad["models"]["m"]["rates"] = {"input": 1, "cached": 1, "cache_write": 1, "output": 1}
    bad["models"]["m"]["tiers"] = ["turbo"]
    with pytest.raises(cat.CatalogError, match="no multiplier"):
        cat.validate(bad)


def test_check_lists_verify(cats):
    issues = cat.check(cats, date(2026, 11, 8))
    assert any("claude-sonnet-5-5" in i for i in issues)
    assert not any("90 days" in i for i in issues)
    assert any("90 days" in i for i in cat.check(cats, date(2027, 3, 1)))
