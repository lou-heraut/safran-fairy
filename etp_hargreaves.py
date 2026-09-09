#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Louis Héraut <louis.heraut@inrae.fr>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Annex production: the ETP FAO Hargreaves dataset, in the pipeline's format.

Météo-France publishes, next to SIM2, a potential evapotranspiration computed
with the FAO formula whose radiation term is estimated by Hargreaves with a
uniform coefficient of 0,175. It is a different quantity from the ETP of SIM2,
meant to be comparable with the DRIAS, Explore2 and TRACC climate projections,
and it is published on the same SAFRAN grid with the same CSV schema.

    https://meteo.data.gouv.fr/datasets/667eae35510cd549fc7722c1

This script turns it into one NetCDF holding the whole record, in exactly the
format the pipeline produces. That format is not reimplemented here: the file
is written by convert.create_netcdf() and checked by check.check_file(), the
same code that produces and guards what goes online.

Nothing here touches the pipeline. It has its own dataset, its own directory
and its own metadata sheet; the service never sees what it writes, and the
result is not published, neither on the S3 nor in the STAC catalogue.

    python etp_hargreaves.py                       # dans annexe-etp/
    python etp_hargreaves.py --dossier /data/etp
    python etp_hargreaves.py --decennies 1970-1979 # un essai sur une seule

The sources are kept: 921 Mo that nothing else brings back. The intermediates,
the CSV and the Parquet, live in a temporary directory and are gone with it.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import netCDF4
import pandas as pd
import requests
import xarray as xr
from dotenv import load_dotenv

from safran_fairy import report
from safran_fairy.check import check_file
from safran_fairy.convert import create_netcdf
from safran_fairy.split import split_file
from safran_fairy.tools import build_filename


API_URL = "https://www.data.gouv.fr/api/1/datasets/"
DATASET_ID = "667eae35510cd549fc7722c1"

VARIABLE = "ETP_Q_H0175"
VARIABLES_FILE = Path("resources/etp-hargreaves-variables_2026-09-09.csv")

# Measured on the first rows of the 1970-1979 file, not read in any document.
FIRST_DAY = pd.Timestamp("1970-01-01")

# One file per decade. The last one carries a « latest- » token in its URL and
# not in its title, a leftover of the naming SIM2 dropped in July 2026.
_SOURCE = re.compile(r"^ETP_Hargreaves_coefficient_0\.175_(?:latest-)?"
                     r"(?P<debut>\d{4})-(?P<fin>\d{4})\.csv\.gz$")

# The Parquet and the NetCDF take their variable name from their file name, and
# create_netcdf() reads it as what precedes « _QUOT_SIM2 ». The decompressed CSV
# is therefore named after the pipeline's convention rather than after upstream:
# that one rename is what lets the whole conversion be reused untouched.
def _work_name(span: str) -> str:
    return f"QUOT_SIM2_{span}.csv"


@dataclass(frozen=True)
class Source:
    """One decade of the dataset."""

    span: str        # « 1970-1979 »
    filename: str
    url: str
    size: int | None

    @property
    def debut(self) -> int:
        return int(self.span.split("-")[0])

    @property
    def fin(self) -> int:
        return int(self.span.split("-")[1])


def list_sources() -> list[Source]:
    """Les six fichiers de données du jeu, triés, la documentation écartée."""
    response = requests.get(API_URL + DATASET_ID + "/", timeout=60)
    response.raise_for_status()

    sources = []
    for raw in response.json().get("resources", []):
        url = raw.get("url", "")
        name = url.split("/")[-1].split("?")[0]
        match = _SOURCE.match(name)
        if not match:
            continue
        extras = raw.get("extras") or {}
        size = raw.get("filesize") or extras.get("check:headers:content-length")
        sources.append(Source(span=f"{match['debut']}-{match['fin']}",
                              filename=name, url=url,
                              size=int(size) if size else None))
    return sorted(sources, key=lambda s: s.debut)


def check_inventory(sources: list[Source]) -> list[str]:
    """
    Contrôle que le jeu a toujours la forme attendue, avant de télécharger.

    Même rôle que sources.check_inventory() pour SIM2 : si Météo-France
    recompose le jeu, il vaut mieux s'arrêter que produire en silence une
    chronique trouée. Le recouvrement est vérifié parce que les décennies sont
    concaténées bout à bout, sans départage possible.

    Returns:
        list[str]: les anomalies constatées. Liste vide si tout est conforme.
    """
    problems = []
    if not sources:
        return ["aucun fichier de données reconnu, le format amont a changé"]

    if sources[0].debut != FIRST_DAY.year:
        problems.append(f"la première décennie commence en {sources[0].debut} "
                        f"et non en {FIRST_DAY.year}")

    for avant, apres in zip(sources, sources[1:]):
        if apres.debut != avant.fin + 1:
            problems.append(f"entre {avant.span} et {apres.span} : "
                            f"{'trou' if apres.debut > avant.fin + 1 else 'recouvrement'}")

    for source in sources:
        if source.fin < source.debut:
            problems.append(f"{source.span} : bornes inversées")

    return problems


