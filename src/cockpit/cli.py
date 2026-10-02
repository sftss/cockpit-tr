"""Command line: ``cockpit serve``, ``import FILE``, ``report``, ``cours``."""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from pathlib import Path

from . import __version__, config, db, store
from .importers import tr_csv


def _euro(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:,.2f} €".replace(",", " ").replace(".", ",")


def cmd_import(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.is_file():
        print(f"Fichier introuvable : {path}", file=sys.stderr)
        return 1
    conn = db.connect()
    try:
        report = tr_csv.import_csv(conn, path.read_text(encoding="utf-8-sig"))
    except tr_csv.CsvFormatError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(
        f"{report.total} lignes lues, {report.inserted} ajoutées, "
        f"{report.already_present} déjà présentes."
    )
    if report.date_min:
        print(f"Période du fichier : {report.date_min} → {report.date_max}")
    for message in report.rejected:
        print(f"  rejetée — {message}")
    for name, count in report.unknown_types.items():
        print(f"  type non reconnu, ignoré dans les calculs : {name} ({count})")
    print(f"Base : {config.db_path()}")
    return 0


def cmd_report(_: argparse.Namespace) -> int:
    data = store.current_report(db.connect())
    if not data["transactions"]:
        print("Aucune transaction. Commencer par : cockpit import <export.csv>")
        return 1
    period = data["period"]
    print(f"{data['transactions']} transactions, du {period['from']} au {period['to']}\n")
    for account in data["accounts"]:
        print(
            f"{account['account']} : {account['open_lines']} lignes ouvertes, "
            f"{account['closed_lines']} soldées, "
            f"capital net engagé {_euro(account['net_invested'])}, "
            f"frais d'ordre {_euro(account['order_fees'])}"
        )
    fees, flows, closed = data["fees"], data["flows"], data["closed_summary"]
    share = fees["share_of_capital"]
    print(f"\nCapital net apporté : {_euro(flows['capital_brought_in'])}")
    print(
        f"Frais totaux : {_euro(fees['total'])}"
        + (
            f" ({share * 100:.1f} % du capital apporté)".replace(".", ",")
            if share is not None
            else ""
        )
    )
    print(f"  dont rechargements : {_euro(fees['deposits'])}")
    print(f"\nLignes soldées : {closed['count']} (gagnantes : {closed['winners']})")
    print(
        f"  capital engagé {_euro(closed['bought'])}, résultat brut {_euro(closed['gross'])}, "
        f"frais {_euro(closed['fees'])}, résultat net {_euro(closed['net'])}"
    )
    print("\nOrdres manuels par trimestre :")
    for quarter in data["quarters"]:
        print(
            f"  {quarter['quarter']} : {quarter['manual_orders']:>3}  "
            f"(frais d'ordre {_euro(quarter['order_fees'])})"
        )
    return 0


def cmd_cours(args: argparse.Namespace) -> int:
    """Fetch quotes from the terminal: the quickest way to see what the source answers."""
    from .market import service
    from .market.yahoo import YahooProvider

    conn = db.connect()
    if store.state(conn)["transactions"] == 0:
        print("Aucune transaction. Commencer par : cockpit import <export.csv>")
        return 1
    market = service.Market(YahooProvider())
    if args.historique:
        print("Chargement de l'historique quotidien (une minute environ)…")
        outcome = market.load_history(conn, service.all_isins(conn), store.state(conn)["from"])
    else:
        outcome = market.refresh_quotes(conn, service.open_isins(conn))

    live = store.quotes(conn)
    for item in service.instruments(conn):
        if not (item["held"] or args.historique):
            continue
        quote = live.get(item["isin"])
        if item["symbol"] is None:
            found = item["status"] == "introuvable"
            detail = "aucune cotation trouvée par ISIN" if found else "pas encore recherché"
        elif quote:
            delay = item["delay_minutes"]
            timing = (
                "délai inconnu"
                if delay is None
                else ("temps réel" if delay == 0 else f"différé {delay} min")
            )
            native = f"{quote['price']:.2f} {quote['currency']}"
            detail = f"{native:>14}  {_euro(quote['price_eur']):>12}  {timing}"
        else:
            detail = f"{item['price_days']} jours de cours en base"
        print(f"{item['name'][:34]:<34}  {(item['symbol'] or '—'):<10}  {detail}")

    print(f"\n{outcome.updated} mis à jour, {outcome.skipped} sans changement ou sans cotation.")
    if any(i["status"] == "introuvable" and i["symbol"] is None for i in service.instruments(conn)):
        print("Titre sans cotation : saisir son symbole Yahoo dans l'écran Données, section Cours.")
    for message in outcome.errors:
        print(f"  erreur — {message}")
    if outcome.unreachable:
        print("La source est injoignable : vérifier la connexion Internet.")
    if outcome.refused:
        print(
            "La source a refusé la requête : réessayer plus tard. "
            "Les cours peuvent toujours être saisis à la main."
        )
    return 0 if not outcome.errors else 1


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .api import create_app

    if config.frontend_dir() is None:
        print(
            "Interface non construite : lancer « npm install » puis « npm run build » "
            "dans le dossier frontend. L'API seule démarre quand même.",
            file=sys.stderr,
        )
    url = f"http://127.0.0.1:{args.port}"
    print(f"Cockpit TR {__version__} — {url}   (Ctrl+C pour arrêter)")
    print(f"Données : {config.data_dir()}")
    if not args.no_open:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    # 127.0.0.1 only: the dashboard must never be reachable from the network.
    uvicorn.run(create_app(), host="127.0.0.1", port=args.port, log_level="warning")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cockpit", description="Cockpit TR")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="démarrer le tableau de bord local")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--no-open", action="store_true", help="ne pas ouvrir le navigateur")
    serve.set_defaults(func=cmd_serve)

    imp = sub.add_parser("import", help="importer un export CSV de transactions")
    imp.add_argument("file")
    imp.set_defaults(func=cmd_import)

    rep = sub.add_parser("report", help="afficher le résumé dans le terminal")
    rep.set_defaults(func=cmd_report)

    cours = sub.add_parser("cours", help="récupérer les cours des titres détenus")
    cours.add_argument(
        "--historique",
        action="store_true",
        help="charger l'historique quotidien de tous les titres",
    )
    cours.set_defaults(func=cmd_cours)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
