"""Order tickets, on the invented history of the fixtures."""

from datetime import date
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from cockpit import compliance, roadmap, rules, store, tickets
from cockpit.api import create_app
from cockpit.assistant import prompt, tools
from cockpit.importers import tr_csv
from cockpit.market.provider import Listing, ProviderError
from cockpit.market.service import Market
from tests.conftest import to_csv, tx
from tests.fakes import FakeProvider, series

ACME, GLOBEX, FUND = "XX0000000001", "XX0000000002", "XX0000000003"
NEWCO = "FR0000000009"
CSV = {"content-type": "text/csv"}
TODAY = date(2025, 6, 10)


@pytest.fixture
def loaded(conn, sample_csv):
    """The sample history: one Acme share on the CTO, two Globex on the PEA, 0.9 fund."""
    tr_csv.import_csv(conn, sample_csv)
    store.set_price(conn, ACME, D("40"), "2025-06-09", "fake")
    return conn


def halal(conn, isin, day="2025-06-01", status="conforme"):
    compliance.record(conn, isin, status, day, None)


def new(conn, **data):
    return tickets.create(conn, {"isin": ACME, "account": "CTO", "side": "BUY", **data})


def seen(conn, ticket_id, today=TODAY):
    return tickets.get(conn, ticket_id, None, today)


def states(view):
    return {check["key"]: check["state"] for check in view["controls"]}


def bought(day, isin=ACME, name="Acme", shares="2.0", amount="-80.00", fee="-1.00", **cells):
    cells = {"asset_class": "STOCK", "price": "40", **cells}
    return tx(day, "BUY", symbol=isin, name=name, shares=shares, amount=amount, fee=fee, **cells)


# -- A draft ---------------------------------------------------------------------


def test_a_draft_takes_what_the_database_already_knows(loaded):
    view = seen(loaded, new(loaded, shares="2"))
    assert (view["name"], view["status"], view["proposed_by"]) == ("Acme", "brouillon", None)
    assert (view["price"], view["price_at"], view["amount"]) == (40.0, "2025-06-09", 80.0)
    assert (view["fee"], view["fee_share"], view["held"]) == (1.0, 0.0125, 1.0)
    assert view["instrument"] == "Action" and view["order_type"] == "marche"

    # An amount gives the quantity, rounded down; a limit order is counted at its limit.
    by_amount = seen(loaded, new(loaded, amount="100"))
    assert (by_amount["shares"], by_amount["amount"]) == (2.5, 100.0)
    limited = seen(loaded, new(loaded, shares="2", order_type="limite", limit_price="35"))
    assert (limited["unit"], limited["amount"]) == (35.0, 70.0)


def test_what_cannot_be_a_ticket_is_refused(loaded):
    for data, message in [
        ({"isin": ""}, "ISIN du titre est obligatoire"),
        ({"isin": "ACME"}, "12 caractères"),
        ({"side": "SHORT"}, "Sens inconnu"),
        ({"account": "LIVRET"}, "Compte inconnu"),
        ({"shares": "-1"}, "nombre positif"),
        ({"shares": "abc"}, "illisible"),
        ({"side": "SELL", "shares": "3"}, "Vente de 3 pour 1 détenus"),
        ({"side": "SELL", "isin": NEWCO}, "pas détenu"),
        ({"isin": NEWCO, "amount": "100"}, "Sans cours"),
        ({"roadmap_item_id": 99}, "introuvable"),
    ]:
        with pytest.raises(tickets.TicketError, match=message):
            new(loaded, **data)
    loaded.execute("UPDATE instruments SET asset_class = 'CRYPTO' WHERE isin = ?", (GLOBEX,))
    with pytest.raises(tickets.TicketError, match="actions et des ETF"):
        new(loaded, isin=GLOBEX)
    assert tickets.listing(loaded, None, TODAY)["tickets"] == []


# -- The one control that stops ----------------------------------------------------


