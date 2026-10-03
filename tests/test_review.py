"""The quarterly review, on the invented history of the fixtures."""

from datetime import date
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from cockpit import review, rules, store
from cockpit.api import create_app
from cockpit.assistant import chat, tools
from cockpit.assistant.llm import LLMError
from cockpit.importers import tr_csv
from tests.test_assistant import KEY, FakeLLM, MemoryKeyStore, text_reply

ACME, GLOBEX, FUND = "XX0000000001", "XX0000000002", "XX0000000003"
CSV = {"content-type": "text/csv"}
JULY = date(2025, 7, 2)


@pytest.fixture
def loaded(conn, sample_csv):
    """The sample history, two rule values, and a few prices."""
    tr_csv.import_csv(conn, sample_csv)
    rules.set_rule(conn, "ordres_manuels_trimestre", "2", "2025-01-01")
    rules.set_rule(conn, "ordres_manuels_trimestre", "1", "2025-04-01")
    for isin, day, price in [
        (ACME, "2025-01-06", "20"),
        (ACME, "2025-03-31", "40"),
        (FUND, "2025-03-03", "20"),
        (FUND, "2025-03-31", "22"),
    ]:
        store.set_price(conn, isin, D(price), day, "fake")
    return conn


# -- Quarters ----------------------------------------------------------------------


def test_quarters_have_bounds_and_neighbours():
    assert review.bounds("2026-T3") == (date(2026, 7, 1), date(2026, 9, 30))
    assert review.bounds("2025-T4") == (date(2025, 10, 1), date(2025, 12, 31))
    assert (review.following("2025-T4"), review.preceding("2026-T1")) == ("2026-T1", "2025-T4")
    assert review.name("2026-T3") == "T3 2026"
    for wrong in ("2026-T5", "T3 2026", "2026", ""):
        with pytest.raises(ValueError):
            review.bounds(wrong)


# -- Figures -----------------------------------------------------------------------


def test_the_review_of_a_quarter_gathers_its_figures(loaded):
    data = review.build(loaded, "2025-T1", None, JULY)
    assert (data["name"], data["from"], data["to"], data["complete"]) == (
        "T1 2025",
        "2025-01-01",
        "2025-03-31",
        True,
    )

    perf = data["performance"]
    # 80 € bought, nothing sold; at the end Acme is worth 80, Globex 20 at cost, the fund 11.
    assert (perf["start_value"], perf["bought"], perf["sold"]) == (0.0, 80.0, 0.0)
    assert (perf["end_value"], perf["gain"], perf["at_cost"]) == (111.0, 31.0, 20.0)
    assert perf["change"] == 0.3592  # purchases set aside, day by day
    assert perf["benchmark"] == {"label": "World Fund (Acc)", "from": "2025-03-03", "change": 0.1}

    counters = {c["kind"]: c for c in data["counters"]}
    orders = counters["ordres_manuels_trimestre"]
    assert (orders["count"], orders["limit"], orders["breaches"]) == ("3", "au plus 2", 1)
    assert orders["next_limit"] == "au plus 1"  # the rule in force for the quarter after
    assert counters["frais_trimestre"]["count"] == "3,00 €"
    assert counters["frais_trimestre"]["limit"] == "pas de règle"
    assert counters["nouvelle_ligne_valeur_minimum"]["label"] == "Nouvelles lignes"
    assert counters["nouvelle_ligne_valeur_minimum"]["count"] == "3"

    assert [(d["date"], d["name"], d["reason"]) for d in data["deviations"]] == [
        ("2025-02-10", "Acme", None)  # the third manual order of the quarter
    ]
    fees = data["fees"]
    assert (fees["manual_orders"], fees["free_trades"], fees["order_fees"]) == (3, 1, 3.0)
    assert (fees["manual_amount"], fees["share_of_amount"]) == (70.0, 0.0429)
    assert data["opened"] == ["Acme", "Globex", "World Fund (Acc)"] and data["closed"] == []
    assert [q["manual_orders"] for q in data["rotation"]] == [3]


