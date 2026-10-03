"""The weekly watch: the checks on a file, its readable version, and what the
application and the assistant show of it. Companies and facts are invented."""

import copy
import json
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cockpit import roadmap, store, veille
from cockpit.api import create_app
from cockpit.assistant import tools
from cockpit.importers import tr_csv

ROOT = Path(__file__).resolve().parents[1]
ACME, GLOBEX, INITECH, FUND = "XX0000000001", "XX0000000002", "XX0000000004", "XX0000000003"
UNIVERSE = [
    {"nom": "Acme", "isin": ACME, "secteur": "Industrie"},
    {"nom": "Globex", "isin": GLOBEX, "secteur": "Santé"},
    {"nom": "Initech", "isin": INITECH, "secteur": "Énergie"},
]
SOURCE = {"titre": "Communiqué du 4 juin", "url": "https://example.org/communique"}


def watch() -> dict:
    return {
        "semaine": "2025-W23",
        "du": "2025-05-31",
        "au": "2025-06-06",
        "macro": [
            {
                "sujet": "Taux directeurs",
                "texte": "La banque centrale a baissé son taux de dépôt de 0,25 point.",
                "sources": [{"titre": "Décision du 5 juin", "url": "https://example.org/taux"}],
            }
        ],
        "titres": [
            {
                "nom": "Acme",
                "isin": ACME,
                "faits": [
                    {
                        "date": "2025-06-04",
                        "texte": "Chiffre d'affaires en hausse.",
                        "source": SOURCE,
                    },
                    {
                        "date": "2025-06-02",
                        "texte": "Nouveau directeur financier.",
                        "source": SOURCE,
                    },
                ],
                "prochain_rendez_vous": {
                    "date": "2025-07-24",
                    "objet": "Résultats semestriels",
                    "source": {"titre": "Agenda [financier]", "url": "https://example.org/agenda"},
                },
                "a_regarder": None,
            },
            {
                "nom": "Globex",
                "isin": GLOBEX,
                "faits": [],
                "prochain_rendez_vous": None,
                "a_regarder": None,
            },
            {
                "nom": "Initech",
                "isin": INITECH,
                "faits": [
                    {"date": "2025-06-06", "texte": "Rachat d'actions annoncé.", "source": SOURCE}
                ],
                "prochain_rendez_vous": None,
                "a_regarder": "Autorisation du régulateur attendue.",
            },
        ],
    }


def errors_after(change) -> list[str]:
    data = watch()
    change(data)
    return veille.validate(data, UNIVERSE)


# -- Period ------------------------------------------------------------------------


def test_a_watch_covers_the_seven_days_ending_on_friday():
    saturday = veille.period_of(date(2026, 10, 3))
    assert saturday == ("2026-W40", date(2026, 9, 26), date(2026, 10, 2))
    # Written late, on Monday, it still covers the same week; on a Friday, the week ending then.
    assert veille.period_of(date(2026, 10, 5)) == saturday
    assert veille.period_of(date(2026, 10, 2)) == saturday
    # Across the new year, the week is named after the ISO year of its Friday.
    assert veille.period_of(date(2027, 1, 2)) == ("2026-W53", date(2026, 12, 26), date(2027, 1, 1))


# -- Checks ------------------------------------------------------------------------


def test_a_complete_watch_passes():
    assert veille.validate(watch(), UNIVERSE) == []


def test_every_company_of_the_list_appears_once():
    assert errors_after(lambda d: d["titres"].pop(1)) == ["Globex : absent de la veille"]
    assert errors_after(lambda d: d["titres"].append(copy.deepcopy(d["titres"][0]))) == [
        "Acme : présent deux fois"
    ]
    unknown = errors_after(lambda d: d["titres"][1].update(isin="XX0000000009"))
    assert "Globex : ISIN absent de la liste des titres" in unknown
    renamed = errors_after(lambda d: d["titres"][1].update(nom="Globex Corp"))
    assert renamed == [f"Globex Corp : le nom attendu pour {GLOBEX} est « Globex »"]


def test_a_fact_needs_a_date_in_the_week_and_a_source():
    def fact(data):
        return data["titres"][0]["faits"][0]

    assert errors_after(lambda d: fact(d).update(date="2025-05-30")) == [
        "Acme : fait du 2025-05-30 hors de la période"
    ]
    assert errors_after(lambda d: fact(d).update(date="hier")) == ["Acme : fait sans date"]
    assert errors_after(lambda d: fact(d).pop("source")) == ["Acme : source absente"]
    assert errors_after(lambda d: fact(d).update(source={"titre": "Presse", "url": "exemple"})) == [
        "Acme : source sans adresse web"
    ]
    assert errors_after(lambda d: fact(d).update(texte="x" * 501)) == [
        "Acme : fait sans texte ou trop long"
    ]


