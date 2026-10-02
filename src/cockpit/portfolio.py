"""Portfolio calculations, derived only from the stored transactions.

Conventions (they reproduce the figures of the 01/10/2026 strategy review):

* A *line* is one instrument in one account.
* Quantities move with trades and with corporate actions (split, bonus issue,
  migration). Dividend lines also carry a quantity, but it is the holding at
  the time, not a movement, so only the TRADING, CORPORATE_ACTION and DELIVERY
  categories change a quantity.
* Cost is tracked at average cost ("prix de revient unitaire"): a sale releases
  the average cost of the shares sold; a split changes the quantity, not the cost.
* A line is *closed* once its quantity is back to zero. Its gross result is
  what was received minus what was paid; the net result subtracts order fees.
  Transaction taxes are reported separately.
* A *manual order* is a trade that paid a fee. Savings-plan executions and
  round-ups are free at Trade Republic, so they are not counted.
* Capital brought in = deposits (before deposit fees) minus card spending, the
  Trade Republic account being also a current account.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from .money import SHARE_EPSILON, ZERO, dec, money, qty, ratio

TRADES = {"BUY", "SELL"}
SHARE_CATEGORIES = {"TRADING", "CORPORATE_ACTION", "DELIVERY"}
DEPOSITS = {"CUSTOMER_INPAYMENT", "TRANSFER_INBOUND"}
CARD = {"CARD_TRANSACTION", "CARD_TRANSACTION_INTERNATIONAL"}
DIVIDENDS = {"DIVIDEND", "DIVIDEND_EQUIVALENT_PAYMENT"}
INTEREST = {"INTEREST_PAYMENT"}

Row = Mapping[str, object]


def _sort_key(row: Row) -> tuple:
    stamp = str(row["datetime"])
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        return (0, parsed.timestamp(), stamp)
    except ValueError:
        return (1, 0.0, stamp)


def chronological(rows: Iterable[Row]) -> list[Row]:
    return sorted(rows, key=_sort_key)


def quarter_of(day: str) -> str:
    """'2026-08-17' -> '2026-T3'."""
    year, month = int(day[:4]), int(day[5:7])
    return f"{year}-T{(month - 1) // 3 + 1}"


@dataclass
class Line:
    account: str
    isin: str
    name: str = ""
    asset_class: str = ""
    shares: Decimal = ZERO
    cost: Decimal = ZERO  # average cost of the shares still held
    bought: Decimal = ZERO  # paid on buys, fees excluded
    sold: Decimal = ZERO  # received on sells, fees excluded
    fees: Decimal = ZERO
    taxes: Decimal = ZERO
    realized: Decimal = ZERO  # gross result of what was sold, at average cost
    dividends: Decimal = ZERO
    buys: int = 0
    sells: int = 0
    manual_orders: int = 0
    first_buy: str | None = None
    last_trade: str | None = None
    anomalies: list[str] = field(default_factory=list)

    @property
    def is_open(self) -> bool:
        return abs(self.shares) >= SHARE_EPSILON

    @property
    def is_closed(self) -> bool:
        return not self.is_open and self.buys > 0

    @property
    def average_cost(self) -> Decimal | None:
        return self.cost / self.shares if self.is_open and self.shares > 0 else None

    @property
    def gross_result(self) -> Decimal:
        """Received minus paid. Meaningful as a final result on a closed line."""
        return self.sold - self.bought

    @property
    def net_result(self) -> Decimal:
        return self.gross_result - self.fees

    @property
    def holding_days(self) -> int | None:
        if not (self.first_buy and self.last_trade):
            return None
        return (date.fromisoformat(self.last_trade) - date.fromisoformat(self.first_buy)).days


def build_lines(rows: Iterable[Row]) -> dict[tuple[str, str], Line]:
    lines: dict[tuple[str, str], Line] = {}
    for row in chronological(rows):
        isin = str(row["isin"] or "")
        if not isin:
            continue
        tx_type = str(row["type"])
        category = str(row["category"])
        if tx_type not in DIVIDENDS and category not in SHARE_CATEGORIES:
            continue

        key = (str(row["account_id"]), isin)
        line = lines.setdefault(key, Line(account=key[0], isin=isin))
        if row["name"]:
            line.name = str(row["name"])
        if row["asset_class"]:
            line.asset_class = str(row["asset_class"])

        if tx_type in DIVIDENDS:
            line.dividends += dec(row["amount"])
            continue

        day = str(row["date"])
        quantity = abs(dec(row["shares"]))
        value = abs(dec(row["amount"]))
        fee = -dec(row["fee"])  # exported negative when paid

        if tx_type == "BUY":
            line.shares += quantity
            line.cost += value
            line.bought += value
            line.buys += 1
            line.first_buy = line.first_buy or day
        elif tx_type == "SELL":
            held = line.shares
            if held < SHARE_EPSILON:
                line.anomalies.append(f"{day} : vente sans quantité détenue")
                released = ZERO
            elif held - quantity < SHARE_EPSILON:
                released = line.cost  # last shares: release everything, no rounding dust
            else:
                released = line.cost * quantity / held
            line.cost -= released
            line.realized += value - released
            line.shares -= quantity
            line.sold += value
            line.sells += 1
        else:
            # Split, bonus issue, migration, delivery: quantity only, cost unchanged.
            line.shares += dec(row["shares"])
            continue

        line.fees += fee
        line.taxes += -dec(row["tax"])
        line.last_trade = day
        if fee != 0:
            line.manual_orders += 1
        if not line.is_open:
            line.shares = ZERO
            line.cost = ZERO
    return lines


@dataclass
class Flows:
    deposits: Decimal = ZERO  # before deposit fees
    deposit_fees: Decimal = ZERO
    card_spending: Decimal = ZERO  # positive = spent
    dividends: Decimal = ZERO
    interest: Decimal = ZERO
    income_taxes: Decimal = ZERO
    order_fees: dict[str, Decimal] = field(default_factory=lambda: defaultdict(lambda: ZERO))
    other_fees: Decimal = ZERO
    cash: dict[str, Decimal] = field(default_factory=lambda: defaultdict(lambda: ZERO))
    quarters: dict[str, dict[str, Decimal | int]] = field(default_factory=dict)

    @property
    def capital_brought_in(self) -> Decimal:
        return self.deposits - self.card_spending

    @property
    def total_order_fees(self) -> Decimal:
        return sum(self.order_fees.values(), ZERO)

    @property
    def total_fees(self) -> Decimal:
        return self.total_order_fees + self.deposit_fees + self.other_fees


def build_flows(rows: Iterable[Row]) -> Flows:
    flows = Flows()
    for row in rows:
        tx_type = str(row["type"])
        account = str(row["account_id"])
        # Fees and taxes are exported as negative numbers when paid.
        amount, fee, tax = dec(row["amount"]), -dec(row["fee"]), -dec(row["tax"])
        day = str(row["date"])

        # Estimated cash: every line moves the balance by amount, fee and tax.
        flows.cash[account] += amount - fee - tax

        quarter = flows.quarters.setdefault(
            quarter_of(day),
            {"manual_orders": 0, "trades": 0, "order_fees": ZERO, "deposit_fees": ZERO},
        )
        if tx_type in TRADES:
            flows.order_fees[account] += fee
            quarter["trades"] += 1
            quarter["order_fees"] += fee
            if fee != 0:
                quarter["manual_orders"] += 1
        elif tx_type in DEPOSITS:
            flows.deposits += amount
            flows.deposit_fees += fee
            quarter["deposit_fees"] += fee
        else:
            flows.other_fees += fee
            if tx_type in CARD:
                flows.card_spending -= amount
            elif tx_type in DIVIDENDS:
                flows.dividends += amount
                flows.income_taxes += tax
            elif tx_type in INTEREST:
                flows.interest += amount
                flows.income_taxes += tax
    return flows


# --------------------------------------------------------------------------
# Presentation: plain dictionaries, ready for JSON.
# --------------------------------------------------------------------------


def _position(line: Line, price: Mapping[str, object] | None) -> dict:
    unit = dec(price["price"]) if price else None
    value = line.shares * unit if unit is not None else None
    latent = value - line.cost if value is not None else None
    return {
        "account": line.account,
        "isin": line.isin,
        "name": line.name or line.isin,
        "asset_class": line.asset_class,
        "shares": qty(line.shares),
        "cost": money(line.cost),
        "average_cost": money(line.average_cost),
        "price": float(unit) if unit is not None else None,
        "price_date": price["date"] if price else None,
        "value": money(value),
        "latent": money(latent),
        "latent_pct": ratio(latent, line.cost) if latent is not None else None,
        "fees": money(line.fees),
        "realized": money(line.realized),
        "dividends": money(line.dividends),
        "first_buy": line.first_buy,
        "manual_orders": line.manual_orders,
        "anomalies": line.anomalies,
    }


def _closed(line: Line) -> dict:
    return {
        "account": line.account,
        "isin": line.isin,
        "name": line.name or line.isin,
        "bought": money(line.bought),
        "sold": money(line.sold),
        "gross": money(line.gross_result),
        "fees": money(line.fees),
        "taxes": money(line.taxes),
        "net": money(line.net_result),
        "net_pct": ratio(line.net_result, line.bought),
        "dividends": money(line.dividends),
        "first_buy": line.first_buy,
        "closed_on": line.last_trade,
        "holding_days": line.holding_days,
    }


def report(rows: Iterable[Row], prices: Mapping[str, Mapping[str, object]] | None = None) -> dict:
    """Everything the dashboard shows, computed in one pass over the transactions."""
    rows = list(rows)
    prices = prices or {}
    lines = build_lines(rows)
    flows = build_flows(rows)

    open_lines = [line for line in lines.values() if line.is_open]
    closed_lines = [line for line in lines.values() if line.is_closed]

    positions = [_position(line, prices.get(line.isin)) for line in open_lines]

    accounts = []
    for account in sorted({line.account for line in lines.values()} | set(flows.cash)):
        mine = [p for p in positions if p["account"] == account]
        all_lines = [line for line in lines.values() if line.account == account]
        cost = sum((line.cost for line in open_lines if line.account == account), ZERO)
        priced = [p for p in mine if p["value"] is not None]
        fully_priced = bool(mine) and len(priced) == len(mine)
        value = sum((Decimal(str(p["value"])) for p in priced), ZERO) if fully_priced else None
        net_invested = sum((line.bought - line.sold for line in all_lines), ZERO)
        closed = [line for line in closed_lines if line.account == account]

        # Weights: on market value when every line has a price, otherwise on cost.
        basis = "value" if fully_priced else "cost"
        total = value if fully_priced else cost
        for p in mine:
            share = Decimal(str(p[basis])) if p[basis] is not None else ZERO
            p["weight"] = ratio(share, total) if total else None
            p["weight_basis"] = basis

        accounts.append(
            {
                "account": account,
                "open_lines": len(mine),
                "closed_lines": len(closed),
                "net_invested": money(net_invested),
                "open_cost": money(cost),
                "value": money(value),
                "priced_lines": len(priced),
                "latent": money(value - cost) if value is not None else None,
                "performance": ratio(value - net_invested, net_invested)
                if value is not None
                else None,
                "closed_net": money(sum((line.net_result for line in closed), ZERO)),
                "order_fees": money(flows.order_fees.get(account, ZERO)),
                "dividends": money(sum((line.dividends for line in all_lines), ZERO)),
                "cash_estimate": money(flows.cash.get(account, ZERO)),
            }
        )

    closed_rows = sorted(
        (_closed(line) for line in closed_lines), key=lambda c: c["closed_on"] or "", reverse=True
    )
    bought = sum((line.bought for line in closed_lines), ZERO)
    gross = sum((line.gross_result for line in closed_lines), ZERO)
    closed_fees = sum((line.fees for line in closed_lines), ZERO)
    closed_summary = {
        "count": len(closed_lines),
        "winners": sum(1 for line in closed_lines if line.net_result > 0),
        "bought": money(bought),
        "gross": money(gross),
        "fees": money(closed_fees),
        "taxes": money(sum((line.taxes for line in closed_lines), ZERO)),
        "net": money(gross - closed_fees),
        "net_pct": ratio(gross - closed_fees, bought),
    }

    quarters = [
        {
            "quarter": name,
            "manual_orders": data["manual_orders"],
            "trades": data["trades"],
            "order_fees": money(data["order_fees"]),
            "deposit_fees": money(data["deposit_fees"]),
        }
        for name, data in sorted(flows.quarters.items())
    ]

    dates = sorted(str(row["date"]) for row in rows)
    return {
        "period": {"from": dates[0], "to": dates[-1]} if dates else None,
        "transactions": len(rows),
        "accounts": accounts,
        "positions": sorted(positions, key=lambda p: (p["account"], -(p["weight"] or 0))),
        "closed": closed_rows,
        "closed_summary": closed_summary,
        "fees": {
            "orders": {acc: money(val) for acc, val in sorted(flows.order_fees.items())},
            "deposits": money(flows.deposit_fees),
            "other": money(flows.other_fees),
            "total": money(flows.total_fees),
            "share_of_capital": ratio(flows.total_fees, flows.capital_brought_in),
        },
        "flows": {
            "deposits": money(flows.deposits),
            "card_spending": money(flows.card_spending),
            "capital_brought_in": money(flows.capital_brought_in),
            "dividends": money(flows.dividends),
            "interest": money(flows.interest),
            "income_taxes": money(flows.income_taxes),
        },
        "quarters": quarters,
        "manual_orders": sum(q["manual_orders"] for q in quarters),
        "anomalies": [
            f"{line.name or line.isin} ({line.account}) — {message}"
            for line in lines.values()
            for message in line.anomalies
        ],
    }
