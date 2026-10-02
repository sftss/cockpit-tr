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
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__, compliance, config, db, gold, roadmap, rules, settings_file, store
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
    database: Path | str | None = None, provider: QuoteProvider | None = None
) -> FastAPI:
    app = FastAPI(title="Cockpit TR", version=__version__, docs_url=None, redoc_url=None)
    market = market_service.Market(provider or YahooProvider())
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
            return tr_csv.import_csv(c, text).as_dict()
        except tr_csv.CsvFormatError as exc:
            raise HTTPException(400, str(exc)) from exc

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
    def get_chart(isin: str, range: str = "1j", c: sqlite3.Connection = Depends(conn)) -> dict:
        try:
            return market.chart(c, isin, range)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except ProviderError as exc:
            raise _provider_error(exc) from exc

    @app.get("/api/portfolio/history")
    def get_value_history(c: sqlite3.Connection = Depends(conn)) -> dict:
        return store.value_history(c)

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