def test_a_purchase_stops_without_an_up_to_date_halal_status(loaded):
    ticket = new(loaded, shares="2", reason="Un motif n'y change rien.")
    view = seen(loaded, ticket)
    assert (
        states(view)["halalitude"] == "bloquant" and "non relevé" in view["controls"][0]["detail"]
    )
    assert (view["blocked"], view["can_be_ready"]) == (True, False)
    with pytest.raises(tickets.TicketError, match="aucun motif ne le débloque"):
        tickets.set_status(loaded, ticket, "pret", None, TODAY)

    # Doubtful and haram stop it alike; so does a reading older than ninety days.
    for status in ("douteux", "non_conforme"):
        halal(loaded, ACME, "2025-06-02", status)
        assert states(seen(loaded, ticket))["halalitude"] == "bloquant"
    halal(loaded, ACME, "2025-06-03")
    assert states(seen(loaded, ticket, date(2025, 9, 2)))["halalitude"] == "bloquant"
    assert "plus de 90 jours" in seen(loaded, ticket, date(2025, 9, 2))["controls"][0]["detail"]

    # Read again and found halal: the same ticket goes through.
    assert states(seen(loaded, ticket))["halalitude"] == "ok"
    tickets.set_status(loaded, ticket, "pret", None, TODAY)
    ready = seen(loaded, ticket)
    assert ready["status"] == "pret" and ready["ready_at"]


def test_a_sale_is_never_stopped(loaded):
    halal(loaded, ACME, status="non_conforme")
    ticket = new(loaded, side="SELL", shares="1")
    view = seen(loaded, ticket)
    assert states(view)["halalitude"] == "info" and "haram" in view["controls"][0]["detail"]
    assert "feuille_de_route" not in states(view) and "especes" not in states(view)
    tickets.set_status(loaded, ticket, "pret", None, TODAY)
    assert seen(loaded, ticket)["status"] == "pret"


def test_a_ready_purchase_goes_back_to_draft_when_its_status_expires(loaded):
    halal(loaded, ACME, "2025-06-01")
    ticket = new(loaded, shares="2")
    tickets.set_status(loaded, ticket, "pret", None, TODAY)
    assert tickets.summary(loaded, TODAY)["pret"] == 1
    later = date(2025, 9, 15)
    assert tickets.summary(loaded, later) == {
        "brouillon": 1,
        "pret": 0,
        "execute": 0,
        "abandonne": 0,
    }
    assert seen(loaded, ticket, later)["blocked"] is True


# -- The rules ask for a reason, and stop nothing ----------------------------------


def test_exceeding_a_rule_asks_for_a_reason(loaded):
    halal(loaded, ACME)
    rules.set_rule(loaded, "ordres_manuels_trimestre", "3", "2025-01-01")
    rules.set_rule(loaded, "achat_minimum", "100", "2025-01-01")
    rules.set_rule(loaded, "frais_trimestre", "10", "2025-01-01")
    ticket = new(loaded, shares="2")  # 80 €: the fourth manual order of the quarter
    view = seen(loaded, ticket)
    found = states(view)
    assert found["ordres_manuels_trimestre"] == "motif" and found["achat_minimum"] == "motif"
    assert found["frais_trimestre"] == "ok"
    details = {check["key"]: check["detail"] for check in view["controls"]}
    assert details["ordres_manuels_trimestre"] == "4e ordre manuel du trimestre, pour 3 prévus."
    assert details["achat_minimum"] == "Achat de 80,00 €, sous le minimum de 100,00 €."
    assert details["frais_trimestre"].startswith("Frais d'ordre du trimestre portés à 3,10 €")
    assert details["frais"] == "1,00 €, soit 1,2 % du montant."
    assert (view["blocked"], view["needs_reason"], view["can_be_ready"]) == (False, True, False)

    with pytest.raises(tickets.TicketError, match="motif écrit"):
        tickets.set_status(loaded, ticket, "pret", None, TODAY)
    tickets.update(loaded, ticket, {"reason": "Renfort décidé à la revue."})
    tickets.set_status(loaded, ticket, "pret", None, TODAY)
    assert seen(loaded, ticket)["status"] == "pret"

    # A ticket that exceeds nothing asks for nothing.
    quiet = new(loaded, shares="3")
    rules.set_rule(loaded, "ordres_manuels_trimestre", "9", "2025-06-01")
    view = seen(loaded, quiet)
    assert (view["needs_reason"], view["can_be_ready"]) == (False, True)
    assert "motif" not in states(view).values()