def download(source: Source, directory: Path) -> Path:
    """
    Récupère une décennie, et rend son chemin local.

    Écrit dans un « .part » renommé une fois complet, pour qu'une interruption
    ne laisse jamais un fichier qui a l'air entier. Un fichier déjà présent et
    de la bonne taille n'est pas retéléchargé : ce sont 166 Mo par décennie.
    """
    path = directory / source.filename
    if path.exists() and (not source.size or path.stat().st_size == source.size):
        report.line(f"{source.span}   déjà présent, "
                    f"{report.humain(path.stat().st_size)}")
        return path

    partial = path.with_suffix(path.suffix + ".part")
    with report.Chrono() as chrono:
        response = requests.get(source.url, stream=True, timeout=120)
        response.raise_for_status()
        with open(partial, "wb") as f:
            for morceau in response.iter_content(chunk_size=1 << 20):
                f.write(morceau)
        partial.replace(path)

    poids = path.stat().st_size
    if source.size and poids != source.size:
        path.unlink()
        raise RuntimeError(f"{source.filename} : {poids} octets reçus pour "
                           f"{source.size} annoncés, fichier retiré")
    report.line(f"{source.span}   téléchargé, {report.humain(poids):>8s}   {chrono}")
    return path


def extract(archive: Path, target: Path) -> Path:
    """
    Décompresse une source, quel que soit son format réel, et rend le CSV.

    Cinq des six fichiers sont des **archives ZIP** portant l'extension
    « .csv.gz », le sixième est un vrai gzip. Mesuré sur les octets d'en-tête :
    « PK\\x03\\x04 » pour les décennies de 1970 à 2019, « \\x1f\\x8b » pour
    2020-2024. Le piège est invisible en ligne de commande, l'outil gzip du
    système sachant lire un ZIP à membre unique là où le module gzip de Python
    le refuse par « Not a gzipped file ». D'où la lecture de l'en-tête plutôt
    que la confiance dans le nom.
    """
    with open(archive, "rb") as f:
        magic = f.read(4)

    if magic[:2] == b"PK":
        with zipfile.ZipFile(archive) as zf:
            members = [n for n in zf.namelist() if n.endswith(".csv")]
            if len(members) != 1:
                raise RuntimeError(f"{archive.name} : {len(members)} membre(s) "
                                   f"CSV dans l'archive, un seul attendu")
            with zf.open(members[0]) as source, open(target, "wb") as cible:
                shutil.copyfileobj(source, cible)
    elif magic[:2] == b"\x1f\x8b":
        with gzip.open(archive, "rb") as source, open(target, "wb") as cible:
            shutil.copyfileobj(source, cible)
    else:
        raise RuntimeError(f"{archive.name} : ni ZIP ni gzip, "
                           f"en-tête {magic!r}")
    return target


def _up_to_date(target: Path, source: Path) -> bool:
    """Whether a decade already converted can be left alone."""
    return target.exists() and target.stat().st_mtime >= source.stat().st_mtime


def convert_decade(gz: Path, span: str, directory: Path,
                   grid_file: Path, force: bool = False) -> Path:
    """
    Convertit une décennie en NetCDF, par le chemin du pipeline.

    Le CSV décompressé et le Parquet vivent dans un dossier temporaire, effacé
    en sortant : à eux deux ils pèsent plus que la source et n'ont d'intérêt
    que pendant la conversion.
    """
    target = directory / f"{VARIABLE}_QUOT_SIM2_{span}.nc"
    if not force and _up_to_date(target, gz):
        report.line(f"{span}   déjà converti, {target.name}")
        return target

    with report.Chrono() as chrono, TemporaryDirectory(dir=directory) as tmp:
        tmp = Path(tmp)
        csv = extract(gz, tmp / _work_name(span))
        brut = csv.stat().st_size
        parquet = split_file(csv, tmp)
        if len(parquet) != 1:
            raise RuntimeError(f"{gz.name} : {len(parquet)} variable(s) dans le "
                               f"CSV, une seule attendue")
        csv.unlink()
        ecrit = create_netcdf(parquet[0], directory, VARIABLES_FILE,
                              METADATA_GRID_FILE=grid_file)
        _stamp_provenance(ecrit, gz.name, "produit")

    if ecrit != target:
        raise RuntimeError(f"écrit sous {ecrit.name} au lieu de {target.name}")
    report.line(f"{span}   {report.humain(brut):>9s} → "
                f"{report.humain(target.stat().st_size):>8s}   {chrono}")
    return target


