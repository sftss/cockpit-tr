"""V1: rules checked after the fact, compliance status, roadmap, physical gold."""

from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from cockpit import compliance, db, gold, roadmap, rules, settings_file, store
from cockpit.api import create_app
from cockpit.importers import tr_csv
from cockpit.market import service
from cockpit.market.provider import Listing, ProviderError
from tests.fakes import FakeProvider, series

ACME, GLOBEX, FUND = "XX0000000001", "XX0000000002", "XX0000000003"
CSV = {"content-type": "text/csv"}


@pytest.fixture
def loaded(conn, sample_csv):
    tr_csv.import_csv(conn, sample_csv)
    return conn


def state_on(conn, day: str) -> dict:
    report = store.current_report(conn)
    history = store.value_history(conn)
    return rules.state(
        store.all_transactions(conn),
        rules.list_rules(conn),
        [(p["date"], D(str(p["value"]))) for p in history["points"]],
        [
            {"name": p["name"], "account": p["account"], "weight": p["weight_total"]}
            for p in report["positions"]
        ],
        dict(conn.execute("SELECT transaction_id, reason FROM deviation_notes").fetchall()),
        date.fromisoformat(day),
    )


def breaches(state: dict, kind: str) -> list[str]:
    """Days of the transactions that departed from this rule, oldest first."""
    return sorted(
        d["date"] for d in state["deviations"] for b in d["breaches"] if b["kind"] == kind
    )


# -- Rules -------------------------------------------------------------------------


def test_without_rules_nothing_is_a_departure(loaded):
    state = state_on(loaded, "2025-06-30")
    assert state["deviations"] == [] and state["has_rules"] is False
    counters = {line["kind"]: line for line in state["current"]}
    # The counters are still shown, without a limit.
    assert counters["ordres_manuels_trimestre"]["count"] == 3
    assert counters["ordres_manuels_trimestre"]["limit"] is None
    assert counters["frais_trimestre"]["count"] == 2.1


def test_each_kind_of_rule_on_the_sample_history(loaded):
    for kind, value in [
        ("ordres_manuels_trimestre", 2),
        ("frais_trimestre", "2,50"),
        ("nouvelle_ligne_valeur_minimum", 1000),
        ("ventes_trimestre", 0),
        ("lignes_soldees_trimestre", 0),
        ("rechargements_carte_trimestre", 0),
        ("poids_maximum", 35),
    ]:
        rules.set_rule(loaded, kind, value, "2025-01-01")
    rules.set_rule(loaded, "achat_minimum", 25, "2025-01-01", account="CTO")
    state = state_on(loaded, "2025-06-30")

    # Third paid order of each quarter; free savings-plan executions do not count.
    assert breaches(state, "ordres_manuels_trimestre") == ["2025-02-10", "2025-06-03"]
    # Order fees only: 1 + 1 + 1 = 3 on 10 February (the 0.70 paid on the card
    # deposit is another rule's business); the second quarter stays under.
    assert breaches(state, "frais_trimestre") == ["2025-02-10"]
    # Paid buys under 25 € on the CTO; the PEA buy of 20 € is not covered by the rule.
    assert breaches(state, "achat_minimum") == ["2025-01-06", "2025-02-03"]
    # Every first buy of a line, in either account, even through the savings plan.
    assert breaches(state, "nouvelle_ligne_valeur_minimum") == [
        "2025-01-06",
        "2025-02-03",
        "2025-03-03",
        "2025-06-03",
    ]
    assert breaches(state, "ventes_trimestre") == ["2025-04-15", "2025-05-05"]
    assert breaches(state, "lignes_soldees_trimestre") == ["2025-05-05"]  # the partial sale is not
    assert breaches(state, "rechargements_carte_trimestre") == ["2025-01-02"]

    sale = next(d for d in state["deviations"] if d["date"] == "2025-05-05")
    assert [b["kind"] for b in sale["breaches"]] == ["ventes_trimestre", "lignes_soldees_trimestre"]
    assert "rupture de conformité ou de thèse" in sale["breaches"][0]["detail"]

    counters = {line["kind"]: line for line in state["current"]}
    assert state["quarter"] == "2025-T2"
    orders = counters["ordres_manuels_trimestre"]
    assert (orders["count"], orders["limit"], orders["breaches"]) == (3, 2.0, 1)
    assert (counters["ventes_trimestre"]["count"], counters["ventes_trimestre"]["breaches"]) == (
        2,
        2,
    )
    assert counters["achat_minimum"]["minimums"] == [{"account": "CTO", "value": 25.0}]
    # Weights on cost (no prices): Acme 25 of 65 is above 35 %, the two others at 20 are not.
    assert [line["name"] for line in counters["poids_maximum"]["lines"]] == ["Acme"]