def test_the_period_runs_from_saturday_to_friday():
    assert errors_after(lambda d: d.update(au="2025-06-05")) != []
    assert errors_after(lambda d: d.update(semaine="2025-W22")) == [
        "semaine : ne correspond pas à la semaine ISO du vendredi « au »"
    ]


def test_the_next_event_lies_after_the_week_and_has_a_source():
    def event(data):
        return data["titres"][0]["prochain_rendez_vous"]

    assert errors_after(lambda d: event(d).update(date="2025-06-06")) == [
        "Acme : le prochain rendez-vous est déjà passé"
    ]
    assert errors_after(lambda d: event(d).pop("source")) == [
        "Acme, prochain rendez-vous : source absente"
    ]


def test_macro_points_are_sourced_and_few():
    assert errors_after(lambda d: d["macro"][0].update(sources=[])) == [
        "macro, point 1 : au moins une source"
    ]
    assert errors_after(lambda d: d.update(macro=d["macro"] * 9)) == ["macro : 8 points au plus"]
    assert errors_after(lambda d: d.update(macro=[])) == []  # a week without macro is allowed


# -- Readable version ----------------------------------------------------------------


def test_the_readable_version_follows_the_file():
    text = veille.render(watch())
    assert text == veille.render(watch())
    assert text.startswith("# Veille de la semaine 23 de 2025\n\nDu 31 mai au 6 juin 2025.")
    assert "## Titres avec du nouveau (2)" in text and "## Rien de notable (1)\n\nGlobex." in text
    # Facts in the order they happened, each with its source.
    first, second = text.index("2 juin : Nouveau directeur"), text.index("4 juin : Chiffre")
    assert first < second
    assert "(https://example.org/communique)" in text
    assert "- À regarder : Autorisation du régulateur attendue." in text
    # Brackets in a source title would break the link.
    assert "| 24 juillet 2025 | Acme | Résultats semestriels ([Agenda (financier)](" in text


def test_the_script_writes_the_readable_version_or_says_what_is_wrong(tmp_path, capsys):
    folder = tmp_path / "veilles" / "2025"
    folder.mkdir(parents=True)
    (tmp_path / "fiches").mkdir()
    (tmp_path / "fiches" / "univers.json").write_text(json.dumps({"titres": UNIVERSE}), "utf-8")
    file = folder / "2025-W23.json"
    file.write_text(json.dumps(watch()), "utf-8")
    assert veille.main([str(file)]) == 0
    assert file.with_suffix(".md").read_text("utf-8") == veille.render(watch())

    incomplete = watch()
    incomplete["titres"].pop()
    file.write_text(json.dumps(incomplete), "utf-8")
    assert veille.main([str(file)]) == 1
    assert "Initech : absent de la veille" in capsys.readouterr().err


def test_every_watch_of_the_repository_is_valid_and_rendered():
    universe = json.loads((ROOT / "fiches" / "univers.json").read_text("utf-8"))["titres"]
    isins = [entry["isin"] for entry in universe]
    assert len(set(isins)) == len(isins) and all(len(isin) == 12 for isin in isins)
    for file in sorted((ROOT / "veilles").glob("20*/20*-W*.json")):
        data = json.loads(file.read_text("utf-8"))
        assert veille.validate(data, universe) == [], file.name
        assert file.stem == data["semaine"] and file.parent.name == data["semaine"][:4]
        assert file.with_suffix(".md").read_text("utf-8") == veille.render(data), file.name


# -- The reading of the week ----------------------------------------------------------


def reading(lean: str = "partagée") -> dict:
    return {
        "hausse": ["Les résultats publiés cette semaine sont en hausse."],
        "baisse": ["La banque centrale a relevé ses taux.", "Le pétrole renchérit."],
        "signaux": [
            {"date": "2025-06-12", "texte": "Prochaine décision de taux."},
            {"date": None, "texte": "Prochain chiffre d'inflation."},
        ],
        "balance": {"sens": lean, "confiance": "faible", "motif": "Rien ne l'emporte nettement."},
    }


def with_reading() -> dict:
    data = watch()
    data["lecture"] = {
        "marche": reading("baisse"),
        "secteurs": [{"secteur": "Industrie", **reading()}, {"secteur": "Énergie", **reading()}],
    }
    return data


def reading_errors(change) -> list[str]:
    data = with_reading()
    change(data["lecture"])
    return veille.validate(data, UNIVERSE)