def test_ready_tickets_count_as_orders_already_passed(loaded):
    halal(loaded, ACME)
    rules.set_rule(loaded, "ordres_manuels_trimestre", "4", "2025-01-01")
    first, second = new(loaded, shares="2"), new(loaded, shares="2")
    # Two drafts: each one would be the fourth order of the quarter.
    assert states(seen(loaded, first))["ordres_manuels_trimestre"] == "ok"
    assert states(seen(loaded, second))["ordres_manuels_trimestre"] == "ok"
    tickets.set_status(loaded, first, "pret", None, TODAY)
    # The first is ready: the second would be the fifth.
    assert states(seen(loaded, first))["ordres_manuels_trimestre"] == "ok"
    view = seen(loaded, second)
    assert states(view)["ordres_manuels_trimestre"] == "motif"
    assert "5e ordre manuel" in next(
        c["detail"] for c in view["controls"] if c["key"] == "ordres_manuels_trimestre"
    )


def test_new_line_weight_sales_and_closed_lines(loaded):
    halal(loaded, NEWCO)
    rules.set_rule(loaded, "nouvelle_ligne_valeur_minimum", "5000", "2025-01-01")
    rules.set_rule(loaded, "poids_maximum", "40", "2025-01-01")
    fresh = seen(loaded, new(loaded, isin=NEWCO, name="Newco", shares="1", price="50"))
    found = states(fresh)
    assert found["nouvelle_ligne_valeur_minimum"] == "motif"
    assert found["instrument"] == "avertissement"  # never held, not on the public list
    assert found["poids_maximum"] == "motif"  # 50 € on a 115 € portfolio

    rules.set_rule(loaded, "ventes_trimestre", "0", "2025-01-01")
    rules.set_rule(loaded, "lignes_soldees_trimestre", "1", "2025-01-01")
    sale = seen(loaded, new(loaded, side="SELL", shares="1"))
    found = states(sale)
    assert found["ventes_trimestre"] == "motif" and found["lignes_soldees_trimestre"] == "motif"
    assert "nouvelle_ligne_valeur_minimum" not in found and "poids_maximum" not in found


def test_warnings_ask_for_nothing(loaded):
    halal(loaded, ACME)
    halal(loaded, "US0000000001")
    # Hors feuille de route, and more to pay than the estimated cash: two warnings.
    view = seen(loaded, new(loaded, shares="10"))
    found = states(view)
    assert found["feuille_de_route"] == "avertissement" and found["especes"] == "avertissement"
    assert (view["needs_reason"], view["can_be_ready"]) == (False, True)

    # A target of the roadmap: linked on its own, and "prévu" clears the warning.
    target = roadmap.create(loaded, {"name": "Acme", "isin": ACME, "status": "idee"})
    linked = new(loaded, shares="1")
    view = seen(loaded, linked)
    assert view["target"]["id"] == target and states(view)["feuille_de_route"] == "avertissement"
    roadmap.update(loaded, target, {"name": "Acme", "isin": ACME, "status": "prevu"})
    assert states(seen(loaded, linked))["feuille_de_route"] == "ok"

    # PEA: an ISIN outside the EU and the EEA is flagged, an ETF is left to the broker.
    foreign = new(loaded, isin="US0000000001", name="Usco", account="PEA", shares="1", price="9")
    assert states(seen(loaded, foreign))["pea"] == "avertissement"
    assert "pea" not in states(view)
    loaded.execute("UPDATE instruments SET isin = 'IE0000000003' WHERE isin = ?", (FUND,))
    halal(loaded, "IE0000000003")
    fund = new(loaded, isin="IE0000000003", account="PEA", shares="1", price="25")
    assert states(seen(loaded, fund))["pea"] == "info"


