# SPDX-FileCopyrightText: 2026 Louis Héraut <louis.heraut@inrae.fr>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Decompress, split and convert, one source file at a time.

Running a whole stage before moving to the next made 44 Go of intermediates
coexist, all dead as soon as the next stage had read them. In a loop the peak
drops below 1 Go, and the chain becomes resumable where it stopped.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .convert import convert
from .decompress import decompress
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
    print(f"\nTRAITEMENT : {len(sources)} fichier(s) source, "
          f"{len(demandees)} variable(s)")

    traites = []
    for i, source in enumerate(sources, 1):
        source = Path(source)
        print(f"\n[{i}/{len(sources)}] {source.name}")
        if not overwrite and already_converted(source, demandees, CONVERT_DIR):
            print("   ⏭️  déjà converti, ignoré")
            continue

        csv_files = decompress(DOWNLOAD_DIR, RAW_DIR, [source])
        parquet_files = split(RAW_DIR, SPLIT_DIR, csv_files, variables=variables)
        convert(SPLIT_DIR, CONVERT_DIR, METADATA_VARIABLES_FILE, parquet_files,
                METADATA_GRID_FILE=METADATA_GRID_FILE)

        for temporaire in list(csv_files) + list(parquet_files):
            Path(temporaire).unlink(missing_ok=True)
        traites.append(source)

    return traites