def test_a_reading_argues_both_sides_and_stays_modest():
    assert veille.validate(with_reading(), UNIVERSE) == []
    assert reading_errors(lambda r: r["marche"].update(hausse=[])) == [
        "lecture du marché : de 1 à 4 arguments à la hausse"
    ]
    assert reading_errors(lambda r: r["marche"].update(baisse=["x"] * 5)) == [
        "lecture du marché : de 1 à 4 arguments à la baisse"
    ]
    # Nobody knows where a market goes: there is no strong confidence to claim.
    assert reading_errors(lambda r: r["marche"]["balance"].update(confiance="forte")) == [
        "lecture du marché : balance, confiance attendue parmi faible, moyenne"
    ]
    assert reading_errors(lambda r: r["marche"]["balance"].update(sens="krach")) == [
        "lecture du marché : balance, sens attendu parmi hausse, baisse, partagée"
    ]
    assert reading_errors(lambda r: r["marche"].pop("balance")) == [
        "lecture du marché : balance absente"
    ]


@pytest.mark.parametrize(
    "text",
    [
        "Il faut acheter avant les résultats.",
        "Mieux vaut vendre maintenant.",
        "Renforcer la ligne sur repli.",
        "Objectif de cours relevé à 200 euros.",
    ],
)
def test_a_reading_never_gives_an_order(text):
    errors = reading_errors(lambda r: r["marche"].update(hausse=[text]))
    assert errors == [
        "lecture du marché, à la hausse : une lecture ne donne pas de consigne d'achat ou de vente"
    ]
    # Sales and purchases as facts are not orders.
    assert (
        reading_errors(lambda r: r["marche"].update(hausse=["Les ventes et les achats montent."]))
        == []
    )


def test_a_reading_names_known_sectors_and_future_signals():
    assert reading_errors(lambda r: r["secteurs"][0].update(secteur="Cryptomonnaies")) == [
        "lecture : secteur inconnu de la liste des titres (Cryptomonnaies)"
    ]
    assert reading_errors(lambda r: r["secteurs"].append(dict(r["secteurs"][0]))) == [
        "lecture : secteur présent deux fois (Industrie)"
    ]
    assert reading_errors(lambda r: r.update(secteurs=r["secteurs"] * 4)) == [
        "lecture : secteurs, liste de 6 au plus"
    ]
    assert reading_errors(lambda r: r["marche"]["signaux"][0].update(date="2025-06-06")) == [
        "lecture du marché : un signal daté est postérieur à la période"
    ]
    assert reading_errors(lambda r: r["marche"].update(signaux=[])) == [
        "lecture du marché : de 1 à 4 signaux à surveiller"
    ]


def test_the_reading_closes_the_readable_version_and_says_what_it_is():
    text = veille.render(with_reading())
    assert "## Lecture de la semaine" not in veille.render(watch())  # optional
    reading_part = text[text.index("## Lecture de la semaine") :]
    assert text.index("## Prochains rendez-vous") < text.index("## Lecture de la semaine")
    assert "Ce n'est pas un conseil en investissement" in reading_part
    assert "### Marché" in reading_part and "### Industrie" in reading_part
    assert "- 12 juin 2025 : Prochaine décision de taux." in reading_part
    assert "- Prochain chiffre d'inflation." in reading_part
    assert "**Balance : penche à la baisse, confiance faible.** Rien ne l'emporte" in reading_part
    assert "**Balance : partagée, confiance faible.**" in reading_part


# -- In the application --------------------------------------------------------------


@pytest.fixture
def folder(tmp_path, monkeypatch):
    """A repository in miniature: the list of companies and one watch."""
    (tmp_path / "fiches").mkdir()
    (tmp_path / "fiches" / "univers.json").write_text(json.dumps({"titres": UNIVERSE}), "utf-8")
    week = tmp_path / "veilles" / "2025"
    week.mkdir(parents=True)
    (week / "2025-W23.json").write_text(json.dumps(watch()), "utf-8")
    monkeypatch.setenv("COCKPIT_VEILLES_DIR", str(tmp_path / "veilles"))
    return tmp_path / "veilles"


def test_the_application_marks_held_lines_and_targets(conn, sample_csv, folder):
    tr_csv.import_csv(conn, sample_csv)
    roadmap.create(conn, {"name": "initech", "status": "prevu"})  # no ISIN: found by its name
    roadmap.create(conn, {"name": "Umbrella", "isin": "XX0000000007", "status": "idee"})
    roadmap.create(conn, {"name": "Hooli", "status": "abandonne"})
    view = store.watch(conn, folder)
    assert {t["nom"]: t["suivi"] for t in view["report"]["titres"]} == {
        "Acme": "ligne",
        "Globex": "ligne",
        "Initech": "cible",
    }
    assert view["weeks"] == [{"semaine": "2025-W23", "du": "2025-05-31", "au": "2025-06-06"}]
    # A target outside the list is named; the fund held is not: a watch is about companies.
    assert view["uncovered"] == ["Umbrella"]


