import json
from pathlib import Path

import pytest

from cockpit import scoring

GOOD = {
    "produits_physiques": False,
    "chiffre_affaires": {"2021": 100, "2025": 180},  # +15.8 %/an
    "cash_flow_libre": {"2021": 20, "2023": 26, "2025": 36},  # +15.8 %/an, always positive
    "chiffre_affaires_12m": 200,
    "resultat_net_12m": 50,  # 25 %
    "resultat_operationnel_12m": 70,
    "ebitda_12m": 80,
    "dette_nette": -10,  # net cash
    "capitaux_propres": 210,  # ROIC = 70 * 0.75 / 200 = 26.25 %
    "taux_impot": 0.25,
    "per": 22,
    "taux_distribution": 0.30,
}


def points(result):
    return {c["cle"]: c["points"] for c in result["criteres"]}


def test_top_marks():
    result = scoring.score(GOOD)
    assert (result["note"], result["libelle"]) == (20, "à approfondir")
    assert points(result) == {
        "croissance_ca": 3,
        "marge_nette": 3,
        "dette_ebitda": 3,
        "croissance_fcf": 3,
        "roic": 4,
        "per": 2,
        "distribution": 2,
    }


@pytest.mark.parametrize(
    ("change", "key", "expected"),
    [
        ({"chiffre_affaires": {"2021": 100, "2025": 130}}, "croissance_ca", 2),  # 6.8 %/an
        ({"chiffre_affaires": {"2021": 100, "2025": 104}}, "croissance_ca", 1),
        ({"chiffre_affaires": {"2021": 100, "2025": 90}}, "croissance_ca", 0),
        ({"resultat_net_12m": 30}, "marge_nette", 2),  # 15 %
        ({"resultat_net_12m": 12}, "marge_nette", 1),  # 6 %
        ({"resultat_net_12m": -5}, "marge_nette", 0),
        ({"resultat_net_12m": 12, "produits_physiques": True}, "marge_nette", 2),  # halved
        ({"dette_nette": 150}, "dette_ebitda", 3),  # 1.9
        ({"dette_nette": 160}, "dette_ebitda", 1),  # exactly 2.0
        ({"dette_nette": 240}, "dette_ebitda", 0),  # exactly 3.0
        ({"dette_nette": 50, "ebitda_12m": -1}, "dette_ebitda", 0),
        ({"cash_flow_libre": {"2021": 20, "2025": 24}}, "croissance_fcf", 2),
        ({"cash_flow_libre": {"2021": 20, "2025": 15}}, "croissance_fcf", 1),
        ({"cash_flow_libre": {"2021": 20, "2023": -3, "2025": 40}}, "croissance_fcf", 1),
        ({"cash_flow_libre": {"2021": 20, "2025": -1}}, "croissance_fcf", 0),
        ({"capitaux_propres": 310}, "roic", 3),  # 17.5 %
        ({"capitaux_propres": 510}, "roic", 2),  # 10.5 %
        ({"capitaux_propres": 810}, "roic", 1),  # 6.6 %
        ({"capitaux_propres": 1510}, "roic", 0),  # 3.5 %
        ({"per": 25}, "per", 1),
        ({"per": 35}, "per", 0),
        ({"per": -8}, "per", 0),
        ({"taux_distribution": 0.70}, "distribution", 1),
        ({"taux_distribution": 0.95}, "distribution", 0),
        ({"taux_distribution": None}, "distribution", 1),  # no dividend: neutral
    ],
)
def test_each_threshold(change, key, expected):
    assert points(scoring.score({**GOOD, **change}))[key] == expected


def test_labels_follow_the_score():
    middling = {
        **GOOD,
        "chiffre_affaires": {"2021": 100, "2025": 104},
        "resultat_net_12m": 30,
        "dette_nette": 160,
        "capitaux_propres": 350,
        "per": 30,
    }
    result = scoring.score(middling)  # 1 + 2 + 1 + 3 + 2 + 1 + 2 = 12
    assert (result["points"], result["note"], result["libelle"]) == (12, 12, "à surveiller")
    weak = scoring.score({**middling, "taux_distribution": 0.95, "per": 40})
    assert (weak["note"], weak["libelle"]) == (9, "écarté")


def test_missing_figures_are_left_out_not_guessed():
    partial = {k: v for k, v in GOOD.items() if k not in ("per", "taux_distribution")}
    result = scoring.score(partial)
    assert (result["criteres_notes"], result["points_possibles"], result["note"]) == (5, 16, 20)
    assert "note partielle : 5 critères sur 7" in scoring.headline(result)

    too_little = scoring.score({"per": 20, "taux_distribution": 0.3})
    assert too_little["note"] is None and too_little["libelle"] is None
    assert scoring.headline(too_little).startswith("Non notée")


def test_published_sheets_match_the_grid():
    """Every sheet in fiches/ must state the score the grid gives its figures."""
    root = Path(__file__).resolve().parents[1] / "fiches"
    sheets = sorted(root.glob("20*/*.json"))
    assert sheets, "aucune fiche trouvée"
    for path in sheets:
        result = scoring.score(json.loads(path.read_text(encoding="utf-8"))["chiffres"])
        text = path.with_suffix(".md").read_text(encoding="utf-8")
        assert scoring.headline(result) in text, f"{path.name} : note différente du barème"
        assert scoring.markdown_table(result) in text, f"{path.name} : tableau différent du barème"