def test_tickets_that_are_ready_weigh_on_the_next_ones(loaded):
    halal(loaded, ACME)
    # Weight, at cost since one line has no price: Acme is 25 € of 65 €. Two
    # purchases of 20 € each: the second is measured with the first one passed.
    rules.set_rule(loaded, "poids_maximum", "55", "2025-01-01")
    first, second = new(loaded, shares="0.5"), new(loaded, shares="0.5")
    assert states(seen(loaded, first))["poids_maximum"] == "ok"  # 45 of 85: 52,9 %
    assert states(seen(loaded, second))["poids_maximum"] == "ok"  # two drafts: the same
    tickets.set_status(loaded, first, "pret", None, TODAY)
    assert states(seen(loaded, second))["poids_maximum"] == "motif"  # 65 of 105: 61,9 %

    # Quantity: one share held, and a sale of it already ready.
    sale = new(loaded, side="SELL", shares="1")
    tickets.set_status(loaded, sale, "pret", None, TODAY)
    again = new(loaded, side="SELL", shares="1")
    view = seen(loaded, again)
    assert states(view)["quantite"] == "erreur" and view["can_be_ready"] is False
    with pytest.raises(tickets.TicketError, match="ventes déjà prêtes"):
        tickets.set_status(loaded, again, "pret", None, TODAY)


def test_an_amount_at_the_minimum_is_not_under_it(loaded):
    halal(loaded, ACME)
    rules.set_rule(loaded, "achat_minimum", "100", "2025-01-01")
    store.set_price(loaded, ACME, D("41.50"), "2025-06-10", "fake")
    view = seen(loaded, new(loaded, amount="100"))  # 2,409638 shares: 99,99998 € before rounding
    assert (view["shares"], view["amount"]) == (2.409638, 100.0)
    assert states(view)["achat_minimum"] == "ok"


def test_a_draft_keeps_its_title_and_what_was_not_sent(loaded):
    halal(loaded, ACME)
    target = roadmap.create(loaded, {"name": "Acme", "isin": ACME, "status": "prevu"})
    ticket = new(loaded, side="SELL", shares="1", fee="2")
    with pytest.raises(tickets.TicketError, match="ne se change pas"):
        tickets.update(loaded, ticket, {"isin": GLOBEX})
    tickets.update(loaded, ticket, {"side": None, "account": "", "fee": None, "order_type": None})
    view = seen(loaded, ticket)
    assert (view["side"], view["account"], view["fee"]) == ("SELL", "CTO", 2.0)

    # A link removed by hand stays removed; a target pointed elsewhere drops its link.
    linked = new(loaded, shares="1")
    assert seen(loaded, linked)["target"]["id"] == target
    tickets.update(loaded, linked, {"roadmap_item_id": None})
    tickets.update(loaded, linked, {"shares": "2"})
    assert seen(loaded, linked)["target"] is None
    tickets.update(loaded, linked, {"roadmap_item_id": target})
    roadmap.update(loaded, target, {"name": "Globex", "isin": GLOBEX, "status": "prevu"})
    assert states(seen(loaded, linked))["feuille_de_route"] == "avertissement"
    tickets.update(loaded, linked, {"shares": "3"})
    assert seen(loaded, linked)["target"] is None
    with pytest.raises(tickets.TicketError, match="autre titre"):
        tickets.update(loaded, linked, {"roadmap_item_id": target})

    for wrong in ("inf", "nan", "1e30", "-1"):
        with pytest.raises(tickets.TicketError):
            tickets.update(loaded, linked, {"price": wrong})


def test_an_unfinished_draft_waits(loaded):
    halal(loaded, NEWCO)
    ticket = new(loaded, isin=NEWCO, name="Newco")
    view = seen(loaded, ticket)
    assert states(view)["saisie"] == "attente" and view["can_be_ready"] is False
    with pytest.raises(tickets.TicketError, match="Saisir la quantité"):
        tickets.set_status(loaded, ticket, "pret", None, TODAY)


# -- States ------------------------------------------------------------------------


def test_states_and_what_each_allows(loaded):
    halal(loaded, ACME)
    ticket = new(loaded, shares="2")
    with pytest.raises(tickets.TicketError, match="pas possible"):
        tickets.set_status(loaded, ticket, "execute", None, TODAY)
    tickets.set_status(loaded, ticket, "pret", None, TODAY)
    with pytest.raises(tickets.TicketError, match="Seul un brouillon"):
        tickets.update(loaded, ticket, {"shares": "3"})
    tickets.set_status(loaded, ticket, "brouillon", None, TODAY)
    tickets.update(loaded, ticket, {"shares": "3", "price": "41"})
    view = seen(loaded, ticket)
    assert (view["shares"], view["price"], view["amount"]) == (3.0, 41.0, 123.0)
    assert view["price_at"] != "2025-06-09"  # typed in by hand: dated now

    tickets.set_status(loaded, ticket, "abandonne", None, TODAY)
    assert seen(loaded, ticket)["closed_at"] and seen(loaded, ticket)["controls"] == []
    tickets.set_status(loaded, ticket, "brouillon", None, TODAY)
    tickets.delete(loaded, ticket)
    with pytest.raises(KeyError):
        tickets.delete(loaded, ticket)


