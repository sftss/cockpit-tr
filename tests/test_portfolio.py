from decimal import Decimal as D

from cockpit import portfolio, store
from cockpit.importers import tr_csv


def lines_of(conn):
    return portfolio.build_lines(store.all_transactions(conn))


def test_average_cost_and_partial_sale(conn, sample_csv):
    tr_csv.import_csv(conn, sample_csv)
    acme = lines_of(conn)[("CTO", "XX0000000001")]
    # 2 shares bought for 50 €, one sold for 40 €: 25 € of cost released.
    assert acme.is_open
    assert (acme.shares, acme.cost, acme.average_cost) == (D("1.0"), D("25.00"), D("25"))
    assert acme.realized == D("15.00")
    assert (acme.fees, acme.manual_orders) == (D("3.00"), 3)
    assert acme.dividends == D("0.50")


def test_split_changes_quantity_not_cost_and_line_closes(conn, sample_csv):
    tr_csv.import_csv(conn, sample_csv)
    globex = lines_of(conn)[("CTO", "XX0000000002")]
    assert globex.is_closed and globex.shares == 0 and globex.cost == 0
    assert (globex.bought, globex.sold) == (D("20.00"), D("16.00"))
    assert (globex.gross_result, globex.net_result) == (D("-4.00"), D("-6.00"))
    assert globex.realized == globex.gross_result
    assert globex.holding_days == 91


def test_free_executions_are_not_manual_orders_and_migration_is_neutral(conn, sample_csv):
    tr_csv.import_csv(conn, sample_csv)
    fund = lines_of(conn)[("CTO", "XX0000000003")]
    assert (fund.shares, fund.cost) == (D("0.9"), D("20.00"))
    assert (fund.buys, fund.manual_orders, fund.fees) == (2, 0, 0)


def test_same_instrument_in_two_accounts_is_two_lines(conn, sample_csv):
    tr_csv.import_csv(conn, sample_csv)
    pea = lines_of(conn)[("PEA", "XX0000000002")]
    assert pea.is_open and pea.shares == D("2.0")
    assert (pea.fees, pea.taxes) == (D("0.10"), D("0.08"))


def test_report_totals(conn, sample_csv):
    tr_csv.import_csv(conn, sample_csv)
    data = store.current_report(conn)

    assert data["flows"]["deposits"] == 150.70
    assert data["flows"]["card_spending"] == 5.00
    assert data["flows"]["capital_brought_in"] == 145.70
    assert data["fees"] == {
        "orders": {"CTO": 5.00, "PEA": 0.10},
        "deposits": 0.70,
        "other": 0.0,
        "total": 5.80,
        "share_of_capital": 0.0398,
    }
    assert data["closed_summary"] == {
        "count": 1,
        "winners": 0,
        "bought": 20.0,
        "gross": -4.0,
        "fees": 2.0,
        "taxes": 0.0,
        "net": -6.0,
        "net_pct": -0.3,
    }
    assert data["manual_orders"] == 6
    quarters = {q["quarter"]: q["manual_orders"] for q in data["quarters"]}
    assert quarters == {"2025-T1": 3, "2025-T2": 3}

    cto, pea = data["accounts"]
    assert (cto["open_lines"], cto["closed_lines"]) == (2, 1)
    assert cto["net_invested"] == 34.0  # 90 paid - 56 received
    assert cto["open_cost"] == 45.0
    # 150 net deposits - 93 (buys+fees) + 54 (sells-fees) + 0.42 income - 5 card - 30 to PEA
    assert cto["cash_estimate"] == 76.42
    assert pea["cash_estimate"] == 9.82
    assert cto["value"] is None  # no price entered yet


def test_weights_and_valuation_follow_prices(conn, sample_csv):
    tr_csv.import_csv(conn, sample_csv)
    before = {
        p["isin"]: p for p in store.current_report(conn)["positions"] if p["account"] == "CTO"
    }
    assert before["XX0000000001"]["weight_basis"] == "cost"
    assert before["XX0000000001"]["weight"] == 0.5556  # 25 of 45 at cost

    store.set_price(conn, "XX0000000001", D("30"), "2025-06-30", "manuel")
    store.set_price(conn, "XX0000000003", D("30"), "2025-06-30", "manuel")
    data = store.current_report(conn)
    acme = next(p for p in data["positions"] if p["isin"] == "XX0000000001")
    assert (acme["value"], acme["latent"], acme["latent_pct"]) == (30.0, 5.0, 0.2)
    assert (acme["weight_basis"], acme["weight"]) == ("value", 0.5263)  # 30 of 57
    cto = data["accounts"][0]
    assert (cto["value"], cto["latent"]) == (57.0, 12.0)
    assert cto["performance"] == 0.6765  # (57 - 34) / 34


def test_sale_without_holding_is_flagged(conn):
    from tests.conftest import ACME, to_csv, tx

    tr_csv.import_csv(
        conn,
        to_csv(
            [
                tx("2025-01-06", "SELL", **ACME, shares="-1.0", price="40", amount="40.00"),
            ]
        ),
    )
    assert store.current_report(conn)["anomalies"] == [
        "Acme (CTO) — 2025-01-06 : vente sans quantité détenue"
    ]
