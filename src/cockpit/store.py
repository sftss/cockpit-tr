"""Reads and writes around the calculations: transactions, prices, snapshots."""

from __future__ import annotations

import csv
import io
import json
import sqlite3
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from . import allocation, bilan, compliance, performance, portfolio, valuation, veille
from .money import ZERO, dec, money, ratio


def all_transactions(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM transactions").fetchall()


def latest_prices(conn: sqlite3.Connection) -> dict[str, dict]:
    rows = conn.execute(
        "SELECT p.isin, p.date, p.price, p.source FROM prices p "
        "JOIN (SELECT isin, MAX(date) AS date FROM prices GROUP BY isin) last "
        "ON last.isin = p.isin AND last.date = p.date"
    ).fetchall()
    return {row["isin"]: dict(row) for row in rows}


def set_price(conn: sqlite3.Connection, isin: str, price: Decimal, day: str, source: str) -> None:
    if price <= 0:
        raise ValueError("Le cours doit être positif.")
    conn.execute(
        "INSERT INTO prices (isin, date, price, source) VALUES (?, ?, ?, ?) "
        "ON CONFLICT (isin, date) DO UPDATE SET price = excluded.price, source = excluded.source",
        (isin, day, str(price), source),
    )
    conn.commit()


def quotes(conn: sqlite3.Connection) -> dict[str, dict]:
    """Latest quote of each instrument, as received from the market-data source."""
    result = {}
    for row in conn.execute("SELECT * FROM quotes"):
        price, previous = dec(row["price"]), row["previous_close"]
        change = None
        if previous and dec(previous) > 0:
            change = float((price / dec(previous) - 1).quantize(Decimal("0.0001")))
        result[row["isin"]] = {
            "price": float(price),
            "currency": row["currency"],
            "price_eur": float(dec(row["price_eur"])),
            "change": change,
            "market_time": row["market_time"],
            "exchange": row["exchange"],
            "delay_minutes": row["delay_minutes"],
            "fetched_at": row["fetched_at"],
        }
    return result


def recent_prices(conn: sqlite3.Connection, isin: str, days: int = 30) -> list[float]:
    """Last daily prices in euros, oldest first: the data of a sparkline."""
    rows = conn.execute(
        "SELECT price FROM prices WHERE isin = ? ORDER BY date DESC LIMIT ?", (isin, days)
    ).fetchall()
    return [float(dec(row["price"])) for row in reversed(rows)]


def price_history(conn: sqlite3.Connection) -> dict[str, list[tuple[str, Decimal]]]:
    history: dict[str, list[tuple[str, Decimal]]] = {}
    for row in conn.execute("SELECT isin, date, price FROM prices ORDER BY isin, date"):
        history.setdefault(row["isin"], []).append((row["date"], dec(row["price"])))
    return history


def split_history(conn: sqlite3.Connection) -> dict[str, list[tuple[str, Decimal]]]:
    splits: dict[str, list[tuple[str, Decimal]]] = {}
    for row in conn.execute("SELECT isin, date, ratio FROM splits ORDER BY isin, date"):
        splits.setdefault(row["isin"], []).append((row["date"], dec(row["ratio"])))
    return splits


def value_history(conn: sqlite3.Connection) -> dict:
    data = valuation.history(
        all_transactions(conn),
        price_history(conn),
        date.today().isoformat(),
        split_history(conn),
    )
    names = dict(conn.execute("SELECT isin, name FROM instruments").fetchall())
    data["unpriced"] = [names.get(isin, isin) for isin in data["unpriced"]]
    return data


def current_report(conn: sqlite3.Connection) -> dict:
    data = portfolio.report(all_transactions(conn), latest_prices(conn))
    last = conn.execute("SELECT MAX(imported_at) FROM transactions").fetchone()[0]
    data["last_import"] = last
    live = quotes(conn)
    statuses = compliance.latest(conn)
    # Share of each line in the whole broker portfolio, every account together:
    # on market value once every line has a price, on cost until then.
    positions = data["positions"]
    basis = "value" if positions and all(p["value"] is not None for p in positions) else "cost"
    total = sum((Decimal(str(p[basis])) for p in positions), ZERO)
    for position in positions:
        position["quote"] = live.get(position["isin"])
        position["spark"] = recent_prices(conn, position["isin"])
        position["halalitude"] = compliance.view(statuses.get(position["isin"]))
        position["weight_total"] = ratio(Decimal(str(position[basis])), total) if total else None
    data["total"] = {"basis": basis, "amount": money(total), "lines": len(positions)}
    return data


def universe(fiches: Path | None) -> dict[str, dict]:
    """The public list of companies by ISIN; empty when the file is not there."""
    if fiches is None:
        return {}
    try:
        listing = json.loads((fiches / "univers.json").read_text(encoding="utf-8"))
        return {str(entry["isin"]): entry for entry in listing["titres"] if entry.get("isin")}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def allocation_view(conn: sqlite3.Connection, fiches: Path | None) -> dict:
    """Spread of the open lines, on the same basis as their weights."""
    report = current_report(conn)
    currencies = dict(conn.execute("SELECT isin, quote_currency FROM instruments").fetchall())
    return allocation.breakdown(
        report["positions"], report["total"]["basis"], currencies, universe(fiches)
    )


# Benchmarks anyone can pick, beside the funds of the portfolio itself. All three
# are quoted in euros; the two funds reinvest their dividends, the index ignores them.
INDICES = {
    "msci-world": ("EUNL.DE", "MSCI World (ETF iShares Core, dividendes réinvestis)"),
    "sp500": ("SXR8.DE", "S&P 500 (ETF iShares Core, dividendes réinvestis)"),
    "cac40": ("^FCHI", "CAC 40 (indice, hors dividendes)"),
}


def benchmark_funds(conn: sqlite3.Connection, history: dict) -> list[dict]:
    """Funds of the database that can serve as a benchmark, from their stored
    prices: those held first, largest first, then those held in the past."""
    held: dict[str, Decimal] = {}
    for line in portfolio.build_lines(all_transactions(conn)).values():
        if line.is_open:
            held[line.isin] = held.get(line.isin, ZERO) + line.cost
    rows = conn.execute(
        "SELECT isin, name FROM instruments WHERE asset_class = 'FUND' ORDER BY name"
    ).fetchall()
    rows.sort(key=lambda row: -held.get(row["isin"], ZERO))  # stable: names within a tie
    return [
        {"id": row["isin"], "label": row["name"]}
        for row in rows
        if len(history.get(row["isin"], [])) > 1
    ]


def performance_view(conn: sqlite3.Connection, market, choice: str | None = None) -> dict:
    """Time-weighted performance of the portfolio beside one benchmark: a fund
    already in the database (its stored prices) or a public index (asked from
    the price source)."""
    points = value_history(conn)["points"]
    history = price_history(conn)
    funds = benchmark_funds(conn, history)
    benchmarks = funds + [{"id": key, "label": label} for key, (_, label) in INDICES.items()]
    chosen = next((b for b in benchmarks if b["id"] == choice), benchmarks[0])
    prices: list[tuple[str, Decimal]] = []
    problem = None
    if points:
        if chosen["id"] in INDICES:
            from .market.provider import ProviderError  # local import: store stays offline

            try:
                prices = market.closes_eur(INDICES[chosen["id"]][0], points[0]["date"])
            except ProviderError as exc:
                problem = str(exc)
        else:
            prices = history.get(chosen["id"], [])
    return {
        "benchmarks": benchmarks,
        "benchmark": chosen,
        "points": performance.series(points, prices),
        "priced": any(point["at_cost"] < point["value"] for point in points),
        "error": problem,
    }


def rules_state(conn: sqlite3.Connection, today: date | None = None) -> dict:
    """Counters against the rules for the quarter of `today` (by default, now)."""
    from . import rules  # local import: rules reads the portfolio through this module

    report = current_report(conn)
    history = value_history(conn)
    reasons = dict(conn.execute("SELECT transaction_id, reason FROM deviation_notes").fetchall())
    return rules.state(
        all_transactions(conn),
        rules.list_rules(conn),
        [(point["date"], Decimal(str(point["value"]))) for point in history["points"]],
        [
            {
                "name": p["name"],
                "account": p["account"],
                "isin": p["isin"],
                "weight": p["weight_total"],
            }
            for p in report["positions"]
        ],
        reasons,
        today,
    )


def held_names(conn: sqlite3.Connection) -> dict[str, str]:
    """ISIN -> name of every instrument currently held."""
    lines = portfolio.build_lines(all_transactions(conn))
    return {line.isin: line.name or line.isin for line in lines.values() if line.is_open}


def watch(conn: sqlite3.Connection, folder: Path | None, week: str | None = None) -> dict:
    """One weekly watch, each company marked as a held line, a target of the
    roadmap or neither. The watch covers a public list of companies and knows
    nothing of the portfolio: the marking happens here, on this machine."""
    reports = veille.reports(folder) if folder else []
    weeks = [{"semaine": r["semaine"], "du": r["du"], "au": r["au"]} for r in reports]
    chosen = next((r for r in reports if r["semaine"] == week), None) if week else None
    chosen = chosen or (reports[0] if reports else None)
    if chosen is None:
        return {"weeks": weeks, "report": None, "uncovered": []}

    lines = portfolio.build_lines(all_transactions(conn)).values()
    held = {line.isin: line.name or line.isin for line in lines if line.is_open}
    funds = {line.isin for line in lines if line.asset_class == "FUND"}
    # A target entered without its ISIN is recognised by its name, when it is the list's.
    by_name = {title["nom"].casefold(): title["isin"] for title in chosen["titres"]}
    targets = {
        row["isin"] or by_name.get(row["name"].casefold()) or row["name"]: row["name"]
        for row in conn.execute(
            "SELECT isin, name FROM roadmap_items WHERE status IN ('idee', 'prevu')"
        )
    }
    titles = [
        {
            **title,
            "suivi": "ligne"
            if title["isin"] in held
            else "cible"
            if title["isin"] in targets
            else None,
        }
        for title in chosen["titres"]
    ]
    covered = {title["isin"] for title in titles}
    # Funds are left out on purpose: a watch reports on companies.
    uncovered = sorted(
        {name for isin, name in {**targets, **held}.items() if isin not in covered | funds}
    )
    # The reading covers sectors of the public list; which ones are held is known here only.
    lecture = chosen.get("lecture")
    if lecture:
        try:
            sectors = {str(e["isin"]): e.get("secteur") for e in veille.universe_of(folder)}
        except (OSError, ValueError, KeyError):
            sectors = {}
        mine = {sectors.get(isin) for isin in list(held) + list(targets)} - {None}
        lecture = {
            **lecture,
            "secteurs": [
                {**block, "suivi": block["secteur"] in mine} for block in lecture["secteurs"]
            ],
        }
    report = {**chosen, "titres": titles, "lecture": lecture}
    return {"weeks": weeks, "report": report, "uncovered": uncovered}


def readings_record(market, folder: Path | None, today: date | None = None) -> dict:
    """The market balance of each past watch against what the MSCI World did, in
    euros, over the following week. Nothing personal enters this: it compares
    public files with public prices."""
    symbol, label = INDICES["msci-world"]
    readings = [
        {
            "semaine": report["semaine"],
            "du": report["du"],
            "au": report["au"],
            "sens": report["lecture"]["marche"]["balance"]["sens"],
            "confiance": report["lecture"]["marche"]["balance"]["confiance"],
        }
        for report in (veille.reports(folder) if folder else [])
        if report.get("lecture")
    ]
    closes: list[tuple[str, Decimal]] = []
    problem = None
    if readings:
        from .market.provider import ProviderError  # local import: store stays offline

        try:
            closes = market.closes_eur(symbol, min(reading["au"] for reading in readings))
        except ProviderError as exc:
            problem = str(exc)
    return {
        "benchmark": label,
        **bilan.score(readings, closes, today or date.today()),
        "error": problem,
    }


def state(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) AS n, MIN(date) AS first, MAX(date) AS last, "
        "MAX(imported_at) AS imported FROM transactions"
    ).fetchone()
    return {
        "transactions": row["n"],
        "from": row["first"],
        "to": row["last"],
        "last_import": row["imported"],
    }


