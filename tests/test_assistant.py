"""The assistant, without any network: a scripted model stands in for the API."""

import copy
import json
from datetime import date
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from cockpit import gold, journal, roadmap, rules, settings_file
from cockpit.api import create_app
from cockpit.assistant import chat, keys, prompt, tools
from cockpit.assistant.llm import MODELS, WEB_SEARCH_TOOL, LLMError, Reply, Usage, cost
from cockpit.importers import tr_csv
from tests.conftest import to_csv, tx

ACME = "XX0000000001"
CSV = {"content-type": "text/csv"}
KEY = "sk-ant-" + "x" * 40
SONNET, HAIKU = "claude-sonnet-5-5", "claude-haiku-4-5-20251001"


class FakeLLM:
    """Plays a script: each step is (pieces of text, final reply) or an error to raise."""

    def __init__(self, *script):
        self.script = list(script)
        self.calls: list[dict] = []

    def stream(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        pieces, reply = step
        yield from pieces
        yield reply


class MemoryKeyStore:
    def __init__(self, key=None):
        self.key = key

    def get(self):
        return self.key

    def set(self, key):
        self.key = key

    def delete(self):
        self.key = None


def text_reply(text, **usage):
    return ([text], Reply([{"type": "text", "text": text}], "end_turn", Usage(**usage)))


def tool_reply(name, arguments=None, tool_id="toolu_1", **usage):
    block = {"type": "tool_use", "id": tool_id, "name": name, "input": arguments or {}}
    return ([], Reply([block], "tool_use", Usage(**usage)))


@pytest.fixture
def loaded(conn, sample_csv):
    tr_csv.import_csv(conn, sample_csv)
    return conn


def events(conn, llm, conversation, text, **options):
    return list(chat.send(conn, llm, KEY, conversation, text, **options))


# -- Tools ------------------------------------------------------------------------


def read(conn, name, **arguments):
    output, failed = tools.run(conn, name, arguments)
    assert failed is False, output
    return json.loads(output)


def test_every_tool_has_a_runner_and_a_label():
    names = [tool["name"] for tool in tools.TOOLS]
    assert len(names) == len(set(names))
    assert set(names) == set(tools.LABELS)
    for tool in tools.TOOLS:
        assert tool["input_schema"]["type"] == "object" and tool["description"]
    assert {"ajouter_note_journal", "proposer_cible", "preparer_ticket"} == tools.WRITING


def test_portfolio_tool_shows_what_the_screens_show(loaded):
    data = read(loaded, "lire_portefeuille")
    assert [p["titre"] for p in data["positions"]] == ["Acme", "World Fund (Acc)", "Globex"]
    acme = data["positions"][0]
    assert (acme["compte"], acme["quantite"], acme["prix_de_revient"]) == ("CTO", 1.0, 25.0)
    assert acme["halalitude"]["statut"] == "non renseigné"
    assert data["base_des_poids"] == "prix de revient" and data["total"] == 65.0

    assert read(loaded, "lire_lignes_soldees")["bilan"]["count"] == 1
    assert read(loaded, "lire_frais_activite")["ordres_manuels_depuis_l_ouverture"] == 6
    assert read(loaded, "lire_halalitude")["titres"][0]["groupe"] == "détenu"


def test_gold_never_reaches_the_assistant(loaded):
    gold.add_lot(loaded, {"label": "LINGOT-SECRET", "grams": "123.456", "cost": "9876.54"})
    for tool in tools.TOOLS:
        if tool["name"] in tools.WRITING or tool["name"] == "lire_cours":
            continue
        output, _ = tools.run(loaded, tool["name"], {})
        assert "LINGOT-SECRET" not in output and "123.456" not in output and "9876" not in output
    system = " ".join(block["text"] for block in prompt.system(loaded))
    assert "LINGOT-SECRET" not in system


def test_transactions_tool_leaves_out_card_payments_and_bank_details(conn):
    rows = [
        tx("2025-01-02", "CUSTOMER_INPAYMENT", amount="100.00", counterparty_name="Jean Test",
           counterparty_iban="FR7600000000000000000000000", payment_reference="REF-PRIVEE"),
        tx("2025-01-06", "BUY", symbol=ACME, name="Acme", asset_class="STOCK", shares="1.0",
           price="20", amount="-20.00", fee="-1.00"),
        tx("2025-01-07", "CARD_TRANSACTION", name="Boulangerie", amount="-5.00"),
        tx("2025-02-10", "SELL", symbol=ACME, name="Acme", asset_class="STOCK", shares="-1.0",
           price="30", amount="30.00", fee="-1.00"),
    ]  # fmt: skip
    tr_csv.import_csv(conn, to_csv(rows))
    output, failed = tools.run(conn, "lire_transactions", {})
    assert failed is False
    for private in ("Boulangerie", "FR76", "Jean Test", "REF-PRIVEE", "CARD_TRANSACTION"):
        assert private not in output
    data = json.loads(output)
    assert (data["nombre_total"], [t["type"] for t in data["transactions"]]) == (
        3,
        ["SELL", "BUY", "CUSTOMER_INPAYMENT"],
    )

    only = read(conn, "lire_transactions", isin=ACME.lower(), type="buy", depuis="2025-01-01")
    assert [(t["date"], t["montant"]) for t in only["transactions"]] == [("2025-01-06", "-20.00")]
    assert read(conn, "lire_transactions", limite=1)["affichees"] == 1
    assert read(conn, "lire_transactions", limite=10_000)["affichees"] == 3  # capped, not refused


def test_price_tool_reads_the_local_history(loaded):
    for day, price in [("2025-06-27", "29"), ("2025-06-30", "30.5")]:
        loaded.execute(
            "INSERT INTO prices (isin, date, price, source) VALUES (?, ?, ?, 'fake')",
            (ACME, day, price),
        )
    data = read(loaded, "lire_cours", isin=ACME, jours=3650)
    assert (data["dernier_cours"], data["plus_bas"], data["plus_haut"]) == (30.5, 29.0, 30.5)
    assert data["variation_sur_la_periode"] == 0.0517 and len(data["cours"]) == 2
    output, failed = tools.run(loaded, "lire_cours", {"isin": "XX9999999999"})
    assert failed is True and "Aucun titre" in output


def test_sheets_tool_lists_then_reads(loaded, tmp_path, monkeypatch):
    folder = tmp_path / "fiches" / "2026"
    folder.mkdir(parents=True)
    figures = {"chiffre_affaires": {"2021": 100, "2025": 150}, "per": 20, "taux_distribution": 0.5,
               "chiffre_affaires_12m": 150, "resultat_net_12m": 30, "dette_nette": -5,
               "ebitda_12m": 40}  # fmt: skip
    (folder / "2026-10-05-acme.json").write_text(
        json.dumps({"nom": "Acme", "date": "2026-10-05", "chiffres": figures}), encoding="utf-8"
    )
    (folder / "2026-10-05-acme.md").write_text("# Acme\n\nTexte de la fiche.", encoding="utf-8")
    monkeypatch.setenv("COCKPIT_FICHES_DIR", str(tmp_path / "fiches"))

    listing = read(loaded, "lire_fiches")["fiches"]
    assert [(f["fiche"], f["entreprise"]) for f in listing] == [("2026-10-05-acme", "Acme")]
    assert listing[0]["note_sur_20"] is not None
    assert "Texte de la fiche" in read(loaded, "lire_fiches", fiche="2026-10-05-acme")["texte"]
    assert tools.run(loaded, "lire_fiches", {"fiche": "../../secret"})[1] is True


def test_the_two_things_the_assistant_can_write(loaded):
    note = read(loaded, "ajouter_note_journal", titre="Garder Acme", texte="Thèse inchangée.")
    assert note["auteur"] == "assistant"
    assert journal.entries(loaded)[0] == {
        "id": note["identifiant"],
        "decided_on": date.today().isoformat(),
        "title": "Garder Acme",
        "body": "Thèse inchangée.",
        "author": "assistant",
    }

    # Amount and entry price are the user's: the tool has no way to set them.
    read(loaded, "proposer_cible", nom="Initech", isin="xx0000000009", compte="PEA",
         these="Trois lignes.", montant=500, cours_entree=12)  # fmt: skip
    item = roadmap.items(loaded)["items"][0]
    assert (item["name"], item["status"], item["proposed_by"]) == ("Initech", "idee", "assistant")
    assert (item["amount"], item["entry_price"], item["account"]) == (None, None, "PEA")

    assert tools.run(loaded, "proposer_cible", {"nom": " "})[1] is True
    assert tools.run(loaded, "supprimer_tout", {})[1] is True
    assert tools.run(loaded, "lire_portefeuille", "pas un objet")[1] is True
    # No tool touches a rule, a status, a reason, a price or the key.
    assert not [t for t in tools.TOOLS if "regle" in t["name"] and t["name"] in tools.WRITING]


# -- The instructions ----------------------------------------------------------------


def test_system_prompt_carries_the_users_own_documents(conn):
    generic = prompt.system(conn, date(2026, 10, 2))
    assert len(generic) == 1 and "2026-10-02" in generic[0]["text"]
    assert "Halalitude" in generic[0]["text"] and "aucun ordre" in generic[0]["text"]

    prompt.save_document(conn, "Mes consignes", "Toujours des scénarios.")
    prompt.save_document(conn, "Mes consignes", "Toujours deux scénarios.")  # same title: replaced
    blocks = prompt.system(conn)
    assert len(blocks) == 2 and "Toujours deux scénarios." in blocks[1]["text"]
    assert len(prompt.documents(conn)) == 1
    with pytest.raises(ValueError):
        prompt.save_document(conn, "", "x")
    with pytest.raises(ValueError):
        prompt.save_document(conn, "Trop long", "x" * 60_001)


# -- Cost -----------------------------------------------------------------------------


def test_cost_estimate_follows_the_price_table():
    usage = Usage(input_tokens=1_000_000, output_tokens=100_000, cache_read_tokens=2_000_000,
                  cache_write_tokens=400_000, web_searches=3)  # fmt: skip
    # Sonnet 5.5: 2 + 1 + 0.40 + 1 dollars of tokens, plus three searches at one cent.
    assert cost(SONNET, usage) == D("4.43")
    assert cost(HAIKU, Usage(input_tokens=12_000, output_tokens=1_000)) == D("0.017")
    assert cost("modele-inconnu", usage) == 0


# -- The real client, against a canned HTTP answer ---------------------------------------


def sse(*events: dict) -> bytes:
    return "".join(
        f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events
    ).encode()


STREAMED = sse(
    {"type": "message_start", "message": {
        "id": "msg_1", "type": "message", "role": "assistant", "content": [], "model": SONNET,
        "stop_reason": None, "stop_sequence": None,
        "usage": {"input_tokens": 25, "output_tokens": 1, "cache_read_input_tokens": 900,
                  "cache_creation_input_tokens": 300}}},
    {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Je "}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "lis."}},
    {"type": "content_block_stop", "index": 0},
    {"type": "content_block_start", "index": 1, "content_block": {
        "type": "tool_use", "id": "toolu_7", "name": "lire_cours", "input": {}}},
    {"type": "content_block_delta", "index": 1,
     "delta": {"type": "input_json_delta", "partial_json": '{"isin": "XX00'}},
    {"type": "content_block_delta", "index": 1,
     "delta": {"type": "input_json_delta", "partial_json": '00000001"}'}},
    {"type": "content_block_stop", "index": 1},
    {"type": "message_delta", "delta": {"stop_reason": "tool_use", "stop_sequence": None},
     "usage": {"output_tokens": 42}},
    {"type": "message_stop"},
)  # fmt: skip


def test_the_real_client_reads_a_streamed_answer():
    import httpx2 as httpx

    from cockpit.assistant.llm import AnthropicLLM

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers["x-api-key"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=STREAMED)

    llm = AnthropicLLM(http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    pieces = list(
        llm.stream(
            api_key=KEY,
            model=SONNET,
            system=[{"type": "text", "text": "Consignes."}],
            messages=[{"role": "user", "content": [{"type": "text", "text": "Cours d'Acme ?"}]}],
            tools=[*tools.TOOLS, WEB_SEARCH_TOOL],
            max_tokens=4096,
        )
    )
    assert pieces[:2] == ["Je ", "lis."]
    reply = pieces[-1]
    assert reply.stop_reason == "tool_use"
    assert reply.content == [
        {"type": "text", "text": "Je lis."},
        {"type": "tool_use", "id": "toolu_7", "name": "lire_cours", "input": {"isin": ACME}},
    ]
    assert reply.usage == Usage(input_tokens=25, output_tokens=42, cache_read_tokens=900,
                                cache_write_tokens=300, web_searches=0)  # fmt: skip

    body = seen["body"]
    assert seen["key"] == KEY and body["model"] == SONNET and body["stream"] is True
    assert body["cache_control"] == {"type": "ephemeral"}
    assert body["tools"][-1] == WEB_SEARCH_TOOL and len(body["tools"]) == len(tools.TOOLS) + 1
    assert body["system"] == [{"type": "text", "text": "Consignes."}]


@pytest.mark.parametrize(
    ("status", "kind"),
    [(401, "cle"), (403, "cle"), (429, "quota"), (400, "requete"), (529, "service")],
)
def test_the_real_client_names_what_went_wrong(status, kind):
    import httpx2 as httpx

    from cockpit.assistant.llm import AnthropicLLM

    def handler(request: httpx.Request) -> httpx.Response:
        error = {"type": "error", "error": {"type": "x", "message": "web search is not enabled"}}
        return httpx.Response(status, json=error)

    llm = AnthropicLLM(http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    llm.retries = 0
    with pytest.raises(LLMError) as error:
        list(llm.stream(api_key=KEY, model=SONNET, system=[], messages=[], tools=[], max_tokens=10))
    assert error.value.kind == kind
    if status == 400:
        assert "web search is not enabled" in str(error.value)


# -- A conversation --------------------------------------------------------------------


def test_a_question_goes_through_a_tool_and_comes_back(loaded):
    llm = FakeLLM(
        tool_reply("lire_portefeuille", input_tokens=900, output_tokens=40),
        text_reply(
            "Trois lignes ouvertes.", input_tokens=60, output_tokens=20, cache_read_tokens=900
        ),  # fmt: skip
    )
    conversation = chat.create(loaded)
    out = events(loaded, llm, conversation, "  Combien de lignes ai-je ?  ")

    assert [e["type"] for e in out] == ["activity", "text", "done"]
    assert out[0] == {"type": "activity", "label": "Lecture du portefeuille", "writes": False}
    assert out[1]["text"] == "Trois lignes ouvertes."

    # Second call: the tool request and its result went back, unchanged.
    second = llm.calls[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    assert second[1]["content"][0]["name"] == "lire_portefeuille"
    result = second[2]["content"][0]
    assert result["type"] == "tool_result" and result["tool_use_id"] == "toolu_1"
    assert "Acme" in result["content"] and "is_error" not in result
    assert llm.calls[0]["api_key"] == KEY and llm.calls[0]["model"] == SONNET
    assert WEB_SEARCH_TOOL not in llm.calls[0]["tools"]  # off unless asked

    shown = out[-1]["conversation"]
    assert shown["title"] == "Combien de lignes ai-je ?"
    assert [t["role"] for t in shown["turns"]] == ["user", "assistant"]  # one answer, two calls
    answer = shown["turns"][1]
    assert answer["text"] == "Trois lignes ouvertes."
    assert answer["activity"] == [{"label": "Lecture du portefeuille", "writes": False}]
    assert (answer["usage"]["tokens_in"], answer["usage"]["tokens_out"]) == (1860, 60)
    expected = cost(SONNET, Usage(900, 40)) + cost(SONNET, Usage(60, 20, 900))
    assert answer["usage"]["cost_usd"] == pytest.approx(float(expected), abs=1e-4)
    assert out[-1]["month"]["calls"] == 2 and out[-1]["month"]["budget_eur"] == 10.0


def test_a_conversation_resumes_where_it_stopped(loaded):
    conversation = chat.create(loaded)
    events(loaded, FakeLLM(text_reply("Bonjour.")), conversation, "Bonjour")
    llm = FakeLLM(text_reply("Oui."))
    events(loaded, llm, conversation, "Tu te souviens ?", model=HAIKU)
    sent = llm.calls[0]["messages"]
    assert [m["content"][0]["text"] for m in sent] == ["Bonjour", "Bonjour.", "Tu te souviens ?"]
    assert llm.calls[0]["model"] == HAIKU
    shown = chat.view(loaded, conversation)
    assert (shown["model"], shown["title"], len(shown["turns"])) == (HAIKU, "Bonjour", 4)
    assert [c["id"] for c in chat.listing(loaded)] == [conversation]


def test_web_search_is_only_offered_when_switched_on(loaded):
    searched = Reply(
        [
            {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search",
             "input": {"query": "résultats Acme"}},
            {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_1",
             "content": [{"type": "web_search_result", "url": "https://exemple.test/acme",
                          "title": "Acme", "encrypted_content": "chiffré"}]},
            {"type": "text", "text": "Acme a publié.",
             "citations": [{"type": "web_search_result_location", "title": "Acme",
                            "url": "https://exemple.test/acme", "cited_text": "…"}]},
        ],
        "end_turn",
        Usage(input_tokens=100, output_tokens=10, web_searches=1),
    )  # fmt: skip
    llm = FakeLLM((["Acme a publié."], searched), text_reply("Merci."))
    conversation = chat.create(loaded)
    out = events(loaded, llm, conversation, "Des nouvelles d'Acme ?", web_search=True)
    assert llm.calls[0]["tools"][-1] == WEB_SEARCH_TOOL
    assert {"type": "activity", "label": "Recherche web : résultats Acme"} in out

    answer = out[-1]["conversation"]["turns"][1]
    assert answer["sources"] == [{"url": "https://exemple.test/acme", "title": "Acme"}]
    assert answer["usage"]["web_searches"] == 1
    assert answer["usage"]["cost_usd"] == pytest.approx(0.0103, abs=1e-4)

    # The search results go back exactly as received, or the API refuses the next call.
    events(loaded, llm, conversation, "Merci")
    assert llm.calls[1]["messages"][1]["content"] == searched.content
    assert WEB_SEARCH_TOOL not in llm.calls[1]["tools"]


def test_a_failed_tool_is_reported_to_the_model_not_hidden(loaded):
    llm = FakeLLM(tool_reply("lire_cours", {"isin": "XX9999999999"}), text_reply("Inconnu."))
    events(loaded, llm, chat.create(loaded), "Cours de X ?")
    result = llm.calls[1]["messages"][2]["content"][0]
    assert result["is_error"] is True and "Aucun titre" in result["content"]


def test_an_api_error_leaves_a_usable_conversation(loaded):
    conversation = chat.create(loaded)
    out = events(loaded, FakeLLM(LLMError("cle", "La clé d'API a été refusée.")), conversation, "?")
    assert [e["type"] for e in out] == ["error", "done"]
    assert (out[0]["kind"], out[0]["message"]) == ("cle", "La clé d'API a été refusée.")

    llm = FakeLLM(text_reply("Me revoilà."))
    out = events(loaded, llm, conversation, "Encore là ?")
    assert out[-1]["conversation"]["turns"][-1]["text"] == "Me revoilà."
    assert [m["role"] for m in llm.calls[0]["messages"]] == ["user", "user"]


def test_a_tool_request_cut_short_is_closed_before_the_next_message(loaded):
    conversation = chat.create(loaded)
    chat._store(loaded, conversation, "user", [{"type": "text", "text": "Question"}])
    chat._store(loaded, conversation, "assistant",
                [{"type": "tool_use", "id": "toolu_9", "name": "lire_portefeuille", "input": {}}],
                SONNET, Usage())  # fmt: skip
    llm = FakeLLM(text_reply("Reprenons."))
    events(loaded, llm, conversation, "Tu es là ?")
    closed = llm.calls[0]["messages"][2]["content"][0]
    assert (closed["tool_use_id"], closed["is_error"]) == ("toolu_9", True)


def test_pause_then_too_many_steps(loaded):
    paused = ([], Reply([{"type": "text", "text": "…"}], "pause_turn", Usage()))
    out = events(loaded, FakeLLM(paused, text_reply("Fini.")), chat.create(loaded), "Cherche")
    assert out[-1]["conversation"]["turns"][-1]["text"] == "…Fini."

    endless = FakeLLM(*[tool_reply("lire_journal", tool_id=f"t{i}") for i in range(chat.MAX_STEPS)])
    out = events(loaded, endless, chat.create(loaded), "Boucle")
    assert out[-2]["type"] == "error" and "trop d'étapes" in out[-2]["message"]
    assert len(endless.calls) == chat.MAX_STEPS


def test_empty_or_unknown_conversations_are_refused(loaded):
    assert events(loaded, FakeLLM(), 999, "x")[0]["message"] == "Discussion introuvable."
    assert events(loaded, FakeLLM(), chat.create(loaded), "   ")[0]["message"] == "Message vide."


def test_month_usage_against_the_budget(loaded):
    conversation = chat.create(loaded)
    events(loaded, FakeLLM(text_reply("a", input_tokens=1_000_000)), conversation, "x")
    usage = chat.month_usage(loaded)
    assert (usage["cost_usd"], usage["cost_eur"], usage["share_of_budget"]) == (2.0, None, 0.2)
    # With an exchange rate in the base, the cost is shown in euros.
    loaded.execute(
        "INSERT INTO fx_rates (currency, date, rate) VALUES ('USD', '2026-10-02', '1.25')"
    )
    assert chat.month_usage(loaded)["cost_eur"] == 1.6
    chat.set_budget(loaded, "4")
    assert chat.month_usage(loaded)["share_of_budget"] == 0.4
    with pytest.raises(ValueError):
        chat.set_budget(loaded, 0)
    with pytest.raises(ValueError):
        chat.set_default_model(loaded, "gpt")


# -- The key ---------------------------------------------------------------------------


def test_key_format_and_where_it_comes_from(monkeypatch):
    assert keys.check_format(f"  {KEY}\n") == KEY
    for bad in ("", "sk-ant-court", "pas une clé du tout, vraiment pas", "sk-ant-" + "x y" * 20):
        with pytest.raises(ValueError):
            keys.check_format(bad)
    monkeypatch.delenv(keys.ENV_VAR, raising=False)
    assert keys.resolve(MemoryKeyStore()) == (None, None)
    monkeypatch.setenv(keys.ENV_VAR, "sk-ant-env")
    assert keys.resolve(MemoryKeyStore()) == ("sk-ant-env", "environnement")
    assert keys.resolve(MemoryKeyStore(KEY)) == (KEY, "coffre")  # the stored key wins


# -- API -------------------------------------------------------------------------------


@pytest.fixture
def api(tmp_path, sample_csv, monkeypatch):
    monkeypatch.delenv(keys.ENV_VAR, raising=False)
    llm, store = FakeLLM(), MemoryKeyStore()
    client = TestClient(create_app(tmp_path / "assistant.db", llm=llm, key_store=store))
    client.post("/api/import/csv", content=sample_csv.encode(), headers=CSV)
    return client, llm, store


def stream(client, conversation, **body):
    response = client.post(f"/api/assistant/conversations/{conversation}/messages", json=body)
    assert response.status_code == 200 and response.headers["content-type"].startswith(
        "text/event-stream"
    )
    return [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]


def test_the_key_goes_in_and_never_comes_out(api):
    client, _, store = api
    status = client.get("/api/assistant/status").json()
    assert (status["configured"], status["key_source"], status["default_model"]) == (
        False,
        None,
        SONNET,
    )
    assert [m["id"] for m in status["models"]] == list(MODELS)
    conversation = client.post("/api/assistant/conversations", json={}).json()["id"]
    refused = client.post(
        f"/api/assistant/conversations/{conversation}/messages", json={"text": "?"}
    )
    assert refused.status_code == 400

    assert client.put("/api/assistant/key", json={"key": "motdepasse"}).status_code == 400
    saved = client.put("/api/assistant/key", json={"key": KEY})
    assert saved.json()["configured"] is True and saved.json()["key_source"] == "coffre"
    assert store.key == KEY
    for path in ("/api/assistant/status", "/api/settings/export", "/api/assistant/context"):
        assert KEY not in client.get(path).text
    assert KEY not in saved.text
    assert client.delete("/api/assistant/key").json()["configured"] is False and store.key is None


def test_a_conversation_over_the_api(api):
    client, llm, store = api
    store.key = KEY
    llm.script = [tool_reply("lire_regles"), text_reply("Aucune règle n'a de valeur.")]
    conversation = client.post("/api/assistant/conversations", json={"model": HAIKU}).json()
    assert conversation["model"] == HAIKU and conversation["turns"] == []

    out = stream(client, conversation["id"], text="Où en sont mes règles ?")
    assert [e["type"] for e in out] == ["activity", "text", "done"]
    assert llm.calls[0]["api_key"] == KEY

    stored = client.get(f"/api/assistant/conversations/{conversation['id']}").json()
    assert stored["turns"][1]["text"] == "Aucune règle n'a de valeur."
    assert client.get("/api/assistant/conversations").json()[0]["messages"] == 4
    assert client.get("/api/assistant/status").json()["month"]["calls"] == 2

    assert client.delete(f"/api/assistant/conversations/{conversation['id']}").status_code == 200
    assert client.get(f"/api/assistant/conversations/{conversation['id']}").status_code == 404
    assert client.get("/api/assistant/conversations").json() == []


def test_assistant_settings_and_documents_over_the_api(api):
    client, _, _ = api
    changed = client.put("/api/assistant/settings", json={"model": HAIKU, "budget_eur": "7,5"})
    assert (changed.json()["default_model"], changed.json()["month"]["budget_eur"]) == (HAIKU, 7.5)
    assert client.put("/api/assistant/settings", json={"model": "gpt"}).status_code == 400

    document = client.put("/api/assistant/context", json={"title": "Consignes", "content": "A"})
    assert client.get("/api/assistant/context").json()[0]["content"] == "A"
    assert (
        client.put("/api/assistant/context", json={"title": "", "content": "A"}).status_code == 400
    )
    assert client.delete(f"/api/assistant/context/{document.json()['id']}").status_code == 200
    assert client.delete(f"/api/assistant/context/{document.json()['id']}").status_code == 404


def test_journal_over_the_api(api):
    client, _, _ = api
    entry = client.post(
        "/api/journal", json={"title": "Vendre X", "body": "Motif.", "decided_on": "2026-10-02"}
    )
    assert entry.status_code == 201
    listed = client.get("/api/journal").json()
    assert (listed[0]["title"], listed[0]["author"], listed[0]["decided_on"]) == (
        "Vendre X",
        "moi",
        "2026-10-02",
    )
    assert (
        client.put(f"/api/journal/{entry.json()['id']}", json={"title": "Garder X"}).status_code
        == 200
    )
    assert client.get("/api/journal").json()[0]["title"] == "Garder X"
    assert client.post("/api/journal", json={"title": " "}).status_code == 400
    assert client.put("/api/journal/999", json={"title": "x"}).status_code == 404
    assert client.delete(f"/api/journal/{entry.json()['id']}").status_code == 200
    assert client.get("/api/journal").json() == []


def test_settings_file_carries_the_assistants_documents(loaded, tmp_path):
    from cockpit import db

    prompt.save_document(loaded, "Consignes", "Halalitude d'abord.")
    rules.set_rule(loaded, "frais_trimestre", 4, "2025-01-01")
    exported = settings_file.export(loaded)
    assert exported["assistant_context"] == [
        {"title": "Consignes", "content": "Halalitude d'abord."}
    ]

    other = db.connect(tmp_path / "other.db")
    prompt.save_document(other, "Consignes", "Ma version, écrite ici.")
    done = settings_file.load(other, exported)
    assert (done["context_added"], done["context_present"]) == (0, 1)
    assert prompt.documents(other)[0]["content"] == "Ma version, écrite ici."  # never overwritten
    other.close()
