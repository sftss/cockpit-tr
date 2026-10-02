import pytest
from fastapi.testclient import TestClient

from cockpit.api import create_app

CSV = {"content-type": "text/csv"}


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path / "api.db"))


def test_empty_state_then_import_then_report(client, sample_csv):
    assert client.get("/api/state").json()["transactions"] == 0
    assert client.get("/api/report").json()["positions"] == []

    report = client.post("/api/import/csv", content=sample_csv.encode(), headers=CSV).json()
    assert (report["inserted"], report["already_present"]) == (18, 0)

    state = client.get("/api/state").json()
    assert (state["transactions"], state["from"], state["to"]) == (18, "2025-01-02", "2025-06-03")
    data = client.get("/api/report").json()
    assert len(data["positions"]) == 3 and len(data["closed"]) == 1


def test_import_refuses_wrong_files(client):
    assert client.post("/api/import/csv", content=b"a;b\n1;2\n", headers=CSV).status_code == 400
    wrong_type = client.post(
        "/api/import/csv", content=b"x", headers={"content-type": "text/plain"}
    )
    assert wrong_type.status_code == 415


def test_price_entry(client, sample_csv):
    client.post("/api/import/csv", content=sample_csv.encode(), headers=CSV)
    ok = client.put("/api/prices/XX0000000001", json={"price": "30,5", "date": "2025-06-30"})
    assert ok.json() == {"isin": "XX0000000001", "price": 30.5, "date": "2025-06-30"}
    acme = next(
        p for p in client.get("/api/report").json()["positions"] if p["isin"] == "XX0000000001"
    )
    assert (acme["price"], acme["value"], acme["price_date"]) == (30.5, 30.5, "2025-06-30")

    assert client.put("/api/prices/XX0000000001", json={"price": "-1"}).status_code == 400
    assert client.put("/api/prices/XX0000000001", json={"price": "abc"}).status_code == 400
    assert client.put("/api/prices/UNKNOWN", json={"price": "1"}).status_code == 404


def test_snapshot_and_exports(client, sample_csv):
    assert client.post("/api/snapshots", json={}).status_code == 400  # nothing to freeze yet
    client.post("/api/import/csv", content=sample_csv.encode(), headers=CSV)
    client.put("/api/prices/XX0000000001", json={"price": "30"})

    created = client.post("/api/snapshots", json={"label": "fin T2"})
    assert created.status_code == 201
    snapshot_id = created.json()["id"]

    listing = client.get("/api/snapshots").json()
    assert [(s["id"], s["label"], s["positions"]) for s in listing] == [(snapshot_id, "fin T2", 3)]

    exported = client.get(f"/api/snapshots/{snapshot_id}/export.json")
    assert "attachment" in exported.headers["content-disposition"]
    body = exported.json()
    assert body["fees"]["total"] == 5.80 and len(body["positions"]) == 3

    sheet = client.get(f"/api/snapshots/{snapshot_id}/export.csv").text
    lines = sheet.lstrip("﻿").splitlines()
    assert lines[0] == "compte;isin;titre;quantite;prix_de_revient;cours;valeur"
    assert "CTO;XX0000000001;Acme;1,0;25,0;30,0;30,0" in lines

    # A later price change does not rewrite history.
    client.put("/api/prices/XX0000000001", json={"price": "99"})
    assert client.get(f"/api/snapshots/{snapshot_id}").json() == body
    assert client.get("/api/snapshots/999").status_code == 404


def test_only_this_machine_may_talk_to_the_api(client, sample_csv):
    foreign_host = client.get("/api/state", headers={"host": "evil.example"})
    assert foreign_host.status_code == 400

    foreign_site = client.post(
        "/api/import/csv",
        content=sample_csv.encode(),
        headers={**CSV, "origin": "https://evil.example"},
    )
    assert foreign_site.status_code == 403
    assert client.get("/api/state").json()["transactions"] == 0

    own_page = client.post(
        "/api/import/csv",
        content=sample_csv.encode(),
        headers={**CSV, "origin": "http://127.0.0.1:8765"},
    )
    assert own_page.status_code == 200


# -- Market data, with a source that answers from memory -------------------------


@pytest.fixture
def market_client(tmp_path, sample_csv):
    from cockpit.market.provider import Listing
    from tests.fakes import FakeProvider, series

    provider = FakeProvider()
    provider.listings["XX0000000001"] = [Listing("ACME.PA", "Acme SA", "PAR", "EQUITY")]
    provider.charts["ACME.PA"] = series(
        "ACME.PA", "EUR", "PAR", {"2025-06-27": "29", "2025-06-30": "30"}, previous="29"
    )
    client = TestClient(create_app(tmp_path / "market.db", provider=provider))
    client.post("/api/import/csv", content=sample_csv.encode(), headers=CSV)
    return client, provider


def test_market_endpoints(market_client):
    client, _ = market_client
    refreshed = client.post("/api/market/refresh").json()
    assert (refreshed["updated"], refreshed["refused"], refreshed["busy"]) == (1, False, False)

    acme = next(
        p for p in client.get("/api/report").json()["positions"] if p["isin"] == "XX0000000001"
    )
    assert (acme["value"], acme["quote"]["delay_minutes"], acme["spark"]) == (30.0, 15, [30.0])

    chart = client.get("/api/market/chart/XX0000000001?range=1j").json()
    assert (chart["symbol"], len(chart["points"])) == ("ACME.PA", 2)
    assert client.get("/api/market/chart/XX0000000001?range=nope").status_code == 400
    assert client.get("/api/market/chart/XX0000000003").status_code == 502  # no listing

    loaded = client.post("/api/market/history").json()
    assert loaded["updated"] == 1 and loaded["skipped"] == 2
    history = client.get("/api/portfolio/history").json()
    assert history["points"][-1]["date"] == "2025-06-30"
    assert set(history["unpriced"]) == {"Globex", "World Fund (Acc)"}

    listing = {i["isin"]: i for i in client.get("/api/market/instruments").json()}
    assert listing["XX0000000001"]["price_days"] == 2
    renamed = client.put("/api/market/instruments/XX0000000003", json={"symbol": "WRLD.DE"})
    assert renamed.json() == {"isin": "XX0000000003", "symbol": "WRLD.DE"}
    assert client.put("/api/market/instruments/UNKNOWN", json={"symbol": "X"}).status_code == 404

    proposed = client.get("/api/market/instruments/XX0000000001/candidates").json()
    assert (proposed["by"], proposed["candidates"][0]["symbol"]) == ("isin", "ACME.PA")
    assert proposed["candidates"][0]["price_eur"] == 30.0
    assert client.get("/api/market/instruments/UNKNOWN/candidates").status_code == 404


def test_refused_source_is_reported_not_hidden(market_client):
    from cockpit.market.provider import ProviderError

    client, provider = market_client
    provider.fail = ProviderError("refused", "Yahoo a refusé la requête (HTTP 429)")
    refreshed = client.post("/api/market/refresh").json()
    assert refreshed["refused"] is True and refreshed["updated"] == 0
    assert client.get("/api/market/chart/XX0000000001").status_code == 503
    assert client.get("/api/market/instruments/XX0000000001/candidates").status_code == 503
    # The dashboard still works, on prices typed in by hand.
    assert client.put("/api/prices/XX0000000001", json={"price": "31"}).status_code == 200
