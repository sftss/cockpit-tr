"""What the assistant can read and write, as tools.

Reading goes through the same functions as the screens, so the assistant sees
the figures the user sees. Three things are deliberately out of its reach:

* physical gold: no tool returns it, by the user's choice;
* bank details and card payments: the transaction tool leaves out card
  spending, counterparties, IBANs and payment references;
* everything that is a decision of the user: rule values, compliance
  statuses, reasons, prices, the API key.

Writing is limited to two things, both marked as coming from the assistant: a
note in the decision journal and a proposed target on the roadmap.
"""

from __future__ import annotations

import json
import sqlite3
from decimal import Decimal

from .. import compliance, config, journal, roadmap, store
from ..money import dec
from ..portfolio import CARD

MAX_TRANSACTIONS = 200
MAX_PRICE_POINTS = 60

TOOLS: list[dict] = [
    {
        "name": "lire_portefeuille",
        "description": (
            "Positions ouvertes du portefeuille Trade Republic, par compte (CTO et PEA) : "
            "quantité, prix de revient, dernier cours, valeur, résultat latent, poids et statut "
            "Halalitude de chaque ligne, plus les totaux par compte. À appeler pour toute "
            "question sur ce qui est détenu aujourd'hui. L'or physique n'y figure pas."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "lire_lignes_soldees",
        "description": (
            "Lignes entièrement revendues : montants achetés et vendus, frais, résultat net, "
            "durée de détention, et le bilan d'ensemble."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "lire_frais_activite",
        "description": (
            "Frais payés depuis l'ouverture (ordres, rechargements), capital apporté, dividendes, "
            "et l'activité par trimestre : ordres manuels, exécutions gratuites, frais."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "lire_regles",
        "description": (
            "Règles que l'utilisateur s'est fixées, leurs valeurs en vigueur, les compteurs du "
            "trimestre en cours face à ces règles, et les transactions qui s'en écartent avec le "
            "motif écrit par l'utilisateur. À appeler avant de parler d'un ordre envisagé."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "lire_halalitude",
        "description": (
            "Statut Halalitude (halal, douteux, haram) de chaque titre détenu ou visé, tel que "
            "l'utilisateur l'a relevé à la main dans ses screeners, avec la date du relevé et s'il "
            "est à revérifier. L'application ne vérifie rien elle-même."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "lire_feuille_de_route",
        "description": (
            "Cibles de la feuille de route : titre, compte, montant prévu, condition d'entrée, "
            "thèse, statut, dernier cours relevé et statut Halalitude."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "lire_transactions",
        "description": (
            "Transactions importées de l'export Trade Republic : achats, ventes, dividendes, "
            "versements, opérations sur titres. Filtrer autant que possible. Les paiements par "
            "carte et les coordonnées bancaires n'y figurent pas."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "isin": {"type": "string", "description": "Code ISIN du titre."},
                "type": {
                    "type": "string",
                    "description": "Type exact : BUY, SELL, DIVIDEND, CUSTOMER_INPAYMENT, SPLIT…",
                },
                "depuis": {"type": "string", "description": "Date de début, AAAA-MM-JJ."},
                "jusqua": {"type": "string", "description": "Date de fin, AAAA-MM-JJ."},
                "limite": {
                    "type": "integer",
                    "description": f"Nombre de lignes, les plus récentes d'abord (au plus "
                    f"{MAX_TRANSACTIONS}).",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "lire_cours",
        "description": (
            "Dernier cours connu d'un titre et son historique en euros sur une période, tirés de "
            "la base locale (source publique, différée selon les places). Donne aussi le plus "
            "haut, le plus bas et la variation sur la période."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "isin": {"type": "string", "description": "Code ISIN du titre."},
                "jours": {
                    "type": "integer",
                    "description": "Profondeur en jours calendaires (30 par défaut).",
                },
            },
            "required": ["isin"],
            "additionalProperties": False,
        },
    },
    {
        "name": "lire_fiches",
        "description": (
            "Fiches du jour : analyses d'entreprises notées sur 20 par un barème fixe. Sans "
            "argument, la liste des fiches (date, entreprise, note). Avec « fiche », le texte "
            "complet de cette fiche."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fiche": {
                    "type": "string",
                    "description": "Identifiant donné par la liste, par exemple "
                    "2026-10-02-legrand.",
                }
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "lire_veille",
        "description": (
            "Veille hebdomadaire : faits publics datés et sourcés de la semaine (résultats, "
            "annonces, prochains rendez-vous) pour une liste d'entreprises, plus un court contexte "
            "macro. Sans argument, la dernière veille, limitée aux lignes détenues et aux cibles "
            "de la feuille de route. Ce sont des faits relevés par une IA : citer la source, ne "
            "pas en tirer de consigne."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "semaine": {
                    "type": "string",
                    "description": "Semaine voulue, par exemple 2026-W40. Par défaut la dernière.",
                },
                "tous_les_titres": {
                    "type": "boolean",
                    "description": "Vrai pour lire aussi les titres ni détenus ni ciblés.",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "lire_journal",
        "description": (
            "Journal de décisions : ce que l'utilisateur a décidé, quand et pourquoi, et les "
            "notes que l'assistant y a ajoutées."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "ajouter_note_journal",
        "description": (
            "Ajoute une note au journal de décisions, marquée comme venant de l'assistant. À "
            "n'utiliser que si l'utilisateur le demande ou l'accepte ; dire ensuite ce qui a été "
            "noté."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "titre": {"type": "string", "description": "Titre court de la note."},
                "texte": {"type": "string", "description": "Contenu : la décision et son motif."},
            },
            "required": ["titre", "texte"],
            "additionalProperties": False,
        },
    },
    {
        "name": "proposer_cible",
        "description": (
            "Propose une cible sur la feuille de route, au statut « idée » et marquée comme "
            "proposée par l'assistant. Ni montant ni cours d'entrée : ils reviennent à "
            "l'utilisateur. À n'utiliser que s'il le demande ou l'accepte."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nom": {"type": "string", "description": "Nom du titre."},
                "isin": {
                    "type": "string",
                    "description": "Code ISIN, s'il est connu avec certitude.",
                },
                "compte": {"type": "string", "enum": ["CTO", "PEA"]},
                "condition_entree": {
                    "type": "string",
                    "description": "Ce qui devrait être vrai avant d'acheter, Halalitude comprise.",
                },
                "these": {"type": "string", "description": "La thèse, en trois lignes au plus."},
            },
            "required": ["nom"],
            "additionalProperties": False,
        },
    },
]

WRITING = {"ajouter_note_journal", "proposer_cible"}

LABELS = {
    "lire_portefeuille": "Lecture du portefeuille",
    "lire_lignes_soldees": "Lecture des lignes soldées",
    "lire_frais_activite": "Lecture des frais et de l'activité",
    "lire_regles": "Lecture des règles et des écarts",
    "lire_halalitude": "Lecture des statuts Halalitude",
    "lire_feuille_de_route": "Lecture de la feuille de route",
    "lire_transactions": "Lecture des transactions",
    "lire_cours": "Lecture des cours",
    "lire_fiches": "Lecture des fiches du jour",
    "lire_veille": "Lecture de la veille hebdomadaire",
    "lire_journal": "Lecture du journal",
    "ajouter_note_journal": "Note ajoutée au journal",
    "proposer_cible": "Cible proposée sur la feuille de route",
}


class ToolError(Exception):
    """The request of the model cannot be served; the message goes back to it."""


def _halalitude(view: dict | None) -> dict | None:
    if view is None:
        return None
    return {
        "statut": compliance.STATUSES.get(view["status"], "non renseigné").lower()
        if view["status"]
        else "non renseigné",
        "releve_le": view["checked_on"],
        "a_reverifier": view["state"] == "a_reverifier",
        "note": view["note"],
    }


def _portfolio(conn: sqlite3.Connection, _: dict) -> dict:
    report = store.current_report(conn)
    return {
        "perimetre": "Portefeuille Trade Republic (CTO et PEA). L'or physique n'est pas inclus.",
        "periode_des_transactions": report["period"],
        "comptes": [
            {
                "compte": a["account"],
                "lignes": a["open_lines"],
                "capital_net_engage": a["net_invested"],
                "prix_de_revient": a["open_cost"],
                "valeur": a["value"],
                "resultat_latent": a["latent"],
                "performance": a["performance"],
                "especes_estimees": a["cash_estimate"],
            }
            for a in report["accounts"]
        ],
        "base_des_poids": "valeur" if report["total"]["basis"] == "value" else "prix de revient",
        "total": report["total"]["amount"],
        "positions": [
            {
                "compte": p["account"],
                "titre": p["name"],
                "isin": p["isin"],
                "quantite": p["shares"],
                "prix_de_revient": p["cost"],
                "cours": p["price"],
                "date_du_cours": p["price_date"],
                "valeur": p["value"],
                "resultat_latent": p["latent"],
                "resultat_latent_pct": p["latent_pct"],
                "poids_dans_le_compte": p["weight"],
                "poids_dans_le_portefeuille": p["weight_total"],
                "premier_achat": p["first_buy"],
                "halalitude": _halalitude(p["halalitude"]),
            }
            for p in report["positions"]
        ],
    }


def _closed(conn: sqlite3.Connection, _: dict) -> dict:
    report = store.current_report(conn)
    return {"bilan": report["closed_summary"], "lignes": report["closed"]}


def _fees(conn: sqlite3.Connection, _: dict) -> dict:
    report = store.current_report(conn)
    return {
        "frais": report["fees"],
        "flux": report["flows"],
        "par_trimestre": report["quarters"],
        "ordres_manuels_depuis_l_ouverture": report["manual_orders"],
        "definition": "Un ordre manuel est un achat ou une vente qui a payé des frais.",
    }


def _rules(conn: sqlite3.Connection, _: dict) -> dict:
    state = store.rules_state(conn)
    kinds = {k["kind"]: k for k in state["kinds"]}
    return {
        "principe": "Une règle ne bloque rien : un écart demande un motif écrit.",
        "trimestre": state["quarter"],
        "compteurs_du_trimestre": state["current"],
        "valeurs_en_vigueur": [
            {
                "regle": kinds[r["kind"]]["label"],
                "valeur": r["value"],
                "unite": kinds[r["kind"]]["unit"],
                "compte": r["account"],
                "depuis": r["valid_from"],
                "note": r["note"],
            }
            for r in state["rules"]
            if r["valid_to"] is None
        ],
        "ecarts": state["deviations"][:30],
        "ecarts_sans_motif": state["pending"],
    }


def _compliance(conn: sqlite3.Connection, _: dict) -> dict:
    view = compliance.overview(conn, store.held_names(conn))
    groups = {"detenu": "détenu", "cible": "cible de la feuille de route", "autre": "autre"}
    return {
        "validite_en_jours": view["validity_days"],
        "titres": [
            {
                "titre": item["name"],
                "isin": item["isin"],
                "groupe": groups[item["group"]],
                **_halalitude(item),
            }
            for item in view["items"]
        ],
    }


def _roadmap(conn: sqlite3.Connection, _: dict) -> dict:
    data = roadmap.items(conn)
    return {
        "cibles": [
            {
                "nom": item["name"],
                "isin": item["isin"],
                "compte": item["account"],
                "montant_prevu": item["amount"],
                "condition_entree": item["entry_condition"],
                "cours_entree": item["entry_price"],
                "these": item["thesis"],
                "statut": data["statuses"][item["status"]],
                "dernier_cours": item["last_price"],
                "cours_releve_le": item["last_price_at"],
                "cours_entree_atteint": item["reached"],
                "proposee_par": item["proposed_by"],
                "halalitude": _halalitude(item["halalitude"]),
            }
            for item in data["items"]
        ]
    }


def _transactions(conn: sqlite3.Connection, args: dict) -> dict:
    clauses = [f"type NOT IN ({', '.join('?' for _ in CARD)})"]
    values: list[object] = sorted(CARD)
    for column, key, operator in (
        ("isin", "isin", "="),
        ("type", "type", "="),
        ("date", "depuis", ">="),
        ("date", "jusqua", "<="),
    ):
        if args.get(key):
            clauses.append(f"{column} {operator} ?")
            values.append(str(args[key]).strip().upper() if key in ("isin", "type") else args[key])
    limit = max(1, min(int(args.get("limite") or 50), MAX_TRANSACTIONS))
    where = " AND ".join(clauses)
    total = conn.execute(f"SELECT COUNT(*) FROM transactions WHERE {where}", values).fetchone()[0]
    rows = conn.execute(
        "SELECT date, account_id, type, name, isin, shares, price, amount, fee, tax "
        f"FROM transactions WHERE {where} ORDER BY datetime DESC LIMIT ?",
        [*values, limit],
    ).fetchall()
    return {
        "nombre_total": total,
        "affichees": len(rows),
        "ordre": "de la plus récente à la plus ancienne",
        "transactions": [
            {
                "date": row["date"],
                "compte": row["account_id"],
                "type": row["type"],
                "titre": row["name"] or None,
                "isin": row["isin"] or None,
                "quantite": row["shares"] or None,
                "prix": row["price"] or None,
                "montant": row["amount"] or None,
                "frais": row["fee"] or None,
                "taxe": row["tax"] or None,
            }
            for row in rows
        ],
    }


def _prices(conn: sqlite3.Connection, args: dict) -> dict:
    isin = str(args.get("isin") or "").strip().upper()
    instrument = conn.execute("SELECT name FROM instruments WHERE isin = ?", (isin,)).fetchone()
    if instrument is None:
        raise ToolError(f"Aucun titre connu de la base avec l'ISIN {isin}.")
    days = max(1, min(int(args.get("jours") or 30), 3650))
    rows = conn.execute(
        "SELECT date, price, source FROM prices WHERE isin = ? AND date >= date('now', ?) "
        "ORDER BY date",
        (isin, f"-{days} days"),
    ).fetchall()
    if not rows:
        return {"titre": instrument["name"], "isin": isin, "cours": [], "note": "Aucun cours."}
    values = [dec(row["price"]) for row in rows]
    step = max(1, len(rows) // MAX_PRICE_POINTS)
    sampled = [rows[i] for i in range(0, len(rows), step)]
    if sampled[-1]["date"] != rows[-1]["date"]:
        sampled.append(rows[-1])

    def euros(value: Decimal) -> float:
        return float(value.quantize(Decimal("0.0001")))

    quote = store.quotes(conn).get(isin)
    return {
        "titre": instrument["name"],
        "isin": isin,
        "devise": "EUR",
        "dernier_cours": euros(values[-1]),
        "date_du_dernier_cours": rows[-1]["date"],
        "cotation_en_direct": quote
        and {
            "prix": quote["price"],
            "devise": quote["currency"],
            "prix_en_euros": quote["price_eur"],
            "place": quote["exchange"],
            "differe_en_minutes": quote["delay_minutes"],
            "relevee_le": quote["fetched_at"],
        },
        "periode": {"du": rows[0]["date"], "au": rows[-1]["date"]},
        "plus_haut": euros(max(values)),
        "plus_bas": euros(min(values)),
        "variation_sur_la_periode": float((values[-1] / values[0] - 1).quantize(Decimal("0.0001")))
        if values[0] > 0
        else None,
        "cours": [{"date": row["date"], "prix": euros(dec(row["price"]))} for row in sampled],
        "avertissement": "Historique ajusté des fractionnements ; source publique non officielle.",
    }


def _sheets(conn: sqlite3.Connection, args: dict) -> dict:
    folder = config.fiches_dir()
    if folder is None:
        return {"fiches": [], "note": "Aucun dossier de fiches sur cet ordinateur."}
    files = sorted(folder.glob("20*/*.json"), reverse=True)
    wanted = str(args.get("fiche") or "").strip()
    if wanted:
        match = next((f for f in files if f.stem == wanted), None)
        if match is None:
            raise ToolError(f"Aucune fiche nommée {wanted}. Appeler l'outil sans argument.")
        text = match.with_suffix(".md")
        return {
            "fiche": match.stem,
            "texte": text.read_text(encoding="utf-8") if text.is_file() else None,
            "rappel": "Une note trie des candidats : ni prédiction, ni consigne d'achat, et elle "
            "ne dit rien de la Halalitude.",
        }
    from ..scoring import score  # the grid itself: same figures, same score

    listing = []
    for file in files:
        try:
            sheet = json.loads(file.read_text(encoding="utf-8"))
            result = score(sheet.get("chiffres", sheet))
        except (ValueError, OSError, TypeError, KeyError):
            continue
        listing.append(
            {
                "fiche": file.stem,
                "date": sheet.get("date"),
                "entreprise": sheet.get("nom"),
                "note_sur_20": result["note"],
                "libelle": result["libelle"],
            }
        )
    return {"fiches": listing}


def _watch(conn: sqlite3.Connection, args: dict) -> dict:
    view = store.watch(conn, config.veilles_dir(), str(args.get("semaine") or "").strip() or None)
    report = view["report"]
    if report is None:
        return {"veille": None, "note": "Aucune veille hebdomadaire sur cet ordinateur."}
    everything = bool(args.get("tous_les_titres"))
    followed = {"ligne": "ligne détenue", "cible": "cible de la feuille de route"}
    titles = [
        {
            "nom": title["nom"],
            "isin": title["isin"],
            "suivi": followed.get(title["suivi"]),
            "faits": title["faits"],
            "prochain_rendez_vous": title.get("prochain_rendez_vous"),
            "a_regarder": title.get("a_regarder"),
        }
        for title in report["titres"]
        if everything or title["suivi"]
    ]
    return {
        "semaine": report["semaine"],
        "du": report["du"],
        "au": report["au"],
        "semaines_disponibles": [week["semaine"] for week in view["weeks"]],
        "macro": report["macro"],
        "titres": titles,
        "autres_titres_avec_du_nouveau": []
        if everything
        else [t["nom"] for t in report["titres"] if not t["suivi"] and t["faits"]],
        "lignes_et_cibles_hors_veille": view["uncovered"],
        "rappel": "Faits relevés par une IA dans des sources publiques : ni prédiction, ni "
        "consigne d'achat ou de vente, et rien sur la Halalitude.",
    }


def _journal(conn: sqlite3.Connection, _: dict) -> dict:
    return {
        "notes": [
            {
                "date": e["decided_on"],
                "titre": e["title"],
                "texte": e["body"],
                "auteur": "utilisateur" if e["author"] == "moi" else "assistant",
            }
            for e in journal.entries(conn, limit=100)
        ]
    }


def _add_note(conn: sqlite3.Connection, args: dict) -> dict:
    try:
        entry_id = journal.add(
            conn, {"title": args.get("titre"), "body": args.get("texte")}, author="assistant"
        )
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    return {"enregistre": True, "identifiant": entry_id, "auteur": "assistant"}


def _propose_target(conn: sqlite3.Connection, args: dict) -> dict:
    try:
        item_id = roadmap.create(
            conn,
            {
                "name": args.get("nom"),
                "isin": args.get("isin"),
                "account": args.get("compte"),
                "entry_condition": args.get("condition_entree"),
                "thesis": args.get("these"),
                "status": "idee",
            },
            proposed_by="assistant",
        )
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    return {
        "enregistre": True,
        "identifiant": item_id,
        "statut": "idée",
        "rappel": "Ni montant ni cours d'entrée : à l'utilisateur de les fixer, après "
        "vérification de la Halalitude.",
    }


_RUNNERS = {
    "lire_portefeuille": _portfolio,
    "lire_lignes_soldees": _closed,
    "lire_frais_activite": _fees,
    "lire_regles": _rules,
    "lire_halalitude": _compliance,
    "lire_feuille_de_route": _roadmap,
    "lire_transactions": _transactions,
    "lire_cours": _prices,
    "lire_fiches": _sheets,
    "lire_veille": _watch,
    "lire_journal": _journal,
    "ajouter_note_journal": _add_note,
    "proposer_cible": _propose_target,
}


def run(conn: sqlite3.Connection, name: str, arguments: object) -> tuple[str, bool]:
    """Run one tool. Returns the text given back to the model, and whether it failed."""
    runner = _RUNNERS.get(name)
    if runner is None:
        return f"Outil inconnu : {name}.", True
    if not isinstance(arguments, dict):
        return "Arguments illisibles.", True
    try:
        result = runner(conn, arguments)
    except ToolError as exc:
        return str(exc), True
    except (ValueError, TypeError) as exc:
        return f"Demande invalide : {exc}", True
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"), default=str), False
