# SPDX-FileCopyrightText: 2026 Louis Héraut <louis.heraut@inrae.fr>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Everything the pipeline knows about the shape of the data.gouv.fr dataset.

Météo-France recomposed the SIM2 dataset on 31 July 2026: yearly files instead
of decades, no date left in any file name, and a single rolling window replacing
the previous / latest pair. This module is the one place that changes if they do
it again. Nothing downstream should ever read a source file name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import requests


# Yearly consolidated file, one per year since 1958. Refreshed twice a month
# for the last four years, so a past year is not frozen.
_YEAR = re.compile(r"^QUOT_SIM2_(?P<year>\d{4})\.csv\.gz$")
# Rolling window, 60 days, refreshed daily. Never consolidated.
_ROLLING = re.compile(r"^QUOT_SIM2_latest\.csv\.gz$")

FIRST_YEAR = 1958


@dataclass(frozen=True)
class Resource:
    """One downloadable file of the dataset."""

    id: str
    filename: str
    url: str
    last_modified: str
    size: int | None
    kind: str        # "year", "rolling" or "other"
    year: int | None  # only set when kind == "year"

    @property
    def is_data(self) -> bool:
        return self.kind in ("year", "rolling")


def _classify(filename: str) -> tuple[str, int | None]:
    match = _YEAR.match(filename)
    if match:
        return "year", int(match["year"])
    if _ROLLING.match(filename):
        return "rolling", None
    return "other", None


def _filename_of(resource: dict) -> str:
    """The name the file takes on disk, read from its URL and not its title."""
    return resource.get("url", "").split("/")[-1].split("?")[0]


def to_resource(raw: dict) -> Resource:
    """Turn one raw data.gouv.fr resource into a Resource."""
    filename = _filename_of(raw)
    kind, year = _classify(filename)
    extras = raw.get("extras") or {}
    # "filesize" is empty on remote files; the availability check knows the size.
    size = raw.get("filesize") or extras.get("check:headers:content-length")
    return Resource(
        id=raw["id"],
        filename=filename,
        url=raw.get("url", ""),
        last_modified=raw.get("last_modified", ""),
        size=int(size) if size else None,
        kind=kind,
        year=year,
    )


def list_resources(METEO_BASE_URL: str, METEO_DATASET_ID: str) -> list[Resource]:
    """
    Interroge l'API data.gouv.fr et rend les ressources du jeu, classées.

    Args:
        METEO_BASE_URL (str):   racine de l'API data.gouv.fr.
        METEO_DATASET_ID (str): identifiant du jeu de données.

    Returns:
        list[Resource]: toutes les ressources, documents compris. Utiliser
                        « kind » pour ne garder que les fichiers de données.
    """
    response = requests.get(METEO_BASE_URL + METEO_DATASET_ID + "/")
    response.raise_for_status()
    return [to_resource(raw) for raw in response.json().get("resources", [])]


def data_resources(resources: list[Resource]) -> list[Resource]:
    """Les fichiers de données seuls, années triées puis le glissant."""
    years = sorted((r for r in resources if r.kind == "year"), key=lambda r: r.year)
    rolling = [r for r in resources if r.kind == "rolling"]
    return years + rolling


def describe(resources: list[Resource]) -> str:
    """Une ligne de résumé, pour les journaux."""
    years = [r.year for r in resources if r.kind == "year"]
    rolling = sum(1 for r in resources if r.kind == "rolling")
    others = sum(1 for r in resources if r.kind == "other")
    span = f"{min(years)} à {max(years)}" if years else "aucune"
    return (f"{len(years)} fichier(s) annuel(s) ({span}), "
            f"{rolling} glissant(s), {others} autre(s) ressource(s)")


def check_inventory(resources: list[Resource]) -> list[str]:
    """
    Contrôle que le dépôt amont a toujours la forme attendue.

    Sert de détecteur de changement de format : si Météo-France recompose à
    nouveau le jeu, le pipeline doit s'en apercevoir et le dire, pas produire
    silencieusement une chronique tronquée.

    Returns:
        list[str]: les anomalies constatées. Liste vide si tout est conforme.
    """
    problems = []
    years = sorted(r.year for r in resources if r.kind == "year")
    rolling = [r for r in resources if r.kind == "rolling"]

    if not years:
        problems.append("aucun fichier annuel reconnu, le format amont a changé")
        return problems

    if years[0] != FIRST_YEAR:
        problems.append(f"la première année est {years[0]} et non {FIRST_YEAR}")

    manquantes = sorted(set(range(years[0], years[-1] + 1)) - set(years))
    if manquantes:
        problems.append(f"année(s) manquante(s) : {manquantes}")

    doublons = sorted({y for y in years if years.count(y) > 1})
    if doublons:
        problems.append(f"année(s) en double : {doublons}")

    if len(rolling) != 1:
        problems.append(f"{len(rolling)} fichier(s) glissant(s) au lieu d'un seul")

    return problems
