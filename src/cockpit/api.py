"""Local HTTP API. It listens on 127.0.0.1 only and serves the dashboard."""

from __future__ import annotations

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

from . import __version__, config, db, store
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