def test_the_indicative_price_is_asked_in_euros(loaded):
    fake = FakeProvider()
    fake.listings[NEWCO] = [Listing("NEW.PA", "Newco", "PAR", "EQUITY")]
    fake.listings[GLOBEX] = [Listing("GLBX", "Globex Inc.", "NMS", "EQUITY")]
    fake.charts["NEW.PA"] = series("NEW.PA", "EUR", "PAR", {"2025-06-10": "51.5"})
    fake.charts["GLBX"] = series("GLBX", "USD", "NMS", {"2025-06-10": "12"})
    fake.charts["EURUSD=X"] = series("EURUSD=X", "USD", "CCY", {"2025-06-10": "1.20"})
    market = Market(fake)

    # A title never held is looked up by its ISIN; a held one through its stored symbol.
    fresh = new(loaded, isin=NEWCO, name="Newco", shares="2")
    assert seen(loaded, fresh)["price"] is None
    tickets.refresh_price(loaded, market, fresh)
    view = seen(loaded, fresh)
    assert (view["price"], view["amount"]) == (51.5, 103.0) and view["price_at"]
    abroad = new(loaded, isin=GLOBEX, account="PEA", shares="1")
    tickets.refresh_price(loaded, market, abroad)
    assert seen(loaded, abroad)["price"] == 10.0  # 12 dollars at 1.20

    fake.fail = ProviderError("refused", "source indisponible")
    unknown = new(loaded, isin="FR0000000017", name="Autre", shares="1", price="5")
    with pytest.raises(ProviderError):
        tickets.refresh_price(loaded, market, unknown)
    assert seen(loaded, unknown)["price"] == 5.0  # the price typed in stays


# -- Matching ----------------------------------------------------------------------


def ready(conn, at="2025-06-10T08:00:00+00:00", **data):
    """A ticket created and made ready on the morning of 10 June 2025."""
    ticket = new(conn, **data)
    tickets.set_status(conn, ticket, "pret", None, TODAY)
    conn.execute(
        "UPDATE tickets SET created_at = '2025-06-10T07:30:00+00:00', ready_at = ? WHERE id = ?",
        (at, ticket),
    )
    conn.commit()
    return ticket


def test_an_imported_order_is_matched_with_its_ticket(loaded):
    halal(loaded, ACME)
    rules.set_rule(loaded, "achat_minimum", "100", "2025-01-01")
    ticket = ready(loaded, shares="2", reason="Renfort décidé à la revue.")
    assert tickets.reconcile(loaded) == {"matched": [], "ambiguous": []}

    order = bought("2025-06-11", shares="2.0", amount="-82.00", price="41")
    tr_csv.import_csv(loaded, to_csv([order]))
    assert tickets.reconcile(loaded) == {"matched": [ticket], "ambiguous": []}
    view = seen(loaded, ticket)
    assert view["status"] == "execute" and view["closed_at"]
    assert view["executed"] == {
        "transaction_id": order["transaction_id"],
        "date": "2025-06-11",
        "shares": 2.0,
        "price": 41.0,
        "amount": 82.0,
        "fee": 1.0,
    }
    assert view["amount"] == 80.0  # what was planned stays beside what was done
    assert states(view)["achat_minimum"] == "motif"  # the controls as they stood when ready

    # The reason follows the transaction: the rules page does not ask for it again.
    state = store.rules_state(loaded, date(2025, 6, 12))
    assert [(d["transaction_id"], d["reason"]) for d in state["deviations"]][0] == (
        order["transaction_id"],
        "Renfort décidé à la revue.",
    )
    with pytest.raises(tickets.TicketError, match="se garde"):
        tickets.delete(loaded, ticket)