def test_a_rule_says_nothing_about_the_days_before_it(loaded):
    rules.set_rule(loaded, "ordres_manuels_trimestre", 0, "2025-04-01")
    state = state_on(loaded, "2025-06-30")
    assert breaches(state, "ordres_manuels_trimestre") == ["2025-04-15", "2025-05-05", "2025-06-03"]


def test_a_new_value_closes_the_previous_one(loaded):
    first = rules.set_rule(loaded, "ordres_manuels_trimestre", 10, "2025-01-01")
    rules.set_rule(loaded, "ordres_manuels_trimestre", 0, "2025-04-01")
    stored = {rule.id: rule for rule in rules.list_rules(loaded)}
    assert stored[first].valid_to == "2025-03-31"
    # Ten allowed in the first quarter, none from April.
    state = state_on(loaded, "2025-06-30")
    assert breaches(state, "ordres_manuels_trimestre") == ["2025-04-15", "2025-05-05", "2025-06-03"]

    # A value dated before an existing one stops where that one starts.
    early = rules.set_rule(loaded, "ordres_manuels_trimestre", 5, "2024-06-01")
    stored = {rule.id: rule for rule in rules.list_rules(loaded)}
    assert (stored[early].valid_to, stored[first].valid_to) == ("2024-12-31", "2025-03-31")
    rules.delete_rule(loaded, early)

    # Same day again: the value is corrected in place, not duplicated.
    rules.set_rule(loaded, "ordres_manuels_trimestre", 2, "2025-04-01")
    assert len(rules.list_rules(loaded)) == 2
    assert breaches(state_on(loaded, "2025-06-30"), "ordres_manuels_trimestre") == ["2025-06-03"]


def test_rule_values_are_checked(loaded):
    with pytest.raises(ValueError):
        rules.set_rule(loaded, "nope", 1)
    with pytest.raises(ValueError):
        rules.set_rule(loaded, "frais_trimestre", -1)
    with pytest.raises(ValueError):
        rules.set_rule(loaded, "frais_trimestre", 4, account="CTO")  # not a per-account rule
    with pytest.raises(ValueError):
        rules.set_rule(loaded, "achat_minimum", 100, account="NOPE")
    with pytest.raises(ValueError):
        rules.set_rule(loaded, "frais_trimestre", 4, "le 1er octobre")


def test_a_written_reason_is_kept_with_the_departure(loaded):
    rules.set_rule(loaded, "ventes_trimestre", 0, "2025-01-01")
    state = state_on(loaded, "2025-06-30")
    assert state["pending"] == 2
    sale = state["deviations"][0]
    assert (sale["date"], sale["reason"]) == ("2025-05-05", None)  # most recent first

    rules.set_reason(loaded, sale["transaction_id"], "  Rupture de conformité  ")
    state = state_on(loaded, "2025-06-30")
    assert state["deviations"][0]["reason"] == "Rupture de conformité" and state["pending"] == 1
    rules.set_reason(loaded, sale["transaction_id"], "")  # an empty reason removes it
    assert state_on(loaded, "2025-06-30")["pending"] == 2
    with pytest.raises(KeyError):
        rules.set_reason(loaded, "unknown", "x")


# -- Compliance ----------------------------------------------------------------------