def _ncrcat(pieces: list[Path], target: Path) -> None:
    """
    Concatène, par un « ncrcat » simple et jamais « ncrcat -A ».

    Avec NCO 5.2.1 l'option -A écrit un nom d'attribut à l'envers, « eulaVlliF_ »
    pour « _FillValue ». Le découpage interne du résultat est hérité du premier
    fichier d'entrée, donc de celui que convert.py a écrit.
    """
    command = ["ncrcat", "-h", "-O"] + [str(p) for p in pieces] + [str(target)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"échec de ncrcat : "
                           f"{result.stderr.strip() or result.stdout.strip()}")


def _stamp_provenance(path: Path, source: str, action: str) -> None:
    """
    Réécrit les attributs globaux qui décrivent d'où vient le fichier.

    Appelée deux fois, et il faut les deux. Sur la sortie, parce que ncrcat
    hérite des attributs de sa première entrée et que le fichier assemblé se
    déclarerait sinon issu du seul Parquet de 1970. Sur chaque décennie, parce
    que create_netcdf() est écrite pour SIM2 et pose un « title » commençant par
    SIM2, un « source » nommant SAFRAN-ISBA-MODCOU et des « references » qui
    renvoient au jeu SIM2 et à son DOI. Ce jeu n'est pas celui-là : laisser ces
    valeurs sur un fichier qui traîne dans le même dossier que la sortie, c'est
    y écrire une provenance fausse, et un DOI qu'une citation ramasserait.
    """
    with netCDF4.Dataset(path, "a") as ds:
        ds.setncattr("title", "ETP FAO Hargreaves (coefficient 0.175) : "
                              "évapotranspiration potentielle SAFRAN")
        ds.setncattr("history",
                     f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} : "
                     f"{action} par safran-fairy depuis {source}")
        ds.setncattr("source_files", source)
        ds.setncattr("source", "SAFRAN, ETP FAO Hargreaves")
        ds.setncattr("references",
                     "https://meteo.data.gouv.fr/datasets/667eae35510cd549fc7722c1")
        # Pas de fenêtre d'agrégation, et ce n'est pas une lacune : cette ETP
        # se calcule à partir d'entrées SAFRAN qui n'ont pas la même journée,
        # donc aucune fenêtre unique ne la décrit. Le dire, plutôt que de
        # laisser croire qu'une fenêtre existe et nous échappe. Voir CLAUDE.md.
        ds.setncattr("comment",
                     "Cette grandeur n'a pas de fenêtre d'agrégation "
                     "quotidienne et n'en déclare donc aucune : elle se calcule "
                     "à partir d'entrées SAFRAN qui n'ont pas la même journée, "
                     "températures minimale et maximale, vent, tension de "
                     "vapeur, insolation et rayonnement global. Aucune fenêtre "
                     "unique ne la décrit, et Météo-France n'en donne pas, pas "
                     "plus que pour l'ETP Penman-Monteith FAO-56 de SIM2. "
                     "L'alignement, lui, est mesuré sur 1970-2024 et 30 "
                     "mailles : la date porte le même jour que celle de l'ETP "
                     "de SIM2, sans décalage, corrélation des anomalies "
                     "désaisonnalisées de 0,885 à décalage nul contre 0,572 au "
                     "plus proche voisin. Les deux fichiers se lisent donc sur "
                     "le même axe de dates. Fichier non publié, produit hors du "
                     "service safran-fairy, qui ne diffuse que SIM2.")


def assemble(decades: list[Path], directory: Path) -> Path:
    """
    Assemble les décennies en une chronique continue, nommée avec sa couverture.

    Le nom est composé après coup, sur les bornes lues dans le résultat et non
    déduites des entrées.
    """
    tmp = directory / f"{VARIABLE}_QUOT_SIM2_tmp.nc"
    with report.Chrono() as chrono:
        _ncrcat(decades, tmp)
        spans = [p.stem.split("_QUOT_SIM2_")[-1] for p in decades]
        source = (f"le fichier décennal {spans[0]}" if len(spans) == 1
                  else f"les fichiers décennaux {spans[0]} à {spans[-1]}")
        _stamp_provenance(tmp, source, "assemblé")
        with xr.open_dataset(tmp) as ds:
            debut = f"{pd.Timestamp(ds.time.min().values):%Y%m%d}"
            fin = f"{pd.Timestamp(ds.time.max().values):%Y%m%d}"
        output = directory / build_filename(VARIABLE, debut, fin)
        tmp.replace(output)

    report.line(f"{len(decades)} décennie(s) → "
                f"{report.humain(output.stat().st_size):>8s}   {chrono}   "
                f"{output.name}")
    return output


