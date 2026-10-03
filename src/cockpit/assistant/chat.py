"""Conversations with the assistant: storage, the tool loop, what the screen shows.

One user message can take several calls to the model: it asks for a tool, the
tool runs here, its result goes back, and so on until it answers. Every message
exchanged is stored as it was, so a conversation resumes where it stopped.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

from ..money import dec
from . import prompt, tools
from .llm import DEFAULT_MODEL, LLM, MODELS, WEB_SEARCH_TOOL, LLMError, Reply, Usage, cost

MAX_STEPS = 8  # calls to the model for one user message
MAX_TOKENS = 8192
MAX_MESSAGE_CHARS = 20_000
DEFAULT_BUDGET_EUR = Decimal(10)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# -- Settings ------------------------------------------------------------------


def setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


def default_model(conn: sqlite3.Connection) -> str:
    chosen = setting(conn, "assistant_model", DEFAULT_MODEL)
    return chosen if chosen in MODELS else DEFAULT_MODEL


def set_default_model(conn: sqlite3.Connection, model: str) -> None:
    if model not in MODELS:
        raise ValueError("Modèle inconnu.")
    set_setting(conn, "assistant_model", model)


def budget(conn: sqlite3.Connection) -> Decimal:
    return dec(setting(conn, "assistant_budget_eur", str(DEFAULT_BUDGET_EUR)))


def set_budget(conn: sqlite3.Connection, value: object) -> None:
    amount = dec(str(value).replace(",", "."))
    if amount <= 0:
        raise ValueError("Le budget doit être positif.")
    set_setting(conn, "assistant_budget_eur", str(amount))


def month_usage(conn: sqlite3.Connection) -> dict:
    """What the assistant cost since the first day of the month (UTC)."""
    start = datetime.now(UTC).strftime("%Y-%m-01")
    row = conn.execute(
        "SELECT COUNT(*) AS calls, COALESCE(SUM(input_tokens + cache_read_tokens + "
        "cache_write_tokens), 0) AS tokens_in, COALESCE(SUM(output_tokens), 0) AS tokens_out, "
        "COALESCE(SUM(web_searches), 0) AS searches FROM messages "
        "WHERE role = 'assistant' AND created_at >= ?",
        (start,),
    ).fetchone()
    costs = conn.execute(
        "SELECT cost_usd FROM messages WHERE role = 'assistant' AND created_at >= ? "
        "AND cost_usd IS NOT NULL",
        (start,),
    ).fetchall()
    usd = sum((dec(c["cost_usd"]) for c in costs), Decimal(0))
    rate = conn.execute(
        "SELECT rate FROM fx_rates WHERE currency = 'USD' ORDER BY date DESC LIMIT 1"
    ).fetchone()
    eur = usd / dec(rate["rate"]) if rate and dec(rate["rate"]) > 0 else None
    limit = budget(conn)
    return {
        "month": start[:7],
        "calls": row["calls"],
        "tokens_in": row["tokens_in"],
        "tokens_out": row["tokens_out"],
        "web_searches": row["searches"],
        "cost_usd": float(usd.quantize(Decimal("0.0001"))),
        "cost_eur": float(eur.quantize(Decimal("0.0001"))) if eur is not None else None,
        "budget_eur": float(limit),
        # Without an exchange rate, the dollar amount is compared to the budget as it is:
        # it overstates the cost a little, which is the safe side for a warning.
        "share_of_budget": float(
            ((eur if eur is not None else usd) / limit).quantize(Decimal("0.001"))
        ),
    }


# -- Conversations ---------------------------------------------------------------


def create(conn: sqlite3.Connection, model: str | None = None) -> int:
    model = model if model in MODELS else default_model(conn)
    now = _now()
    cursor = conn.execute(
        "INSERT INTO conversations (title, model, created_at, updated_at) VALUES (?, ?, ?, ?)",
        ("Nouvelle discussion", model, now, now),
    )
    conn.commit()
    return cursor.lastrowid


def delete(conn: sqlite3.Connection, conversation_id: int) -> bool:
    deleted = conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,)).rowcount
    conn.commit()
    return bool(deleted)


def listing(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT c.id, c.title, c.model, c.updated_at, "
        "(SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS messages "
        "FROM conversations c ORDER BY c.updated_at DESC, c.id DESC"
    ).fetchall()
    return [dict(row) for row in rows]


def _history(conn: sqlite3.Connection, conversation_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id", (conversation_id,)
    ).fetchall()


def view(conn: sqlite3.Connection, conversation_id: int) -> dict | None:
    """The conversation as the screen shows it: what was asked, what was answered."""
    conversation = conn.execute(
        "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
    ).fetchone()
    if conversation is None:
        return None
    turns: list[dict] = []
    for row in _history(conn, conversation_id):
        blocks = json.loads(row["content"])
        if row["role"] == "user":
            text = "\n".join(b["text"] for b in blocks if b.get("type") == "text")
            if text:  # a row holding tool results is plumbing, not something the user wrote
                turns.append({"role": "user", "text": text, "at": row["created_at"]})
            continue
        if not turns or turns[-1]["role"] != "assistant":
            turns.append(
                {
                    "role": "assistant",
                    "text": "",
                    "at": row["created_at"],
                    "model": row["model"],
                    "activity": [],
                    "sources": [],
                    "usage": {"tokens_in": 0, "tokens_out": 0, "web_searches": 0, "cost_usd": 0.0},
                }
            )
        turn = turns[-1]
        for block in blocks:
            kind = block.get("type")
            if kind == "text":
                turn["text"] += block.get("text", "")
                for citation in block.get("citations") or []:
                    source = {"url": citation.get("url"), "title": citation.get("title")}
                    if source["url"] and source not in turn["sources"]:
                        turn["sources"].append(source)
            elif kind == "tool_use":
                turn["activity"].append(
                    {
                        "label": tools.LABELS.get(block.get("name"), block.get("name")),
                        "writes": block.get("name") in tools.WRITING,
                    }
                )
            elif kind == "server_tool_use" and block.get("name") == "web_search":
                query = (block.get("input") or {}).get("query")
                turn["activity"].append({"label": f"Recherche web : {query}", "writes": False})
        usage = turn["usage"]
        usage["tokens_in"] += (
            (row["input_tokens"] or 0)
            + (row["cache_read_tokens"] or 0)
            + (row["cache_write_tokens"] or 0)
        )
        usage["tokens_out"] += row["output_tokens"] or 0
        usage["web_searches"] += row["web_searches"] or 0
        usage["cost_usd"] = round(usage["cost_usd"] + float(dec(row["cost_usd"])), 4)
        turn["model"] = row["model"] or turn["model"]
    return {
        "id": conversation["id"],
        "title": conversation["title"],
        "model": conversation["model"],
        "updated_at": conversation["updated_at"],
        "turns": turns,
    }


def _store(
    conn: sqlite3.Connection,
    conversation_id: int,
    role: str,
    content: list[dict],
    model: str | None = None,
    usage: Usage | None = None,
) -> None:
    conn.execute(
        "INSERT INTO messages (conversation_id, role, content, model, input_tokens, output_tokens,"
        " cache_read_tokens, cache_write_tokens, web_searches, cost_usd, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            conversation_id,
            role,
            json.dumps(content, ensure_ascii=False),
            model,
            usage.input_tokens if usage else None,
            usage.output_tokens if usage else None,
            usage.cache_read_tokens if usage else None,
            usage.cache_write_tokens if usage else None,
            usage.web_searches if usage else None,
            str(cost(model, usage)) if usage and model else None,
            _now(),
        ),
    )
    conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (_now(), conversation_id))
    conn.commit()


def _close_interrupted_tools(conn: sqlite3.Connection, conversation_id: int) -> None:
    """A tool request left without its result (the application was closed mid-answer)
    would make every later call invalid: answer it with an error."""
    last = conn.execute(
        "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT 1",
        (conversation_id,),
    ).fetchone()
    if last is None or last["role"] != "assistant":
        return
    pending = [b for b in json.loads(last["content"]) if b.get("type") == "tool_use"]
    if pending:
        _store(
            conn,
            conversation_id,
            "user",
            [
                {
                    "type": "tool_result",
                    "tool_use_id": block["id"],
                    "content": "Interrompu avant d'avoir pu s'exécuter.",
                    "is_error": True,
                }
                for block in pending
            ],
        )


def _title(text: str) -> str:
    line = " ".join(text.split())
    return line if len(line) <= 60 else line[:57].rstrip() + "…"


# -- One user message, from question to answer ---------------------------------------


def send(
    conn: sqlite3.Connection,
    llm: LLM,
    api_key: str,
    conversation_id: int,
    text: str,
    web_search: bool = False,
    model: str | None = None,
    max_chars: int = MAX_MESSAGE_CHARS,
) -> Iterator[dict]:
    """Send one message and yield what happens, as events for the screen.

    Events: {"type": "text"}, {"type": "activity"}, {"type": "error"}, and a
    final {"type": "done"} carrying the conversation as it now stands.
    """
    conversation = conn.execute(
        "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
    ).fetchone()
    if conversation is None:
        yield {"type": "error", "message": "Discussion introuvable."}
        return
    text = text.strip()
    if not text:
        yield {"type": "error", "message": "Message vide."}
        return
    if len(text) > max_chars:
        yield {"type": "error", "message": "Message trop long."}
        return

    model = model if model in MODELS else conversation["model"]
    first = conn.execute(
        "SELECT 1 FROM messages WHERE conversation_id = ? LIMIT 1", (conversation_id,)
    ).fetchone()
    conn.execute(
        "UPDATE conversations SET model = ?, title = CASE WHEN ? THEN title ELSE ? END "
        "WHERE id = ?",
        (model, bool(first), _title(text), conversation_id),
    )
    _close_interrupted_tools(conn, conversation_id)
    _store(conn, conversation_id, "user", [{"type": "text", "text": text}])

    available = [*tools.TOOLS, WEB_SEARCH_TOOL] if web_search else list(tools.TOOLS)
    system = prompt.system(conn)

    try:
        for _ in range(MAX_STEPS):
            messages = [
                {"role": row["role"], "content": json.loads(row["content"])}
                for row in _history(conn, conversation_id)
            ]
            reply: Reply | None = None
            for piece in llm.stream(
                api_key=api_key,
                model=model,
                system=system,
                messages=messages,
                tools=available,
                max_tokens=MAX_TOKENS,
            ):
                if isinstance(piece, Reply):
                    reply = piece
                else:
                    yield {"type": "text", "text": piece}
            if reply is None:
                raise LLMError("service", "Réponse incomplète de l'API.")
            _store(conn, conversation_id, "assistant", reply.content, model, reply.usage)

            for block in reply.content:
                if block.get("type") == "server_tool_use" and block.get("name") == "web_search":
                    query = (block.get("input") or {}).get("query")
                    yield {"type": "activity", "label": f"Recherche web : {query}"}

            if reply.stop_reason == "tool_use":
                results = []
                for block in reply.content:
                    if block.get("type") != "tool_use":
                        continue
                    name = block.get("name", "")
                    yield {
                        "type": "activity",
                        "label": tools.LABELS.get(name, name),
                        "writes": name in tools.WRITING,
                    }
                    output, failed = tools.run(conn, name, block.get("input"))
                    result = {"type": "tool_result", "tool_use_id": block["id"], "content": output}
                    if failed:
                        result["is_error"] = True
                    results.append(result)
                _store(conn, conversation_id, "user", results)
                continue
            if reply.stop_reason == "pause_turn":
                continue  # a long server-side search: the same messages are sent again
            if reply.stop_reason == "max_tokens":
                yield {
                    "type": "error",
                    "message": "Réponse coupée : la limite de longueur est atteinte. "
                    "Demander la suite.",
                }
            break
        else:
            yield {
                "type": "error",
                "message": "L'assistant a enchaîné trop d'étapes sans conclure. Reformuler.",
            }
    except LLMError as exc:
        yield {"type": "error", "message": str(exc), "kind": exc.kind}

    yield {"type": "done", "conversation": view(conn, conversation_id), "month": month_usage(conn)}