def test_what_is_not_surely_the_order_is_left_to_the_user(loaded):
    halal(loaded, ACME)
    ticket = ready(loaded, shares="2")
    rows = [
        bought("2025-06-09"),  # before the ticket existed
        bought("2025-06-10", time="07:45:00"),  # the same day, but before it was ready
        bought("2025-06-11", fee="", amount="-80.00"),  # a free savings-plan execution
        bought("2025-06-11", account="PEA"),  # another account
        bought("2025-06-11", isin=GLOBEX, name="Globex"),  # another title
        bought("2025-06-12", shares="5.0", amount="-200.00"),  # a quantity far from the plan
    ]
    tr_csv.import_csv(loaded, to_csv(rows))
    assert tickets.reconcile(loaded) == {"matched": [], "ambiguous": [ticket]}
    view = seen(loaded, ticket)
    assert view["status"] == "pret"
    # None is sure, three are possible: the user can say which, whatever the doubt.
    assert [c["transaction_id"] for c in view["candidates"]] == [
        rows[1]["transaction_id"],
        rows[2]["transaction_id"],
        rows[5]["transaction_id"],
    ]

    # Two orders that both fit: the application asks which.
    twins = [bought("2025-06-13"), bought("2025-06-14")]
    tr_csv.import_csv(loaded, to_csv(twins))
    assert tickets.reconcile(loaded)["ambiguous"] == [ticket]
    with pytest.raises(tickets.TicketError, match="ne correspond pas"):
        tickets.match(loaded, ticket, rows[0]["transaction_id"])
    tickets.match(loaded, ticket, twins[1]["transaction_id"], TODAY)
    assert seen(loaded, ticket)["executed"]["date"] == "2025-06-14"

    # A second ticket cannot take the same transaction.
    other = ready(loaded, at="2025-06-10T09:00:00+00:00", shares="2")
    assert twins[1]["transaction_id"] not in [
        c["transaction_id"] for c in seen(loaded, other)["candidates"]
    ]
    # Undone: the user said it was not that order, so it is not matched with it
    # again. What is left is one sure transaction for each ticket, found in turn.
    tickets.match(loaded, ticket, None, TODAY)
    assert seen(loaded, ticket)["status"] == "pret"
    with pytest.raises(tickets.TicketError, match="rapproché d'aucune"):
        tickets.match(loaded, ticket, None, TODAY)
    assert tickets.reconcile(loaded)["matched"] == [ticket, other]
    assert seen(loaded, ticket)["executed"]["date"] == "2025-06-13"
    assert seen(loaded, other)["executed"]["date"] == "2025-06-14"


def test_a_match_is_only_automatic_when_nothing_argues_against_it(loaded):
    halal(loaded, ACME, "2025-06-01")
    order = bought("2025-06-20", shares="2.0", amount="-80.00")

    def outcome(ticket):
        result = tickets.reconcile(loaded)
        loaded.execute("DELETE FROM tickets WHERE id = ?", (ticket,))
        loaded.commit()
        return result

    tr_csv.import_csv(loaded, to_csv([order]))
    # A limit that the execution did not respect: 40 € paid for a limit at 35.
    limited = ready(loaded, shares="2", order_type="limite", limit_price="35")
    assert outcome(limited) == {"matched": [], "ambiguous": [limited]}
    # A ticket said to be free: never matched on its own, a savings plan looks the same.
    free = ready(loaded, shares="2", fee="0")
    assert states(seen(loaded, free))["ordre_sans_frais"] == "avertissement"
    assert outcome(free) == {"matched": [], "ambiguous": [free]}
    # Ready for more than thirty days before the order: another decision, most likely.
    old = ready(loaded, at="2025-05-12T08:00:00+00:00", shares="2")
    loaded.execute(
        "UPDATE tickets SET created_at = '2025-05-12T07:00:00+00:00' WHERE id = ?", (old,)
    )
    assert outcome(old) == {"matched": [], "ambiguous": [old]}
    # The status was read as haram before the day of the order: not a ticket's order.
    haram = ready(loaded, shares="2")
    halal(loaded, ACME, "2025-06-15", "non_conforme")
    assert outcome(haram) == {"matched": [], "ambiguous": [haram]}
    halal(loaded, ACME, "2025-06-16")
    # Nothing against it: matched.
    plain = ready(loaded, shares="2")
    assert tickets.reconcile(loaded) == {"matched": [plain], "ambiguous": []}