def test_compliance_status_goes_stale_after_ninety_days(conn):
    today = date(2026, 10, 2)
    compliance.record(conn, " xx0000000001 ", "conforme", "2026-07-04", "vu dans l'app")
    entry = compliance.latest(conn)[ACME]
    fresh = compliance.view(entry, today)
    assert (fresh["state"], fresh["age_days"], fresh["due_on"]) == ("a_jour", 90, "2026-10-02")
    assert compliance.view(entry, today + timedelta(days=1))["state"] == "a_reverifier"
    assert compliance.view(None, today)["state"] == "non_renseigne"

    # A later check replaces the status shown; the earlier one stays in the history.
    compliance.record(conn, ACME, "non_conforme", "2026-09-30", None)
    assert compliance.view(compliance.latest(conn)[ACME], today)["status"] == "non_conforme"
    assert conn.execute("SELECT COUNT(*) FROM compliance").fetchone()[0] == 2

    with pytest.raises(ValueError):
        compliance.record(conn, ACME, "halal", None, None)
    with pytest.raises(ValueError):
        compliance.record(
            conn, ACME, "conforme", (date.today() + timedelta(days=1)).isoformat(), None
        )
    with pytest.raises(ValueError):
        compliance.record(conn, ACME, "conforme", "hier", None)


def test_compliance_overview_lists_held_lines_then_targets(loaded):
    roadmap.create(loaded, {"name": "Initech", "isin": "XX0000000009"})
    compliance.record(loaded, ACME, "conforme", None, None)
    compliance.record(loaded, "XX0000000777", "douteux", None, None)  # neither held nor a target
    view = compliance.overview(loaded, store.held_names(loaded))
    assert [(i["name"], i["group"]) for i in view["items"]] == [
        ("Acme", "detenu"),
        ("Globex", "detenu"),
        ("World Fund (Acc)", "detenu"),
        ("Initech", "cible"),
        ("XX0000000777", "autre"),
    ]
    assert view["summary"] == {"held": 3, "missing": 3, "stale": 0, "not_compliant": 0}

    position = next(p for p in store.current_report(loaded)["positions"] if p["isin"] == ACME)
    assert (position["zoya"]["status"], position["zoya"]["state"]) == ("conforme", "a_jour")


# -- Roadmap -------------------------------------------------------------------------


def test_roadmap_items_and_the_entry_price_signal(loaded):
    first = roadmap.create(
        loaded,
        {
            "name": "Initech",
            "isin": "xx0000000009",
            "account": "PEA",
            "amount": "150",
            "entry_condition": "Après les résultats annuels",
            "entry_price": "100,5",
            "thesis": "Trois lignes.",
            "status": "prevu",
        },
    )
    roadmap.create(loaded, {"name": "Sans titre coté"})
    provider = FakeProvider()
    provider.listings["XX0000000009"] = [Listing("INI.PA", "Initech", "PAR", "EQUITY")]
    provider.charts["INI.PA"] = series("INI.PA", "EUR", "PAR", {"2025-06-30": "101"})
    market = service.Market(provider)

    assert roadmap.refresh_prices(loaded, market)["updated"] == 1
    item = roadmap.items(loaded)["items"][0]
    assert (item["name"], item["symbol"], item["last_price"], item["reached"]) == (
        "Initech",
        "INI.PA",
        101.0,
        False,
    )
    assert (item["isin"], item["account"], item["amount"], item["entry_price"]) == (
        "XX0000000009",
        "PEA",
        150.0,
        100.5,
    )
    assert item["zoya"]["state"] == "non_renseigne"

    # The price falls to the entry price: the target is flagged, nothing else happens.
    provider.charts["INI.PA"] = series("INI.PA", "EUR", "PAR", {"2025-07-01": "100.5"})
    roadmap.refresh_prices(loaded, service.Market(provider))
    assert roadmap.items(loaded)["items"][0]["reached"] is True

    # Done or abandoned targets are no longer flagged nor refreshed.
    roadmap.update(
        loaded,
        first,
        {
            "name": "Initech",
            "isin": "XX0000000009",
            "status": "execute",
            "symbol": "INI.PA",
            "entry_price": "100,5",
        },
    )
    done = next(i for i in roadmap.items(loaded)["items"] if i["id"] == first)
    assert (done["status"], done["reached"]) == ("execute", False)
    assert roadmap.refresh_prices(loaded, service.Market(provider))["updated"] == 0

    with pytest.raises(ValueError):
        roadmap.create(loaded, {"name": " "})
    with pytest.raises(ValueError):
        roadmap.create(loaded, {"name": "X", "entry_price": "-3"})
    with pytest.raises(ValueError):
        roadmap.create(loaded, {"name": "X", "status": "acheter"})
    assert roadmap.delete(loaded, first) is True and roadmap.delete(loaded, first) is False