def sweep(directory: Path, keep: Path) -> list[Path]:
    """
    Retire les sorties d'un passage précédent, et les restes d'un assemblage coupé.

    Une sortie porte huit chiffres de chaque côté du tiret, une décennie quatre :
    les fichiers de travail ne sont donc jamais confondus avec le résultat.
    """
    motif = re.compile(rf"^{VARIABLE}_QUOT_SIM2_(\d{{8}}-\d{{8}}|tmp)\.nc$")
    perimes = [p for p in directory.glob(f"{VARIABLE}_QUOT_SIM2_*.nc")
               if motif.match(p.name) and p != keep]
    for p in perimes:
        p.unlink()
    if perimes:
        report.line(f"{len(perimes)} sortie(s) périmée(s) retirée(s) : "
                    f"{', '.join(sorted(p.name for p in perimes))}")
    return perimes


def default_grid_file() -> Path:
    """
    La grille de référence, prise dans la configuration du pipeline.

    Elle est versionnée sous un nom daté ; la lire dans la configuration plutôt
    que l'écrire ici évite qu'annexe et pipeline dérivent sur la grille, ce qui
    ferait deux fichiers qui ne se superposent plus.
    """
    load_dotenv()
    config_file = os.getenv("CONFIG_FILE", "config.json")
    if not Path(config_file).exists():
        raise SystemExit(f"\n❌ {config_file} introuvable. Donner la grille "
                         f"explicitement avec --grille.\n")
    config = json.loads(Path(config_file).read_text())
    return Path("resources") / config["METADATA_GRID_FILE"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Production annexe : l'ETP FAO Hargreaves au format du "
                    "pipeline. Rien n'est publié.")
    parser.add_argument("--dossier", default="annexe-etp", metavar="DOSSIER",
                        help="où vivent les sources et le résultat "
                             "(défaut : annexe-etp)")
    parser.add_argument("--grille", metavar="CSV",
                        help="grille de référence SAFRAN "
                             "(défaut : celle de config.json)")
    parser.add_argument("--decennies", nargs="+", metavar="SPAN",
                        help="ne traiter que ces décennies, ex. 1970-1979")
    parser.add_argument("--force", action="store_true",
                        help="reconvertir même ce qui est déjà à jour")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    directory = Path(args.dossier)
    directory.mkdir(parents=True, exist_ok=True)
    grid_file = Path(args.grille) if args.grille else default_grid_file()
    if not grid_file.exists():
        raise SystemExit(f"\n❌ grille introuvable : {grid_file}\n")
    if not VARIABLES_FILE.exists():
        raise SystemExit(f"\n❌ métadonnées introuvables : {VARIABLES_FILE}\n")

    report.banner("etp hargreaves")
    total = report.Chrono().__enter__()

    sources = list_sources()
    problems = check_inventory(sources)
    if problems:
        print()
        for problem in problems:
            print(f"   ❌ {problem}")
        raise SystemExit("\n   Le jeu amont n'a plus la forme attendue, "
                         "rien n'est produit.\n")
    if args.decennies:
        inconnues = sorted(set(args.decennies) - {s.span for s in sources})
        if inconnues:
            raise SystemExit(f"\n❌ décennie(s) inconnue(s) : "
                             f"{', '.join(inconnues)}\n")
        sources = [s for s in sources if s.span in args.decennies]

    report.phase("SOURCES", f"{len(sources)} décennie(s), "
                            f"{sources[0].debut} à {sources[-1].fin}, "
                            f"{report.humain(sum(s.size or 0 for s in sources))}")

    report.phase("TÉLÉCHARGEMENT", f"{len(sources)} fichier(s)")
    archives = [download(source, directory) for source in sources]

    report.phase("CONVERSION", f"{len(sources)} décennie(s)")
    decades = [convert_decade(gz, source.span, directory, grid_file,
                              force=args.force)
               for gz, source in zip(archives, sources)]

    report.phase("ASSEMBLAGE", f"{len(decades)} décennie(s)")
    output = assemble(decades, directory)
    # Jamais après un essai partiel : une sortie de deux décennies effacerait
    # la chronique entière produite au passage précédent.
    if not args.decennies:
        sweep(directory, keep=output)

    report.phase("CONTRÔLE", output.name)
    faults = check_file(output, first_day=FIRST_DAY)
    for fault in faults:
        report.detail(f"- {fault}")
    report.summary(sortie=output.name,
                   volume=report.humain(output.stat().st_size),
                   etat="rejetée" if faults else "saine",
                   duree=str(total))
    if faults:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Interruption par l'utilisateur")
        sys.exit(130)
    except Exception as error:
        print(f"\n❌ Erreur : {error}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
