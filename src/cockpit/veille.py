"""The weekly watch ("veille"): public facts about the companies of the list.

One JSON file per week holds the facts, each with its date and its source. This
module checks such a file against the rules below and writes the readable
Markdown version from it, so the two can never disagree.

A watch states facts. It is not a forecast and not a buy or sell signal, and it
says nothing about compliance, which is checked separately.

This module only uses the standard library and imports nothing from the rest
of the package, so it also runs on its own:

    python src/cockpit/veille.py veilles/2026/2026-W40.json
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

MAX_FACT = 500  # characters of one fact
MAX_NOTE = 400
MAX_MACRO = 8
MONTHS = [
    "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
    "octobre", "novembre", "décembre",
]  # fmt: skip
WEEK = re.compile(r"^(\d{4})-W(\d{2})$")
URL = re.compile(r"^https?://\S+$")


def _day(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def long_date(day: date, with_year: bool = True) -> str:
    text = f"{'1er' if day.day == 1 else day.day} {MONTHS[day.month - 1]}"
    return f"{text} {day.year}" if with_year else text


def period_of(run_day: date) -> tuple[str, date, date]:
    """The week a watch written on `run_day` covers: the seven days ending the
    Friday before (or that day, when it is a Friday), named by its ISO week."""
    end = run_day - timedelta(days=(run_day.weekday() - 4) % 7)
    year, week, _ = end.isocalendar()
    return f"{year}-W{week:02d}", end - timedelta(days=6), end


def _source(value: object, where: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{where} : source absente")
        return
    if not str(value.get("titre") or "").strip():
        errors.append(f"{where} : source sans titre")
    if not URL.match(str(value.get("url") or "")):
        errors.append(f"{where} : source sans adresse web")


def validate(data: object, universe: list[dict]) -> list[str]:
    """Everything wrong with a watch file; an empty list means it is usable."""
    if not isinstance(data, dict):
        return ["le fichier n'est pas un objet JSON"]
    errors: list[str] = []

    start, end = _day(data.get("du")), _day(data.get("au"))
    match = WEEK.match(str(data.get("semaine") or ""))
    if not match:
        errors.append("semaine : attendu AAAA-Wnn")
    if start is None or end is None:
        errors.append("du / au : dates AAAA-MM-JJ attendues")
    else:
        if end.weekday() != 4 or (end - start).days != 6:
            errors.append("du / au : la période va du samedi au vendredi, sept jours")
        year, week, _ = end.isocalendar()
        if match and (int(match[1]), int(match[2])) != (year, week):
            errors.append("semaine : ne correspond pas à la semaine ISO du vendredi « au »")

    macro = data.get("macro")
    if not isinstance(macro, list):
        errors.append("macro : liste attendue (elle peut être vide)")
    else:
        if len(macro) > MAX_MACRO:
            errors.append(f"macro : {MAX_MACRO} points au plus")
        for index, point in enumerate(macro, start=1):
            where = f"macro, point {index}"
            if not isinstance(point, dict):
                errors.append(f"{where} : objet attendu")
                continue
            if not str(point.get("sujet") or "").strip():
                errors.append(f"{where} : sujet manquant")
            text = str(point.get("texte") or "").strip()
            if not text or len(text) > MAX_FACT:
                errors.append(f"{where} : texte manquant ou trop long")
            sources = point.get("sources")
            if not isinstance(sources, list) or not sources:
                errors.append(f"{where} : au moins une source")
            else:
                for source in sources:
                    _source(source, where, errors)

    expected = {str(entry["isin"]): str(entry["nom"]) for entry in universe}
    titles = data.get("titres")
    if not isinstance(titles, list):
        return [*errors, "titres : liste attendue"]
    seen: set[str] = set()
    for item in titles:
        if not isinstance(item, dict):
            errors.append("titres : objet attendu")
            continue
        isin, name = str(item.get("isin") or ""), str(item.get("nom") or "")
        where = name or isin or "titre sans nom"
        if isin not in expected:
            errors.append(f"{where} : ISIN absent de la liste des titres")
        elif expected[isin] != name:
            errors.append(f"{where} : le nom attendu pour {isin} est « {expected[isin]} »")
        if isin in seen:
            errors.append(f"{where} : présent deux fois")
        seen.add(isin)

        facts = item.get("faits")
        if not isinstance(facts, list):
            errors.append(f"{where} : faits, liste attendue (vide s'il n'y a rien)")
            facts = []
        for fact in facts:
            if not isinstance(fact, dict):
                errors.append(f"{where} : fait mal formé")
                continue
            day = _day(fact.get("date"))
            if day is None:
                errors.append(f"{where} : fait sans date")
            elif start and end and not start <= day <= end:
                errors.append(f"{where} : fait du {day.isoformat()} hors de la période")
            text = str(fact.get("texte") or "").strip()
            if not text or len(text) > MAX_FACT:
                errors.append(f"{where} : fait sans texte ou trop long")
            _source(fact.get("source"), where, errors)

        upcoming = item.get("prochain_rendez_vous")
        if upcoming is not None:
            day = _day(upcoming.get("date")) if isinstance(upcoming, dict) else None
            if day is None or not str(upcoming.get("objet") or "").strip():
                errors.append(f"{where} : prochain rendez-vous sans date ou sans objet")
            elif end and day <= end:
                errors.append(f"{where} : le prochain rendez-vous est déjà passé")
            if isinstance(upcoming, dict):
                _source(upcoming.get("source"), f"{where}, prochain rendez-vous", errors)

        note = item.get("a_regarder")
        if note is not None and (not str(note).strip() or len(str(note)) > MAX_NOTE):
            errors.append(f"{where} : « à regarder » vide ou trop long")

    for isin in sorted(set(expected) - seen):
        errors.append(f"{expected[isin]} : absent de la veille")
    return errors


def _link(source: dict) -> str:
    title = str(source["titre"]).replace("[", "(").replace("]", ")")
    return f"[{title}]({source['url']})"


def render(data: dict) -> str:
    """The readable version of a watch. Same file in, same text out."""
    start, end = date.fromisoformat(data["du"]), date.fromisoformat(data["au"])
    week = int(data["semaine"][-2:])
    titles = data["titres"]
    with_news = [t for t in titles if t["faits"] or t.get("a_regarder")]
    quiet = [t for t in titles if not t["faits"] and not t.get("a_regarder")]

    lines = [
        f"# Veille de la semaine {week} de {end.isocalendar()[0]}",
        "",
        f"Du {long_date(start, start.year != end.year)} au {long_date(end)}. Faits publics relevés "
        f"pour les {len(titles)} titres de la liste, chacun avec sa source. Ce ne sont ni des "
        "prédictions ni des recommandations, et la Halalitude se vérifie à part.",
        "",
    ]
    if data["macro"]:
        lines += ["## Contexte", ""]
        for point in data["macro"]:
            sources = ", ".join(_link(source) for source in point["sources"])
            lines.append(f"- **{point['sujet']}.** {point['texte']} ({sources})")
        lines.append("")

    lines += [f"## Titres avec du nouveau ({len(with_news)})", ""]
    if not with_news:
        lines += ["Aucun cette semaine.", ""]
    for title in with_news:
        lines += [f"### {title['nom']}", ""]
        for fact in sorted(title["faits"], key=lambda f: f["date"]):
            day = long_date(date.fromisoformat(fact["date"]), with_year=False)
            lines.append(f"- {day} : {fact['texte']} ({_link(fact['source'])})")
        if title.get("a_regarder"):
            lines.append(f"- À regarder : {title['a_regarder']}")
        lines.append("")

    lines += [f"## Rien de notable ({len(quiet)})", ""]
    lines += [", ".join(t["nom"] for t in quiet) + "." if quiet else "Aucun.", ""]

    upcoming = sorted(
        (t for t in titles if t.get("prochain_rendez_vous")),
        key=lambda t: (t["prochain_rendez_vous"]["date"], t["nom"]),
    )
    if upcoming:
        lines += ["## Prochains rendez-vous", "", "| Date | Titre | Objet |", "| --- | --- | --- |"]
        for title in upcoming:
            event = title["prochain_rendez_vous"]
            day = long_date(date.fromisoformat(event["date"]))
            lines.append(
                f"| {day} | {title['nom']} | {event['objet']} ({_link(event['source'])}) |"
            )
        lines.append("")
    return "\n".join(lines)


def universe_of(folder: Path) -> list[dict]:
    """The list of companies, from ``fiches/univers.json`` beside ``veilles/``."""
    listing = json.loads((folder.parent / "fiches" / "univers.json").read_text(encoding="utf-8"))
    return listing["titres"]


def reports(folder: Path) -> list[dict]:
    """Every usable watch of the folder, most recent first. A file that does not
    pass the checks is left out rather than shown half-read."""
    try:
        universe = universe_of(folder)
    except (OSError, ValueError, KeyError):
        return []
    found = []
    for file in sorted(folder.glob("20*/20*-W*.json"), reverse=True):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not validate(data, universe):
            found.append(data)
    return found


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage : python src/cockpit/veille.py <veille.json>", file=sys.stderr)
        return 2
    file = Path(args[0])
    data = json.loads(file.read_text(encoding="utf-8"))
    errors = validate(data, universe_of(file.resolve().parents[1]))
    if errors:
        print(f"{len(errors)} problème(s) :", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    target = file.with_suffix(".md")
    target.write_text(render(data), encoding="utf-8")
    news = sum(1 for t in data["titres"] if t["faits"] or t.get("a_regarder"))
    print(f"Veille valide : {len(data['titres'])} titres, {news} avec du nouveau. Écrit : {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