def test_roadmap_prices_stop_on_a_refusal(loaded):
    roadmap.create(loaded, {"name": "A", "isin": "XX0000000008"})
    roadmap.create(loaded, {"name": "B", "isin": "XX0000000009"})
    provider = FakeProvider()
    provider.fail = ProviderError("refused", "HTTP 429")
    outcome = roadmap.refresh_prices(loaded, service.Market(provider))
    assert (outcome["updated"], outcome["refused"], len(outcome["errors"])) == (0, True, 1)
    assert len(provider.calls) == 1  # the second target was not asked


# -- Physical gold -------------------------------------------------------------------


def test_gold_is_valued_at_the_world_price_in_euros(conn):
    gold.add_lot(
        conn, {"label": "Pièces", "grams": "10", "cost": "600", "acquired_on": "2024-03-01"}
    )
    gold.add_lot(conn, {"label": "Lingotin", "grams": "5,5", "cost": "400"})
    empty = gold.summary(conn)
    assert (empty["grams"], empty["cost"], empty["value"], empty["price_date"]) == (
        15.5,
        1000.0,
        None,
        None,
    )

    provider = FakeProvider()
    # 3 421.382448 $ an ounce at 1.10 $ for one euro: exactly 100 € a gram.
    provider.charts["GC=F"] = series("GC=F", "USD", "CMX", {"2025-06-30": "3421.382448"})
    provider.charts["EURUSD=X"] = series("EURUSD=X", "USD", "CCY", {"2025-06-30": "1.10"})
    assert gold.refresh_price(conn, service.Market(provider)) == D("100")

    data = gold.summary(conn)
    assert (data["eur_per_gram"], data["value"], data["latent"], data["latent_pct"]) == (
        100.0,
        1550.0,
        550.0,
        0.55,
    )
    assert [(lot["label"], lot["value"], lot["latent"]) for lot in data["lots"]] == [
        ("Pièces", 1000.0, 400.0),
        ("Lingotin", 550.0, 150.0),
    ]

    # A lot without a known price paid: the value stays, the result is not invented.
    gold.add_lot(conn, {"label": "Héritage", "grams": 1})
    partial = gold.summary(conn)
    assert (partial["value"], partial["cost"], partial["latent"]) == (1650.0, None, None)

    with pytest.raises(ValueError):
        gold.add_lot(conn, {"label": "X", "grams": "0"})
    with pytest.raises(ValueError):
        gold.add_lot(conn, {"label": "", "grams": "1"})


# -- Settings file -------------------------------------------------------------------


def test_settings_file_round_trip(loaded, tmp_path):
    rules.set_rule(loaded, "ordres_manuels_trimestre", 10, "2025-01-01")
    rules.set_rule(loaded, "ordres_manuels_trimestre", 4, "2025-04-01", note="objectif")
    rules.set_rule(loaded, "achat_minimum", 100, "2025-04-01", account="CTO")
    roadmap.create(loaded, {"name": "Initech", "isin": "XX0000000009", "entry_price": "100"})
    exported = settings_file.export(loaded)
    assert exported["format"] == "cockpit-tr/reglages" and len(exported["rules"]) == 3

    other = db.connect(tmp_path / "other.db")
    assert settings_file.load(other, exported) == {
        "rules_added": 3,
        "rules_present": 0,
        "roadmap_added": 1,
        "roadmap_present": 0,
    }
    again = settings_file.load(other, exported)
    assert (again["rules_added"], again["roadmap_added"]) == (0, 0)
    assert settings_file.export(other)["rules"] == exported["rules"]
    assert settings_file.export(other)["roadmap"] == exported["roadmap"]

    for bad in ({"format": "autre"}, [], {"format": "cockpit-tr/reglages", "version": 99}):
        with pytest.raises(ValueError):
            settings_file.load(other, bad)
    other.close()


