# SPDX-FileCopyrightText: 2026 Louis Héraut <louis.heraut@inrae.fr>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Decompress, split and convert, one source file at a time.

Running a whole stage before moving to the next made 44 Go of intermediates
coexist, all dead as soon as the next stage had read them. In a loop the peak
drops below 1 Go, and the chain becomes resumable where it stopped.

The three steps are told to keep quiet: their own banners and summaries were
written for a run where each happened once, and repeating them for every source
buries the one thing worth reading. This module reports instead, one line per
file.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .convert import convert
from .decompress import decompress
from .report import Chrono, banner, humain, line, phase, summary
from .split import split


def wanted_variables(METADATA_VARIABLES_FILE, variables=None) -> list[str]:
    """Les variables demandées, ou toutes celles que le fichier de métadonnées décrit."""
    if variables:
        return list(variables)
    return list(pd.read_csv(METADATA_VARIABLES_FILE)["variable"])


def already_converted(source: Path, variables, CONVERT_DIR) -> bool:
    """
    Si tous les NetCDF annuels de cette source existent et lui sont postérieurs.

    C'est cette règle qui rend gratuit le parcours de toutes les sources, et
    donc qui permet de ne jamais restreindre le traitement au dernier lot
    téléchargé : mesuré à 6 ms pour 70 sources sur 26 variables.
    """
    annee = source.name[: -len(".csv.gz")].split("QUOT_SIM2_")[-1]
    horodatage = source.stat().st_mtime
    cibles = [Path(CONVERT_DIR) / f"{v}_QUOT_SIM2_{annee}.nc" for v in variables]
    return all(c.exists() and c.stat().st_mtime >= horodatage for c in cibles)


def process(sources, DOWNLOAD_DIR, RAW_DIR, SPLIT_DIR, CONVERT_DIR,
            METADATA_VARIABLES_FILE, METADATA_GRID_FILE=None,
            variables=None, overwrite=False) -> list[Path]:
    """
    Traite les fichiers source un par un, du .csv.gz au NetCDF annuel.

    Args:
        sources (list[Path]):  fichiers .csv.gz à traiter.
        variables (list[str], optional): variables à extraire. Si None, toutes.
        overwrite (bool):      retraiter même ce qui est déjà converti.

    Returns:
        list[Path]: les fichiers source effectivement traités.

    Notes:
        - Le CSV et les Parquet ne sont supprimés qu'une fois la conversion
          réussie : un échec laisse de quoi regarder ce qui s'est passé.
    """
    demandees = wanted_variables(METADATA_VARIABLES_FILE, variables)
    banner("traitement")
    phase("TRAITEMENT", f"{len(sources)} fichier(s) source, "
                        f"{len(demandees)} variable(s)")

    traites, ignores, volume = [], 0, 0
    with Chrono() as total:
        for i, source in enumerate(sources, 1):
            source = Path(source)
            rang = f"[{i}/{len(sources)}] {source.name:26s}"

            if not overwrite and already_converted(source, demandees, CONVERT_DIR):
                ignores += 1
                line(f"{rang} déjà converti, ignoré")
                continue

            with Chrono() as chrono:
                csv_files = decompress(DOWNLOAD_DIR, RAW_DIR, [source],
                                       verbose=False)
                brut = sum(Path(f).stat().st_size for f in csv_files)
                parquet_files = split(RAW_DIR, SPLIT_DIR, csv_files,
                                      variables=variables, verbose=False)
                netcdf = convert(SPLIT_DIR, CONVERT_DIR, METADATA_VARIABLES_FILE,
                                 parquet_files,
                                 METADATA_GRID_FILE=METADATA_GRID_FILE,
                                 verbose=False)
                for temporaire in list(csv_files) + list(parquet_files):
                    Path(temporaire).unlink(missing_ok=True)

            volume += brut
            traites.append(source)
            line(f"{rang} {humain(brut):>9s} → {len(netcdf):2d} NetCDF   {chrono}")

    summary(sources=len(sources), traitees=len(traites), ignorees=ignores,
            lu=humain(volume), duree=str(total))
    return traites