def test_an_order_placed_while_ready_is_matched_even_if_the_status_expired_since(loaded):
    halal(loaded, ACME, "2025-03-15")  # valid until 13 June
    ticket = ready(loaded, shares="2", reason="Renfort.")
    order = bought("2025-06-11")
    # Seen again on 20 June before any import: the reading has expired, back to draft.
    assert tickets.summary(loaded, date(2025, 6, 20))["brouillon"] == 1
    tr_csv.import_csv(loaded, to_csv([order]))
    assert tickets.reconcile(loaded) == {"matched": [], "ambiguous": []}
    # Read again, ready again: the order of 11 June can still be pointed at.
    halal(loaded, ACME, "2025-06-20")
    tickets.set_status(loaded, ticket, "pret", None, date(2025, 6, 20))
    view = seen(loaded, ticket, date(2025, 6, 20))
    assert [c["transaction_id"] for c in view["candidates"]] == [order["transaction_id"]]
    tickets.match(loaded, ticket, order["transaction_id"], date(2025, 6, 20))
    assert seen(loaded, ticket, date(2025, 6, 20))["status"] == "execute"


def test_undoing_a_match_checks_the_status_again_and_takes_the_reason_back(loaded):
    halal(loaded, ACME)
    rules.set_rule(loaded, "achat_minimum", "100", "2025-01-01")
    ticket = ready(loaded, shares="2", reason="Renfort décidé à la revue.")
    order = bought("2025-06-11")
    tr_csv.import_csv(loaded, to_csv([order]))
    assert tickets.reconcile(loaded)["matched"] == [ticket]
    note = "SELECT reason FROM deviation_notes WHERE transaction_id = ?"
    assert loaded.execute(note, (order["transaction_id"],)).fetchone()[0].startswith("Renfort")

    halal(loaded, ACME, "2025-06-12", "non_conforme")
    tickets.match(loaded, ticket, None, date(2025, 6, 12))
    view = seen(loaded, ticket, date(2025, 6, 12))
    assert (view["status"], view["blocked"]) == ("brouillon", True)
    assert loaded.execute(note, (order["transaction_id"],)).fetchone() is None
    # A reason the user wrote on the transaction himself is not touched.
    halal(loaded, ACME, "2025-06-13")
    tickets.set_status(loaded, ticket, "pret", None, date(2025, 6, 13))
    rules.set_reason(loaded, order["transaction_id"], "Écrit à la main.")
    tickets.match(loaded, ticket, order["transaction_id"], date(2025, 6, 13))
    tickets.match(loaded, ticket, None, date(2025, 6, 13))
    assert loaded.execute(note, (order["transaction_id"],)).fetchone()[0] == "Écrit à la main."


# -- The assistant -----------------------------------------------------------------


def run(conn, name, **arguments):
    return tools.run(conn, name, arguments)


def test_the_assistant_drafts_and_nothing_more(loaded):
    import json

    halal(loaded, ACME)
    output, failed = run(
        loaded, "preparer_ticket", isin=ACME, compte="CTO", sens="achat", quantite=2
    )
    assert failed is False
    drafted = json.loads(output)["ticket"]
    assert (drafted["etat"], drafted["propose_par"], drafted["montant"]) == (
        "brouillon",
        "assistant",
        80.0,
    )
    assert {c["controle"] for c in drafted["controles"]} >= {"Halalitude", "Feuille de route"}
    assert "Rien n'a été envoyé" in output
    view = tickets.listing(loaded, None, TODAY)["tickets"][0]
    assert (view["status"], view["proposed_by"]) == ("brouillon", "assistant")

    # What it is told when the purchase is stopped, and what it cannot ask for.
    output, failed = run(
        loaded, "preparer_ticket", isin=GLOBEX, compte="PEA", sens="achat", quantite=1
    )
    assert failed is False and json.loads(output)["ticket"]["arrete"] is True
    # Without a price, an amount cannot become a quantity: said, not guessed.
    assert run(loaded, "preparer_ticket", isin=GLOBEX, compte="PEA", sens="achat", montant=50)[1]
    assert run(loaded, "preparer_ticket", isin=ACME, compte="CTO", sens="vente", quantite=9)[1]
    assert run(loaded, "preparer_ticket", isin=ACME, compte="CTO", sens="short")[1]

    listed = json.loads(run(loaded, "lire_tickets")[0])
    assert [t["etat"] for t in listed["tickets"]] == ["brouillon", "brouillon"]

    # No tool reaches beyond the draft: no state, no reason, no execution.
    schema = next(t for t in tools.TOOLS if t["name"] == "preparer_ticket")["input_schema"]
    assert set(schema["properties"]) == {
        "isin",
        "compte",
        "sens",
        "quantite",
        "montant",
        "cours_limite",
    }
    writing = [
        t["name"] for t in tools.TOOLS if "ticket" in t["name"] and t["name"] != "lire_tickets"
    ]
    assert writing == ["preparer_ticket"]
    told = prompt.BASE
    assert "explicitement" in told and "ni le passer à « prêt »" in told