# -- API -----------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path, sample_csv):
    provider = FakeProvider()
    provider.charts["GC=F"] = series("GC=F", "USD", "CMX", {"2025-06-30": "3421.382448"})
    provider.charts["EURUSD=X"] = series("EURUSD=X", "USD", "CCY", {"2025-06-30": "1.10"})
    client = TestClient(create_app(tmp_path / "v1.db", provider=provider))
    client.post("/api/import/csv", content=sample_csv.encode(), headers=CSV)
    return client


def test_rules_over_the_api(client):
    assert client.get("/api/rules").json()["has_rules"] is False
    created = client.post(
        "/api/rules", json={"kind": "ventes_trimestre", "value": 0, "valid_from": "2025-01-01"}
    )
    assert created.status_code == 201
    state = client.get("/api/rules").json()
    assert [d["date"] for d in state["deviations"]] == ["2025-05-05", "2025-04-15"]
    assert state["pending"] == 2 and len(state["kinds"]) == len(rules.KINDS)

    tx_id = state["deviations"][0]["transaction_id"]
    assert (
        client.put(f"/api/deviations/{tx_id}", json={"reason": "Thèse rompue"}).status_code == 200
    )
    assert client.get("/api/rules").json()["deviations"][0]["reason"] == "Thèse rompue"
    assert client.put("/api/deviations/unknown", json={"reason": "x"}).status_code == 404

    assert client.post("/api/rules", json={"kind": "nope", "value": 1}).status_code == 400
    assert client.delete(f"/api/rules/{created.json()['id']}").status_code == 200
    assert client.delete(f"/api/rules/{created.json()['id']}").status_code == 404
    assert client.get("/api/rules").json()["deviations"] == []


def test_compliance_roadmap_and_gold_over_the_api(client):
    assert client.get("/api/compliance").json()["summary"]["missing"] == 3
    ok = client.post("/api/compliance", json={"isin": ACME, "status": "conforme"})
    assert ok.status_code == 201
    assert client.post("/api/compliance", json={"isin": ACME, "status": "?"}).status_code == 400
    assert client.get("/api/compliance").json()["summary"]["missing"] == 2
    report = client.get("/api/report").json()
    assert report["total"] == {"basis": "cost", "amount": 65.0, "lines": 3}
    assert sum(p["weight_total"] for p in report["positions"]) == pytest.approx(1, abs=0.001)

    item = client.post("/api/roadmap", json={"name": "Initech", "entry_price": 100}).json()["id"]
    assert client.put(f"/api/roadmap/{item}", json={"name": "Initech SA"}).status_code == 200
    assert client.get("/api/roadmap").json()["items"][0]["name"] == "Initech SA"
    assert client.post("/api/roadmap", json={"name": ""}).status_code == 400
    assert client.put("/api/roadmap/999", json={"name": "X"}).status_code == 404
    assert client.post("/api/roadmap/prices").json()["updated"] == 0  # no instrument named
    assert client.delete(f"/api/roadmap/{item}").status_code == 200

    lot = client.post("/api/gold/lots", json={"label": "Pièces", "grams": 10, "cost": 600})
    assert lot.status_code == 201
    assert client.post("/api/gold/lots", json={"label": "X", "grams": -1}).status_code == 400
    priced = client.post("/api/gold/price").json()
    assert (priced["eur_per_gram"], priced["value"], priced["latent"]) == (100.0, 1000.0, 400.0)
    assert (
        client.put(
            f"/api/gold/lots/{lot.json()['id']}", json={"label": "Pièces", "grams": 20}
        ).status_code
        == 200
    )
    assert client.get("/api/gold").json()["value"] == 2000.0
    assert client.delete(f"/api/gold/lots/{lot.json()['id']}").status_code == 200
    assert client.get("/api/gold").json()["lots"] == []


def test_settings_file_over_the_api(client):
    client.post(
        "/api/rules", json={"kind": "frais_trimestre", "value": "4", "valid_from": "2025-01-01"}
    )
    exported = client.get("/api/settings/export")
    assert "attachment" in exported.headers["content-disposition"]
    assert client.post("/api/settings/import", content=exported.content).json()["rules_added"] == 0
    assert client.post("/api/settings/import", content=b"pas du json").status_code == 400
    assert client.post("/api/settings/import", content=b'{"format": "autre"}').status_code == 400
