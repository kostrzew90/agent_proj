from .conftest import insert_call


def test_cost_computed_from_pricing(db):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO model_pricing (provider, model, usd_per_mtok_in, usd_per_mtok_out)"
            " VALUES ('test', 'pricing-test-model', 0.15, 0.60)"
        )
    insert_call(db, provider="test", model="pricing-test-model", tokens_in=1_000_000, tokens_out=1_000_000)
    with db.cursor() as cur:
        cur.execute("SELECT effective_cost_usd, pricing_missing FROM v_llm_calls_costed WHERE model = 'pricing-test-model'")
        cost, missing = cur.fetchone()
    assert float(cost) == 0.75
    assert missing is False


def test_missing_pricing_gives_null_not_zero(db):
    insert_call(db, model="nieznany/model", tokens_in=1_000_000, tokens_out=1_000_000)
    with db.cursor() as cur:
        cur.execute("SELECT effective_cost_usd, pricing_missing FROM v_llm_calls_costed WHERE model = 'nieznany/model'")
        cost, missing = cur.fetchone()
    assert cost is None, "brak cennika musi dawać NULL, nie 0 — inaczej koszt cicho znika"
    assert missing is True


def test_explicit_cost_wins_over_pricing(db):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO model_pricing (provider, model, usd_per_mtok_in, usd_per_mtok_out)"
            " VALUES ('test', 'explicit-cost-model', 100.0, 100.0)"
        )
    insert_call(db, provider="test", model="explicit-cost-model", cost_usd=0.5, tokens_in=1_000_000, tokens_out=1_000_000)
    with db.cursor() as cur:
        cur.execute("SELECT effective_cost_usd FROM v_llm_calls_costed WHERE model = 'explicit-cost-model'")
        assert float(cur.fetchone()[0]) == 0.5


def test_pricing_is_versioned_by_valid_from(db):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO model_pricing (provider, model, usd_per_mtok_in, usd_per_mtok_out, valid_from)"
            " VALUES ('test', 'versioned-model', 1.0, 0.0, '2020-01-01T00:00:00Z'),"
            "        ('test', 'versioned-model', 2.0, 0.0, '2030-01-01T00:00:00Z')"
        )
    insert_call(db, provider="test", model="versioned-model", tokens_in=1_000_000, ts="2025-01-01T00:00:00Z")
    with db.cursor() as cur:
        cur.execute("SELECT effective_cost_usd FROM v_llm_calls_costed WHERE model = 'versioned-model'")
        assert float(cur.fetchone()[0]) == 1.0, "musi obowiązywać cennik z momentu wywołania"


def test_free_model_is_zero_not_null(db):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO model_pricing (provider, model, usd_per_mtok_in, usd_per_mtok_out)"
            " VALUES ('test', 'free-test-model', 0.0, 0.0)"
        )
    insert_call(db, provider="test", model="free-test-model", tokens_in=1_000_000)
    with db.cursor() as cur:
        cur.execute("SELECT effective_cost_usd, pricing_missing FROM v_llm_calls_costed WHERE model = 'free-test-model'")
        cost, missing = cur.fetchone()
    assert float(cost) == 0.0
    assert missing is False