# -- Snapshots ---------------------------------------------------------------


def take_snapshot(conn: sqlite3.Connection, label: str | None = None) -> int:
    """Freeze today's positions and totals so they can be compared later."""
    data = current_report(conn)
    totals = {key: data[key] for key in ("period", "accounts", "closed_summary", "fees", "flows")}
    totals["manual_orders"] = data["manual_orders"]
    cursor = conn.execute(
        "INSERT INTO snapshots (taken_at, label, totals) VALUES (?, ?, ?)",
        (datetime.now(UTC).isoformat(timespec="seconds"), label or None, json.dumps(totals)),
    )
    snapshot_id = cursor.lastrowid
    conn.executemany(
        "INSERT INTO snapshot_positions "
        "(snapshot_id, account_id, isin, name, shares, cost, price, value) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                snapshot_id,
                p["account"],
                p["isin"],
                p["name"],
                str(p["shares"]),
                str(p["cost"]),
                None if p["price"] is None else str(p["price"]),
                None if p["value"] is None else str(p["value"]),
            )
            for p in data["positions"]
        ],
    )
    conn.commit()
    return snapshot_id


def list_snapshots(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT s.id, s.taken_at, s.label, s.totals, COUNT(p.isin) AS positions "
        "FROM snapshots s LEFT JOIN snapshot_positions p ON p.snapshot_id = s.id "
        "GROUP BY s.id ORDER BY s.id DESC"
    ).fetchall()
    result = []
    for row in rows:
        totals = json.loads(row["totals"])
        result.append(
            {
                "id": row["id"],
                "taken_at": row["taken_at"],
                "label": row["label"],
                "positions": row["positions"],
                "accounts": totals.get("accounts", []),
            }
        )
    return result


