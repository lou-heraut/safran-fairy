#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Louis Héraut <louis.heraut@inrae.fr>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Vérifie que la chaîne rattrape bien un état incomplet.

Deux pannes ont coûté cher et se ressemblent : un pipeline qui croit avoir fini
alors qu'il lui manque des morceaux. Le 4 août, une chronique dupliquée est
partie en ligne ; le 3 septembre, une chronique trouée a été produite parce que
le traitement ne portait que sur le dernier lot téléchargé.

Ce script rejoue ces situations sur trois années réelles et vérifie que chacune
est rattrapée. Il ne touche à rien : il travaille dans un dossier temporaire.

    python verifier_reprise.py
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

from safran_fairy import build, check, list_resources, process
from safran_fairy.download import has_changed

ANNEES = ("1958", "1959", "1960")
VARIABLE = "TINF_H"


def charger_config():
    load_dotenv()
    config = json.load(open(os.getenv("CONFIG_FILE", "config.json")))
    return config, Path("resources")


def tour(bac, config, resources_dir, attendu):
    """Un passage complet, et ce qu'il a réellement fait."""
    sources = sorted(Path(bac / "dl").glob("*.csv.gz"))
    tampon = io.StringIO()
    with contextlib.redirect_stdout(tampon):
        process(sources, bac / "dl", bac / "raw", bac / "split", bac / "conv",
                resources_dir / config["METADATA_VARIABLES_FILE"],
                METADATA_GRID_FILE=resources_dir / config["METADATA_GRID_FILE"],
                variables=[VARIABLE])
        sorties = build(bac / "conv", bac / "out", variables=[VARIABLE])
        rejets = check(sorties)
    texte = tampon.getvalue()

    obtenu = {
        "converties": texte.count("Conversion NetCDF"),
        "sautees": texte.count("déjà converti"),
        "assemblage": "refait" if "déjà à jour" not in texte.split("ASSEMBLAGE")[-1]
                      else "sauté",
        "controle": "rejeté" if rejets else "ok",
    }
    ecarts = {k: (v, obtenu[k]) for k, v in attendu.items() if obtenu[k] != v}
    return obtenu, ecarts


def main() -> int:
    config, resources_dir = charger_config()
    source_dir = Path(config["DOWNLOAD_DIR"])
    manquants = [a for a in ANNEES
                 if not (source_dir / f"QUOT_SIM2_{a}.csv.gz").exists()]
    if manquants:
        sys.exit(f"❌ années absentes de {source_dir} : {', '.join(manquants)}")

    bac = Path(tempfile.mkdtemp(prefix="verifier-reprise-"))
    for nom in ("dl", "raw", "split", "conv", "out"):
        (bac / nom).mkdir()
    for annee in ANNEES:
        shutil.copy(source_dir / f"QUOT_SIM2_{annee}.csv.gz", bac / "dl")

    cas = [
        ("premier passage, tout est à faire",
         None,
         dict(converties=3, sautees=0, assemblage="refait", controle="ok")),
        ("un NetCDF du cache disparaît, comme un dossier vidé à la main",
         lambda: (bac / "conv" / f"{VARIABLE}_QUOT_SIM2_1959.nc").unlink(),
         dict(converties=1, sautees=2, assemblage="refait", controle="ok")),
        ("rien ne bouge, tout doit être sauté",
         None,
         dict(converties=0, sautees=3, assemblage="sauté", controle="ok")),
        ("une source est retéléchargée, donc plus récente",
         lambda: (bac / "dl" / "QUOT_SIM2_1960.csv.gz").touch(),
         dict(converties=1, sautees=2, assemblage="refait", controle="ok")),
    ]

    print("REPRISE APRÈS UN ÉTAT INCOMPLET\n")
    echecs = 0
    for titre, casser, attendu in cas:
        if casser:
            casser()
        obtenu, ecarts = tour(bac, config, resources_dir, attendu)
        marque = "✅" if not ecarts else "❌"
        print(f"{marque} {titre}")
        print(f"   converties {obtenu['converties']}, sautées {obtenu['sautees']}, "
              f"assemblage {obtenu['assemblage']}, contrôle {obtenu['controle']}")
        for cle, (veut, a) in ecarts.items():
            print(f"   attendu {cle} = {veut}, obtenu {a}")
            echecs += 1

    print("\nDÉTECTION DES SOURCES À REPRENDRE\n")
    ressource = next(r for r in list_resources(config["METEO_BASE_URL"],
                                               config["METEO_DATASET_ID"])
                     if r.filename == f"QUOT_SIM2_{ANNEES[0]}.csv.gz")
    etat = {ressource.id: {"filename": ressource.filename,
                           "last_modified": ressource.last_modified,
                           "size_bytes": ressource.size}}
    fichier = bac / "dl" / ressource.filename
    situations = [
        ("fichier intact et état cohérent", lambda: None, etat, False),
        ("fichier supprimé", lambda: fichier.unlink(), etat, True),
        ("fichier tronqué", lambda: fichier.write_bytes(b"x" * 1000), etat, True),
        ("révisé en amont", lambda: shutil.copy(
            source_dir / ressource.filename, fichier),
         {ressource.id: {**etat[ressource.id], "last_modified": "2020-01-01"}}, True),
        ("jamais téléchargé", lambda: None, {}, True),
    ]
    for titre, casser, table, veut in situations:
        casser()
        obtenu = has_changed(ressource, table, bac / "dl")
        marque = "✅" if obtenu == veut else "❌"
        echecs += obtenu != veut
        print(f"{marque} {titre:34s} reprise : {obtenu}")

    shutil.rmtree(bac, ignore_errors=True)
    print(f"\n{'✅ tout est conforme' if not echecs else f'❌ {echecs} écart(s)'}")
    return 1 if echecs else 0


if __name__ == "__main__":
    sys.exit(main())
