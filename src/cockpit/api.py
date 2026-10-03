"""Local HTTP API. It listens on 127.0.0.1 only and serves the dashboard."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import (
    __version__,
    compliance,
    config,
    db,
    gold,
    journal,
    review,
    roadmap,
    rules,
    settings_file,
    store,
    tickets,
)
from .assistant import chat, keys
from .assistant import prompt as assistant_prompt
from .assistant.llm import LLM, MODELS, AnthropicLLM
from .importers import tr_csv
from .market import service as market_service
from .market.provider import ProviderError, QuoteProvider
from .market.yahoo import YahooProvider
from .money import dec

LOCAL_HOSTS = ["127.0.0.1", "localhost", "testserver"]
MAX_CSV_BYTES = 20 * 1024 * 1024


class PriceIn(BaseModel):
    price: str | float
    date: str | None = None


class SnapshotIn(BaseModel):
    label: str | None = None


class SymbolIn(BaseModel):
    symbol: str | None = None


class RuleIn(BaseModel):
    kind: str
    value: str | float
    valid_from: str | None = None
    account: str | None = None
    note: str | None = None


class ReasonIn(BaseModel):
    reason: str = ""


class ComplianceIn(BaseModel):
    isin: str
    status: str
    checked_on: str | None = None
    note: str | None = None


class RoadmapIn(BaseModel):
    name: str
    isin: str | None = None
    account: str | None = None
    amount: str | float | None = None
    entry_condition: str | None = None
    entry_price: str | float | None = None
    thesis: str | None = None
    status: str = "idee"
    symbol: str | None = None


class KeyIn(BaseModel):
    key: str


class AssistantSettingsIn(BaseModel):
    model: str | None = None
    budget_eur: str | float | None = None


class ContextIn(BaseModel):
    title: str
    content: str


class ConversationIn(BaseModel):
    model: str | None = None


class MessageIn(BaseModel):
    text: str
    web_search: bool = False
    model: str | None = None


class JournalIn(BaseModel):
    title: str
    body: str | None = None
    decided_on: str | None = None


class ReviewIn(BaseModel):
    quarter: str


class TextIn(BaseModel):
    text: str = ""


class CommentaryIn(BaseModel):
    model: str | None = None


class TicketIn(BaseModel):
    isin: str | None = None
    name: str | None = None
    account: str | None = None
    side: str | None = None
    shares: str | float | None = None
    amount: str | float | None = None
    order_type: str | None = None
    limit_price: str | float | None = None
    price: str | float | None = None
    fee: str | float | None = None
    reason: str | None = None
    roadmap_item_id: int | None = None


class TicketStatusIn(BaseModel):
    status: str


class TicketMatchIn(BaseModel):
    transaction_id: str | None = None


class GoldLotIn(BaseModel):
    label: str
    grams: str | float
    cost: str | float | None = None
    acquired_on: str | None = None
    note: str | None = None


def _provider_error(exc: ProviderError) -> HTTPException:
    # 503: the source turned us down for now; 502: it answered something unusable.
    return HTTPException(503 if exc.kind in ("refused", "network") else 502, str(exc))


def create_app(
    database: Path | str | None = None,
    provider: QuoteProvider | None = None,
    llm: LLM | None = None,
    key_store: keys.KeyStore | None = None,
) -> FastAPI:
    app = FastAPI(title="Cockpit TR", version=__version__, docs_url=None, redoc_url=None)
    market = market_service.Market(provider or YahooProvider())
    llm = llm or AnthropicLLM()
    key_store = key_store or keys.SystemKeyStore()
    market_busy = threading.Lock()  # one refresh at a time, whatever the number of tabs

    # The app holds personal financial data: answer only to this machine's own
    # browser. The Host check stops DNS rebinding, the Origin check stops another
    # website from sending commands to the local server.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=LOCAL_HOSTS)

    @app.middleware("http")
    async def same_machine_only(request: Request, call_next):
        origin = request.headers.get("origin")
        if (
            request.method not in ("GET", "HEAD", "OPTIONS")
            and origin
            and urlparse(origin).hostname not in LOCAL_HOSTS
        ):
            return JSONResponse({"detail": "Origine refusée."}, status_code=403)
        return await call_next(request)

    def conn() -> Iterator[sqlite3.Connection]:
        connection = db.connect(database)
        try:
            yield connection
        finally:
            connection.close()

    @app.get("/api/state")
    def get_state(c: sqlite3.Connection = Depends(conn)) -> dict:
        return {"version": __version__, **store.state(c)}

    @app.get("/api/report")
    def get_report(c: sqlite3.Connection = Depends(conn)) -> dict:
        return store.current_report(c)

    @app.post("/api/import/csv")
    async def import_csv(request: Request, c: sqlite3.Connection = Depends(conn)) -> dict:
        if not request.headers.get("content-type", "").startswith("text/csv"):
            raise HTTPException(415, "Envoyer le fichier avec le type text/csv.")
        body = await request.body()
        if len(body) > MAX_CSV_BYTES:
            raise HTTPException(413, "Fichier trop volumineux.")
        try:
            text = body.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(400, "Le fichier n'est pas encodé en UTF-8.") from exc
        try:
            report = tr_csv.import_csv(c, text).as_dict()
        except tr_csv.CsvFormatError as exc:
            raise HTTPException(400, str(exc)) from exc
        # An order placed from a ticket shows up here: match it with its ticket.
        return {**report, "tickets": tickets.reconcile(c)}

    @app.put("/api/prices/{isin}")
    def put_price(isin: str, body: PriceIn, c: sqlite3.Connection = Depends(conn)) -> dict:
        known = c.execute("SELECT 1 FROM instruments WHERE isin = ?", (isin,)).fetchone()
        if not known:
            raise HTTPException(404, "Titre inconnu.")
        try:
            price = dec(str(body.price).replace(",", "."))
            day = (
                date.fromisoformat(body.date).isoformat() if body.date else date.today().isoformat()
            )
            store.set_price(c, isin, price, day, source="manuel")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"isin": isin, "price": float(price), "date": day}

    @app.get("/api/snapshots")
    def get_snapshots(c: sqlite3.Connection = Depends(conn)) -> list[dict]:
        return store.list_snapshots(c)

    @app.post("/api/snapshots", status_code=201)
    def post_snapshot(body: SnapshotIn, c: sqlite3.Connection = Depends(conn)) -> dict:
        if store.state(c)["transactions"] == 0:
            raise HTTPException(400, "Aucune transaction : importer un export d'abord.")
        return {"id": store.take_snapshot(c, body.label)}

    def load_snapshot(snapshot_id: int, c: sqlite3.Connection) -> dict:
        data = store.snapshot(c, snapshot_id)
        if data is None:
            raise HTTPException(404, "Snapshot introuvable.")
        return data

    @app.get("/api/snapshots/{snapshot_id}")
    def get_snapshot(snapshot_id: int, c: sqlite3.Connection = Depends(conn)) -> dict:
        return load_snapshot(snapshot_id, c)

    @app.get("/api/snapshots/{snapshot_id}/export.json")
    def export_json(snapshot_id: int, c: sqlite3.Connection = Depends(conn)) -> JSONResponse:
        data = load_snapshot(snapshot_id, c)
        name = f"snapshot_{data['taken_at'][:10]}_{snapshot_id}.json"
        return JSONResponse(data, headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/api/snapshots/{snapshot_id}/export.csv")
    def export_csv(snapshot_id: int, c: sqlite3.Connection = Depends(conn)) -> Response:
        data = load_snapshot(snapshot_id, c)
        name = f"snapshot_{data['taken_at'][:10]}_{snapshot_id}.csv"
        return Response(
            # BOM so that Excel reads the accents correctly.
            "﻿" + store.snapshot_csv(data),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    # -- Market data --------------------------------------------------------

    @app.get("/api/market/instruments")
    def get_instruments(c: sqlite3.Connection = Depends(conn)) -> list[dict]:
        return market_service.instruments(c)

    @app.put("/api/market/instruments/{isin}")
    def put_symbol(isin: str, body: SymbolIn, c: sqlite3.Connection = Depends(conn)) -> dict:
        known = c.execute("SELECT 1 FROM instruments WHERE isin = ?", (isin,)).fetchone()
        if not known:
            raise HTTPException(404, "Titre inconnu.")
        market.set_symbol(c, isin, body.symbol)
        return {"isin": isin, "symbol": (body.symbol or "").strip() or None}

    @app.get("/api/market/instruments/{isin}/candidates")
    def get_candidates(isin: str, c: sqlite3.Connection = Depends(conn)) -> dict:
        """Listings to choose from, by ISIN or else by name. Stores nothing."""
        known = c.execute("SELECT 1 FROM instruments WHERE isin = ?", (isin,)).fetchone()
        if not known:
            raise HTTPException(404, "Titre inconnu.")
        try:
            return market.candidates(c, isin)
        except ProviderError as exc:
            raise _provider_error(exc) from exc

    @app.post("/api/market/refresh")
    def refresh_quotes(c: sqlite3.Connection = Depends(conn)) -> dict:
        """Latest quotes of the instruments held. Safe to call often: each quote
        is asked at most once a minute."""
        if not market_busy.acquire(blocking=False):
            return {"busy": True, **market_service.Outcome().as_dict()}
        try:
            outcome = market.refresh_quotes(c, market_service.open_isins(c))
        finally:
            market_busy.release()
        return {"busy": False, **outcome.as_dict()}

    @app.post("/api/market/history")
    def load_history(c: sqlite3.Connection = Depends(conn)) -> dict:
        """Daily prices of every instrument ever held, since the first transaction."""
        since = store.state(c)["from"]
        if since is None:
            raise HTTPException(400, "Aucune transaction : importer un export d'abord.")
        with market_busy:
            outcome = market.load_history(c, market_service.all_isins(c), since)
        return {"busy": False, **outcome.as_dict()}

    @app.get("/api/market/chart/{isin}")
    def get_chart(
        isin: str, range: str = "1j", devise: str = "", c: sqlite3.Connection = Depends(conn)
    ) -> dict:
        try:
            return market.chart(c, isin, range, in_euros=devise.lower() == "eur")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except ProviderError as exc:
            raise _provider_error(exc) from exc

    @app.get("/api/securities/{isin}")
    def get_security(isin: str, devise: str = "", c: sqlite3.Connection = Depends(conn)) -> dict:
        """One instrument ever held: the user's trades on it and its key figures.
        The figures come from the price source; without it, the trades still show."""
        row = c.execute(
            "SELECT name, asset_class FROM instruments WHERE isin = ?", (isin,)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Titre inconnu.")
        stats, problem = None, None
        try:
            stats = market.stats(c, isin, in_euros=devise.lower() == "eur")
        except ProviderError as exc:
            problem = str(exc)
        return {
            "isin": isin,
            "name": row["name"],
            "asset_class": row["asset_class"],
            "held": isin in store.held_names(c),
            "trades": market_service.trades(c, isin),
            "stats": stats,
            "stats_error": problem,
        }

    @app.get("/api/portfolio/history")
    def get_value_history(c: sqlite3.Connection = Depends(conn)) -> dict:
        return store.value_history(c)

    @app.get("/api/portfolio/performance")
    def get_performance(indice: str | None = None, c: sqlite3.Connection = Depends(conn)) -> dict:
        return store.performance_view(c, market, indice)

    @app.get("/api/portfolio/allocation")
    def get_allocation(c: sqlite3.Connection = Depends(conn)) -> dict:
        return store.allocation_view(c, config.fiches_dir())

    # -- Rules ---------------------------------------------------------------

    @app.get("/api/rules")
    def get_rules(c: sqlite3.Connection = Depends(conn)) -> dict:
        return store.rules_state(c)

    @app.post("/api/rules", status_code=201)
    def post_rule(body: RuleIn, c: sqlite3.Connection = Depends(conn)) -> dict:
        try:
            rule_id = rules.set_rule(
                c, body.kind, body.value, body.valid_from, body.account, body.note
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"id": rule_id}

    @app.delete("/api/rules/{rule_id}")
    def delete_rule(rule_id: int, c: sqlite3.Connection = Depends(conn)) -> dict:
        if not rules.delete_rule(c, rule_id):
            raise HTTPException(404, "Règle introuvable.")
        return {"deleted": rule_id}

    @app.put("/api/deviations/{transaction_id}")
    def put_reason(
        transaction_id: str, body: ReasonIn, c: sqlite3.Connection = Depends(conn)
    ) -> dict:
        try:
            rules.set_reason(c, transaction_id, body.reason)
        except KeyError as exc:
            raise HTTPException(404, "Transaction inconnue.") from exc
        return {"transaction_id": transaction_id, "reason": body.reason.strip() or None}

    # -- Compliance ----------------------------------------------------------

    @app.get("/api/compliance")
    def get_compliance(c: sqlite3.Connection = Depends(conn)) -> dict:
        return compliance.overview(c, store.held_names(c))

    @app.post("/api/compliance", status_code=201)
    def post_compliance(body: ComplianceIn, c: sqlite3.Connection = Depends(conn)) -> dict:
        try:
            compliance.record(c, body.isin, body.status, body.checked_on, body.note)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"isin": body.isin.strip().upper()}

    # -- Roadmap -------------------------------------------------------------

    @app.get("/api/roadmap")
    def get_roadmap(c: sqlite3.Connection = Depends(conn)) -> dict:
        return roadmap.items(c)

    @app.post("/api/roadmap", status_code=201)
    def post_roadmap(body: RoadmapIn, c: sqlite3.Connection = Depends(conn)) -> dict:
        try:
            return {"id": roadmap.create(c, body.model_dump())}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.put("/api/roadmap/{item_id}")
    def put_roadmap(item_id: int, body: RoadmapIn, c: sqlite3.Connection = Depends(conn)) -> dict:
        try:
            found = roadmap.update(c, item_id, body.model_dump())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not found:
            raise HTTPException(404, "Cible introuvable.")
        return {"id": item_id}

    @app.delete("/api/roadmap/{item_id}")
    def delete_roadmap(item_id: int, c: sqlite3.Connection = Depends(conn)) -> dict:
        if not roadmap.delete(c, item_id):
            raise HTTPException(404, "Cible introuvable.")
        return {"deleted": item_id}

    @app.post("/api/roadmap/prices")
    def refresh_roadmap(c: sqlite3.Connection = Depends(conn)) -> dict:
        with market_busy:
            return roadmap.refresh_prices(c, market)

    # -- Order tickets -------------------------------------------------------
    # A ticket is prepared and checked here; the order is placed by the user in
    # the broker's application. No route sends anything to a broker.

    def ticket_view(c: sqlite3.Connection, ticket_id: int) -> dict:
        return tickets.get(c, ticket_id, config.fiches_dir())

    def ticket_call(action, *args) -> None:
        try:
            action(*args)
        except KeyError as exc:
            raise HTTPException(404, "Ticket introuvable.") from exc
        except tickets.TicketError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/tickets")
    def get_tickets(c: sqlite3.Connection = Depends(conn)) -> dict:
        return tickets.listing(c, config.fiches_dir())

    @app.get("/api/tickets/summary")
    def get_tickets_summary(c: sqlite3.Connection = Depends(conn)) -> dict:
        return tickets.summary(c)

    @app.post("/api/tickets", status_code=201)
    def post_ticket(body: TicketIn, c: sqlite3.Connection = Depends(conn)) -> dict:
        try:
            ticket_id = tickets.create(
                c, body.model_dump(exclude_unset=True), fiches=config.fiches_dir()
            )
        except tickets.TicketError as exc:
            raise HTTPException(400, str(exc)) from exc
        return ticket_view(c, ticket_id)

    @app.post("/api/tickets/reconcile")
    def reconcile_tickets(c: sqlite3.Connection = Depends(conn)) -> dict:
        return tickets.reconcile(c)

    @app.put("/api/tickets/{ticket_id}")
    def put_ticket(ticket_id: int, body: TicketIn, c: sqlite3.Connection = Depends(conn)) -> dict:
        ticket_call(
            tickets.update, c, ticket_id, body.model_dump(exclude_unset=True), config.fiches_dir()
        )
        return ticket_view(c, ticket_id)

    @app.post("/api/tickets/{ticket_id}/status")
    def post_ticket_status(
        ticket_id: int, body: TicketStatusIn, c: sqlite3.Connection = Depends(conn)
    ) -> dict:
        ticket_call(tickets.set_status, c, ticket_id, body.status, config.fiches_dir())
        return ticket_view(c, ticket_id)

    @app.post("/api/tickets/{ticket_id}/price")
    def post_ticket_price(ticket_id: int, c: sqlite3.Connection = Depends(conn)) -> dict:
        try:
            with market_busy:
                ticket_call(tickets.refresh_price, c, market, ticket_id)
        except ProviderError as exc:
            raise _provider_error(exc) from exc
        return ticket_view(c, ticket_id)

    @app.post("/api/tickets/{ticket_id}/match")
    def post_ticket_match(
        ticket_id: int, body: TicketMatchIn, c: sqlite3.Connection = Depends(conn)
    ) -> dict:
        ticket_call(tickets.match, c, ticket_id, body.transaction_id)
        return ticket_view(c, ticket_id)

    @app.delete("/api/tickets/{ticket_id}")
    def delete_ticket(ticket_id: int, c: sqlite3.Connection = Depends(conn)) -> dict:
        ticket_call(tickets.delete, c, ticket_id)
        return {"deleted": ticket_id}

    # -- Physical gold -------------------------------------------------------

    @app.get("/api/gold")
    def get_gold(c: sqlite3.Connection = Depends(conn)) -> dict:
        return gold.summary(c)

    @app.post("/api/gold/lots", status_code=201)
    def post_gold_lot(body: GoldLotIn, c: sqlite3.Connection = Depends(conn)) -> dict:
        try:
            return {"id": gold.add_lot(c, body.model_dump())}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.put("/api/gold/lots/{lot_id}")
    def put_gold_lot(lot_id: int, body: GoldLotIn, c: sqlite3.Connection = Depends(conn)) -> dict:
        try:
            found = gold.update_lot(c, lot_id, body.model_dump())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not found:
            raise HTTPException(404, "Lot introuvable.")
        return {"id": lot_id}

    @app.delete("/api/gold/lots/{lot_id}")
    def delete_gold_lot(lot_id: int, c: sqlite3.Connection = Depends(conn)) -> dict:
        if not gold.delete_lot(c, lot_id):
            raise HTTPException(404, "Lot introuvable.")
        return {"deleted": lot_id}

    @app.post("/api/gold/price")
    def refresh_gold(c: sqlite3.Connection = Depends(conn)) -> dict:
        try:
            with market_busy:
                gold.refresh_price(c, market)
        except ProviderError as exc:
            raise _provider_error(exc) from exc
        return gold.summary(c)

    # -- Assistant -----------------------------------------------------------

    def assistant_status(c: sqlite3.Connection) -> dict:
        _, source = keys.resolve(key_store)
        return {
            "configured": source is not None,
            "key_source": source,  # where the key is kept; the key itself never leaves
            "models": [{"id": name, "label": spec["label"]} for name, spec in MODELS.items()],
            "default_model": chat.default_model(c),
            "month": chat.month_usage(c),
        }

    @app.get("/api/assistant/status")
    def get_assistant_status(c: sqlite3.Connection = Depends(conn)) -> dict:
        return assistant_status(c)

    @app.put("/api/assistant/key")
    def put_key(body: KeyIn, c: sqlite3.Connection = Depends(conn)) -> dict:
        try:
            key_store.set(keys.check_format(body.key))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except keys.KeyStoreError as exc:
            raise HTTPException(500, str(exc)) from exc
        return assistant_status(c)

    @app.delete("/api/assistant/key")
    def delete_key(c: sqlite3.Connection = Depends(conn)) -> dict:
        key_store.delete()
        return assistant_status(c)

    @app.put("/api/assistant/settings")
    def put_assistant_settings(
        body: AssistantSettingsIn, c: sqlite3.Connection = Depends(conn)
    ) -> dict:
        try:
            if body.model is not None:
                chat.set_default_model(c, body.model)
            if body.budget_eur is not None:
                chat.set_budget(c, body.budget_eur)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return assistant_status(c)

    @app.get("/api/assistant/context")
    def get_context(c: sqlite3.Connection = Depends(conn)) -> list[dict]:
        return assistant_prompt.documents(c)

    @app.put("/api/assistant/context")
    def put_context(body: ContextIn, c: sqlite3.Connection = Depends(conn)) -> dict:
        try:
            return {"id": assistant_prompt.save_document(c, body.title, body.content)}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.delete("/api/assistant/context/{document_id}")
    def delete_context(document_id: int, c: sqlite3.Connection = Depends(conn)) -> dict:
        if not assistant_prompt.delete_document(c, document_id):
            raise HTTPException(404, "Document introuvable.")
        return {"deleted": document_id}

    @app.get("/api/assistant/conversations")
    def get_conversations(c: sqlite3.Connection = Depends(conn)) -> list[dict]:
        return chat.listing(c)

    @app.post("/api/assistant/conversations", status_code=201)
    def post_conversation(body: ConversationIn, c: sqlite3.Connection = Depends(conn)) -> dict:
        return chat.view(c, chat.create(c, body.model))

    @app.get("/api/assistant/conversations/{conversation_id}")
    def get_conversation(conversation_id: int, c: sqlite3.Connection = Depends(conn)) -> dict:
        data = chat.view(c, conversation_id)
        if data is None:
            raise HTTPException(404, "Discussion introuvable.")
        return data

    @app.delete("/api/assistant/conversations/{conversation_id}")
    def delete_conversation(conversation_id: int, c: sqlite3.Connection = Depends(conn)) -> dict:
        if not chat.delete(c, conversation_id):
            raise HTTPException(404, "Discussion introuvable.")
        return {"deleted": conversation_id}

    @app.post("/api/assistant/conversations/{conversation_id}/messages")
    def post_message(conversation_id: int, body: MessageIn) -> StreamingResponse:
        """Send a message; the answer comes back as a stream of events."""
        api_key, _ = keys.resolve(key_store)
        if not api_key:
            raise HTTPException(400, "Aucune clé d'API enregistrée.")

        def events() -> Iterator[str]:
            # The stream outlives the request handler: it needs its own connection.
            connection = db.connect(database)
            try:
                for event in chat.send(
                    connection,
                    llm,
                    api_key,
                    conversation_id,
                    body.text,
                    web_search=body.web_search,
                    model=body.model,
                ):
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            finally:
                connection.close()

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    # -- Decision journal ------------------------------------------------------

    @app.get("/api/journal")
    def get_journal(c: sqlite3.Connection = Depends(conn)) -> list[dict]:
        return journal.entries(c)

    @app.post("/api/journal", status_code=201)
    def post_journal(body: JournalIn, c: sqlite3.Connection = Depends(conn)) -> dict:
        try:
            return {"id": journal.add(c, body.model_dump())}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.put("/api/journal/{entry_id}")
    def put_journal(entry_id: int, body: JournalIn, c: sqlite3.Connection = Depends(conn)) -> dict:
        try:
            found = journal.update(c, entry_id, body.model_dump())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not found:
            raise HTTPException(404, "Note introuvable.")
        return {"id": entry_id}

    @app.delete("/api/journal/{entry_id}")
    def delete_journal(entry_id: int, c: sqlite3.Connection = Depends(conn)) -> dict:
        if not journal.delete(c, entry_id):
            raise HTTPException(404, "Note introuvable.")
        return {"deleted": entry_id}

    # -- Quarterly review ----------------------------------------------------

    @app.get("/api/reviews")
    def get_reviews(c: sqlite3.Connection = Depends(conn)) -> dict:
        return review.listing(c)

    @app.post("/api/reviews", status_code=201)
    def post_review(body: ReviewIn, c: sqlite3.Connection = Depends(conn)) -> dict:
        """Compute the review of a quarter and keep it; again, to refresh its figures."""
        try:
            return review.generate(c, body.quarter, config.fiches_dir())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    def kept_review(quarter: str, c: sqlite3.Connection) -> dict:
        found = review.get(c, quarter)
        if found is None:
            raise HTTPException(404, "Revue introuvable.")
        return found

    @app.get("/api/reviews/{quarter}")
    def get_review(quarter: str, c: sqlite3.Connection = Depends(conn)) -> dict:
        return kept_review(quarter, c)

    @app.put("/api/reviews/{quarter}/conclusions")
    def put_conclusions(quarter: str, body: TextIn, c: sqlite3.Connection = Depends(conn)) -> dict:
        if not review.set_conclusions(c, quarter, body.text):
            raise HTTPException(404, "Revue introuvable.")
        return kept_review(quarter, c)

    @app.post("/api/reviews/{quarter}/commentary")
    def post_commentary(
        quarter: str, body: CommentaryIn, c: sqlite3.Connection = Depends(conn)
    ) -> dict:
        """Ask the assistant to read the review. Billed like any message to it."""
        kept_review(quarter, c)
        api_key, _ = keys.resolve(key_store)
        if not api_key:
            raise HTTPException(400, "Aucune clé d'API enregistrée.")
        model = body.model if body.model in MODELS else chat.default_model(c)
        try:
            return review.comment(c, llm, api_key, quarter, model)
        except review.CommentaryError as exc:
            raise HTTPException(502, str(exc)) from exc

    @app.get("/api/reviews/{quarter}/export")
    def export_review(quarter: str, c: sqlite3.Connection = Depends(conn)) -> Response:
        text = review.markdown(kept_review(quarter, c))
        return Response(
            text,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="revue-{quarter}.md"'},
        )

    @app.delete("/api/reviews/{quarter}")
    def delete_review(quarter: str, c: sqlite3.Connection = Depends(conn)) -> dict:
        if not review.delete(c, quarter):
            raise HTTPException(404, "Revue introuvable.")
        return {"deleted": quarter}

    # -- Weekly watch --------------------------------------------------------

    @app.get("/api/veille")
    def get_watch(semaine: str | None = None, c: sqlite3.Connection = Depends(conn)) -> dict:
        return store.watch(c, config.veilles_dir(), semaine)

    @app.get("/api/veille/bilan")
    def get_readings_record() -> dict:
        """How the past readings fared against the market. Asks the price source."""
        return store.readings_record(market, config.veilles_dir())

    # -- Settings file -------------------------------------------------------

    @app.get("/api/settings/export")
    def export_settings(c: sqlite3.Connection = Depends(conn)) -> JSONResponse:
        name = f"cockpit-reglages_{date.today().isoformat()}.json"
        return JSONResponse(
            settings_file.export(c),
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    @app.post("/api/settings/import")
    async def import_settings(request: Request, c: sqlite3.Connection = Depends(conn)) -> dict:
        body = await request.body()
        if len(body) > 1024 * 1024:
            raise HTTPException(413, "Fichier trop volumineux.")
        try:
            return settings_file.load(c, json.loads(body.decode("utf-8-sig")))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(400, "Le fichier n'est pas un JSON lisible.") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    frontend = config.frontend_dir()
    if frontend:
        app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path.startswith("api/"):
                raise HTTPException(404)
            candidate = (frontend / path).resolve()
            if path and candidate.is_file() and frontend.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(frontend / "index.html")

    return app