def test_an_unusable_file_is_left_out(conn, folder):
    broken = watch()
    broken.update(semaine="2025-W24", du="2025-06-07", au="2025-06-13")
    broken["titres"].pop()
    (folder / "2025" / "2025-W24.json").write_text(json.dumps(broken), "utf-8")
    (folder / "2025" / "2025-W25.json").write_text("{", "utf-8")
    assert [week["semaine"] for week in store.watch(conn, folder)["weeks"]] == ["2025-W23"]


def test_the_latest_week_is_shown_unless_another_is_asked(conn, folder):
    later = watch()
    later.update(semaine="2025-W24", du="2025-06-07", au="2025-06-13")
    for title in later["titres"]:
        title.update(faits=[], prochain_rendez_vous=None, a_regarder=None)
    (folder / "2025" / "2025-W24.json").write_text(json.dumps(later), "utf-8")
    assert store.watch(conn, folder)["report"]["semaine"] == "2025-W24"
    assert store.watch(conn, folder, "2025-W23")["report"]["semaine"] == "2025-W23"
    assert store.watch(conn, folder, "2019-W01")["report"]["semaine"] == "2025-W24"


def test_without_a_watch_the_screen_says_so(conn, tmp_path):
    assert store.watch(conn, None) == {"weeks": [], "report": None, "uncovered": []}
    assert store.watch(conn, tmp_path)["report"] is None


def test_the_watch_over_the_api(tmp_path, sample_csv, folder):
    client = TestClient(create_app(tmp_path / "veille.db"))
    client.post(
        "/api/import/csv", content=sample_csv.encode(), headers={"content-type": "text/csv"}
    )
    body = client.get("/api/veille").json()
    assert body["report"]["semaine"] == "2025-W23"
    assert [t["suivi"] for t in body["report"]["titres"]] == ["ligne", "ligne", None]
    assert client.get("/api/veille", params={"semaine": "2025-W23"}).status_code == 200


def test_the_assistant_reads_the_followed_companies_first(conn, sample_csv, folder):
    tr_csv.import_csv(conn, sample_csv)
    output, failed = tools.run(conn, "lire_veille", {})
    data = json.loads(output)
    assert failed is False and data["semaine"] == "2025-W23"
    assert [t["nom"] for t in data["titres"]] == ["Acme", "Globex"]
    assert data["titres"][0]["suivi"] == "ligne détenue"
    assert data["autres_titres_avec_du_nouveau"] == ["Initech"]
    assert data["macro"][0]["sujet"] == "Taux directeurs"

    everything = json.loads(tools.run(conn, "lire_veille", {"tous_les_titres": True})[0])
    assert [t["nom"] for t in everything["titres"]] == ["Acme", "Globex", "Initech"]


def test_the_assistant_is_told_when_there_is_no_watch(conn, monkeypatch, tmp_path):
    monkeypatch.setenv("COCKPIT_VEILLES_DIR", str(tmp_path / "absent"))
    assert json.loads(tools.run(conn, "lire_veille", {})[0])["veille"] is None


def test_the_reading_marks_the_sectors_held_or_targeted(conn, sample_csv, folder):
    (folder / "2025" / "2025-W23.json").write_text(json.dumps(with_reading()), "utf-8")
    tr_csv.import_csv(conn, sample_csv)  # Acme and Globex are held, Initech is not
    lecture = store.watch(conn, folder)["report"]["lecture"]
    assert [(s["secteur"], s["suivi"]) for s in lecture["secteurs"]] == [
        ("Industrie", True),
        ("Énergie", False),
    ]
    assert lecture["marche"]["balance"]["sens"] == "baisse"
    roadmap.create(conn, {"name": "Initech", "isin": INITECH, "status": "idee"})
    assert store.watch(conn, folder)["report"]["lecture"]["secteurs"][1]["suivi"] is True

    told = json.loads(tools.run(conn, "lire_veille", {})[0])
    assert told["lecture_de_la_semaine"]["marche"]["balance"]["confiance"] == "faible"
    assert "opinion" in told["rappel"]


def test_a_watch_without_a_reading_shows_none(conn, folder):
    assert store.watch(conn, folder)["report"]["lecture"] is None