def test_a_later_quarter_sees_what_was_closed_and_the_whole_rotation(loaded):
    data = review.build(loaded, "2025-T2", None, JULY)
    assert [(c["name"], c["account"]) for c in data["closed"]] == [("Globex", "CTO")]
    assert data["opened"] == ["Globex"]  # bought again, in the PEA
    assert [q["manual_orders"] for q in data["rotation"]] == [3, 3]
    assert {p["name"] for p in data["positions"]} == {"Acme", "Globex", "World Fund (Acc)"}
    assert all(p["halalitude"] == "non renseignée" for p in data["positions"])
    assert data["halalitude"]["missing"] == 3 and len(data["halalitude"]["attention"]) == 3


def test_a_quarter_in_progress_stops_today_and_a_future_one_is_refused(loaded):
    running = review.build(loaded, "2025-T2", None, date(2025, 4, 20))
    assert (running["complete"], running["as_of"]) == (False, "2025-04-20")
    assert running["closed"] == [] or running["closed"][0]["name"] == "Globex"
    assert running["fees"]["manual_orders"] == 3  # the report counts the whole quarter imported
    with pytest.raises(ValueError):
        review.build(loaded, "2025-T4", None, JULY)


def test_without_prices_the_quarter_is_counted_at_cost(conn, sample_csv):
    tr_csv.import_csv(conn, sample_csv)
    perf = review.build(conn, "2025-T1", None, JULY)["performance"]
    assert (perf["end_value"], perf["at_cost"], perf["gain"]) == (80.0, 80.0, 0.0)
    assert perf["benchmark"] is None
    # A quarter without a trade or a price: the last known value carries over.
    quiet = review.build(conn, "2025-T3", None, date(2025, 9, 1))["performance"]
    assert (quiet["available"], quiet["start_value"], quiet["end_value"]) == (True, 65.0, 65.0)
    assert (quiet["gain"], quiet["change"]) == (0.0, 0.0)


# -- Keeping -----------------------------------------------------------------------


def test_a_review_is_kept_and_generating_again_keeps_the_conclusions(loaded):
    assert review.listing(loaded, JULY)["due"] == {"quarter": "2025-T2", "name": "T2 2025"}
    first = review.generate(loaded, "2025-T2", None, JULY)
    assert first["data"]["quarter"] == "2025-T2" and first["commentary"] is None
    assert review.set_conclusions(loaded, "2025-T2", "  Moins d'ordres au T3.  ")
    review.set_commentary(loaded, "2025-T2", "Lecture des chiffres.", None)

    listing = review.listing(loaded, JULY)
    assert listing["due"] is None
    assert [(r["quarter"], r["has_commentary"]) for r in listing["reviews"]] == [("2025-T2", True)]
    assert [q["quarter"] for q in listing["quarters"]] == ["2025-T3", "2025-T2", "2025-T1"]

    again = review.generate(loaded, "2025-T2", None, JULY)
    assert again["conclusions"] == "Moins d'ordres au T3."
    assert again["commentary"] is None  # it was written on the old figures
    assert review.set_conclusions(loaded, "2024-T1", "x") is False
    assert review.delete(loaded, "2025-T2") and review.get(loaded, "2025-T2") is None


def test_the_readable_version_says_what_it_is(loaded):
    kept = review.generate(loaded, "2025-T1", None, JULY)
    review.set_conclusions(loaded, "2025-T1", "Tenir la règle des deux ordres.")
    text = review.markdown(review.get(loaded, "2025-T1"))
    assert text.startswith("# Revue trimestrielle — T1 2025\n\nDu 01/01/2025 au 31/03/2025")
    assert "| Ordres manuels par trimestre | 3 | au plus 2 | 1 |" in text
    assert "| 10/02/2025 | Acme |" in text and "**sans motif**" in text
    assert "| Gain ou perte du trimestre | +31,00 € |" in text
    assert "| World Fund (Acc), même période | +10,0 % |" in text
    assert "## 10. Repères pour T2 2025" in text
    assert "| Ordres manuels par trimestre | 3 | au plus 1 |" in text
    assert "## Mes conclusions\n\nTenir la règle des deux ordres." in text
    assert "pas un conseil en investissement" in text
    assert "## Commentaire de l'assistant" not in text and kept["commentary"] is None