# -- API -----------------------------------------------------------------------------


def test_tickets_over_the_api(tmp_path, sample_csv):
    client = TestClient(create_app(tmp_path / "tickets.db"))
    assert client.post("/api/import/csv", content=sample_csv.encode(), headers=CSV).json()[
        "tickets"
    ] == {"matched": [], "ambiguous": []}
    today = date.today().isoformat()

    assert client.post("/api/tickets", json={"isin": "nope"}).status_code == 400
    created = client.post(
        "/api/tickets", json={"isin": ACME, "account": "CTO", "side": "BUY", "shares": 2}
    )
    assert created.status_code == 201
    ticket = created.json()
    assert ticket["blocked"] is True and ticket["price"] is None  # no price in this database
    number = ticket["id"]
    assert client.put(f"/api/tickets/{number}", json={"price": "40"}).json()["amount"] == 80.0
    assert client.put("/api/tickets/99", json={"price": "40"}).status_code == 404

    refused = client.post(f"/api/tickets/{number}/status", json={"status": "pret"})
    assert refused.status_code == 400 and "Halalitude" in refused.json()["detail"]
    client.post("/api/compliance", json={"isin": ACME, "status": "conforme", "checked_on": today})
    ready = client.post(f"/api/tickets/{number}/status", json={"status": "pret"}).json()
    assert ready["status"] == "pret" and ready["candidates"] == []
    assert client.get("/api/tickets/summary").json()["pret"] == 1

    # The order shows up in the next export: the import itself matches it.
    order = bought(today, time="23:59:59")
    report = client.post("/api/import/csv", content=to_csv([order]).encode(), headers=CSV).json()
    assert report["tickets"] == {"matched": [number], "ambiguous": []}
    listed = client.get("/api/tickets").json()
    assert listed["tickets"][0]["executed"]["transaction_id"] == order["transaction_id"]
    assert listed["statuses"]["execute"] == "Exécuté" and listed["default_fee"] == 1.0

    assert client.delete(f"/api/tickets/{number}").status_code == 400
    undone = client.post(f"/api/tickets/{number}/match", json={"transaction_id": None}).json()
    assert undone["status"] == "pret"
    # Said not to be this order: not matched again on its own, still there to point at.
    assert client.post("/api/tickets/reconcile").json() == {"matched": [], "ambiguous": [number]}
    again = client.post(
        f"/api/tickets/{number}/match", json={"transaction_id": order["transaction_id"]}
    )
    assert again.json()["status"] == "execute"

    # What the request cannot set: a state, an author, a match.
    forged = client.post(
        "/api/tickets",
        json={
            "isin": ACME,
            "account": "CTO",
            "side": "BUY",
            "shares": 1,
            "status": "pret",
            "proposed_by": "moi",
            "transaction_id": "tx-0001",
        },
    ).json()
    assert (forged["status"], forged["proposed_by"], forged["executed"]) == (
        "brouillon",
        None,
        None,
    )
    for wrong in ("Infinity", "NaN", "1e30"):
        assert client.put(f"/api/tickets/{forged['id']}", json={"shares": wrong}).status_code == 400
    assert client.get("/api/tickets").status_code == 200

    # Nothing in these routes reaches a broker: no route name says "order" or "send".
    paths = [route.path for route in client.app.routes if "ticket" in route.path]
    assert paths and not [p for p in paths if "send" in p or "order" in p or "envoi" in p]