def snapshot(conn: sqlite3.Connection, snapshot_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)).fetchone()
    if row is None:
        return None
    positions = conn.execute(
        "SELECT account_id AS account, isin, name, shares, cost, price, value "
        "FROM snapshot_positions WHERE snapshot_id = ? ORDER BY account_id, name",
        (snapshot_id,),
    ).fetchall()

    def number(text: str | None) -> float | None:
        return None if text is None else float(dec(text))

    return {
        "id": row["id"],
        "taken_at": row["taken_at"],
        "label": row["label"],
        **json.loads(row["totals"]),
        "positions": [
            {
                "account": p["account"],
                "isin": p["isin"],
                "name": p["name"],
                "shares": number(p["shares"]),
                "cost": number(p["cost"]),
                "price": number(p["price"]),
                "value": number(p["value"]),
            }
            for p in positions
        ],
    }


def snapshot_csv(data: dict) -> str:
    """Positions of a snapshot as CSV (semicolon-separated, opens in Excel FR)."""
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\n")
    writer.writerow(["compte", "isin", "titre", "quantite", "prix_de_revient", "cours", "valeur"])
    for p in data["positions"]:
        writer.writerow(
            [
                p["account"],
                p["isin"],
                p["name"],
                _fr(p["shares"]),
                _fr(p["cost"]),
                _fr(p["price"]),
                _fr(p["value"]),
            ]
        )
    return out.getvalue()


def _fr(value: float | None) -> str:
    return "" if value is None else repr(value).replace(".", ",")