# -- Commentary --------------------------------------------------------------------


def test_the_assistant_comments_the_review_in_a_conversation(loaded):
    review.generate(loaded, "2025-T1", None, JULY)
    llm = FakeLLM(text_reply("Trois ordres pour deux prévus.", input_tokens=900, output_tokens=40))
    kept = review.comment(loaded, llm, KEY, "2025-T1", "claude-sonnet-5-5")
    assert kept["commentary"] == "Trois ordres pour deux prévus."
    assert kept["conversation_id"] is not None and kept["commentary_at"]

    sent = llm.calls[0]["messages"][0]["content"][0]["text"]
    assert sent.startswith("Revue T1 2025 : commentaire demandé.")
    assert "| Ordres manuels par trimestre | 3 | au plus 2 | 1 |" in sent
    assert "consigne d'achat ou de vente" in sent
    # An ordinary conversation: listed with the others, and counted in the month's usage.
    assert chat.listing(loaded)[0]["title"].startswith("Revue T1 2025")
    assert chat.month_usage(loaded)["calls"] == 1


def test_a_failed_commentary_leaves_nothing_behind(loaded):
    review.generate(loaded, "2025-T1", None, JULY)
    llm = FakeLLM(LLMError("quota", "Quota atteint."))
    with pytest.raises(review.CommentaryError, match="Quota atteint"):
        review.comment(loaded, llm, KEY, "2025-T1", None)
    assert review.get(loaded, "2025-T1")["commentary"] is None
    assert chat.listing(loaded) == []
    with pytest.raises(review.CommentaryError):
        review.comment(loaded, FakeLLM(), KEY, "2019-T1", None)


def test_the_assistant_reads_the_reviews(loaded):
    empty, failed = tools.run(loaded, "lire_revue", {})
    assert failed is False and "Aucune revue" in empty
    review.generate(loaded, "2025-T1", None, JULY)
    told, failed = tools.run(loaded, "lire_revue", {"trimestre": "2025-T1"})
    assert failed is False and "Revue trimestrielle — T1 2025" in told
    assert tools.run(loaded, "lire_revue", {"trimestre": "2020-T1"})[1] is True


# -- API -----------------------------------------------------------------------------


def test_reviews_over_the_api(tmp_path, sample_csv):
    llm, key_store = FakeLLM(text_reply("Commentaire.")), MemoryKeyStore()
    client = TestClient(create_app(tmp_path / "review.db", llm=llm, key_store=key_store))
    client.post("/api/import/csv", content=sample_csv.encode(), headers=CSV)

    assert client.get("/api/reviews").json()["reviews"] == []
    assert client.post("/api/reviews", json={"quarter": "nope"}).status_code == 400
    created = client.post("/api/reviews", json={"quarter": "2025-T1"})
    assert created.status_code == 201 and created.json()["data"]["name"] == "T1 2025"
    assert client.get("/api/reviews/2025-T1").json()["quarter"] == "2025-T1"
    assert client.get("/api/reviews/2024-T1").status_code == 404

    saved = client.put("/api/reviews/2025-T1/conclusions", json={"text": "À tenir."}).json()
    assert saved["conclusions"] == "À tenir."

    # No key: nothing is sent. With one, the commentary comes back with the review.
    assert client.post("/api/reviews/2025-T1/commentary", json={}).status_code == 400
    key_store.set(KEY)
    commented = client.post("/api/reviews/2025-T1/commentary", json={}).json()
    assert commented["commentary"] == "Commentaire."

    export = client.get("/api/reviews/2025-T1/export")
    assert export.headers["content-disposition"] == 'attachment; filename="revue-2025-T1.md"'
    assert "## Commentaire de l'assistant\n\nCommentaire." in export.text
    assert client.delete("/api/reviews/2025-T1").json() == {"deleted": "2025-T1"}
