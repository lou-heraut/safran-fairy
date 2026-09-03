# SPDX-FileCopyrightText: 2026 Louis Héraut <louis.heraut@inrae.fr>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Expand the downloaded .csv.gz into raw CSV."""

from __future__ import annotations

import gzip
import shutil
from pathlib import Path

from .report import banner, humain, line, phase, summary
from .sources import is_data_filename


def decompress_file(gz_file, RAW_DIR) -> Path:
    """Décompresse un .gz dans RAW_DIR et rend le chemin du CSV."""
    output_file = Path(RAW_DIR) / Path(gz_file).stem
    with gzip.open(gz_file, "rb") as source, open(output_file, "wb") as cible:
        shutil.copyfileobj(source, cible)
    return output_file


def decompress(DOWNLOAD_DIR, RAW_DIR, downloaded_files=None,
               verbose: bool = True) -> list[Path]:
    """
    Décompresse les .csv.gz en CSV bruts.

    Args:
        DOWNLOAD_DIR (str | Path): dossier des .csv.gz.
        RAW_DIR (str | Path):      dossier de destination, créé si absent.
        downloaded_files (list[Path], optional): fichiers à traiter. Si None,
                                                 tous les .csv.gz reconnus.
        verbose (bool):            False quand l'appelant rend compte lui-même,
                                   ce qui est le cas dans la boucle de traitement.

    Returns:
        list[Path]: les CSV écrits.
    """
    Path(RAW_DIR).mkdir(parents=True, exist_ok=True)
    if downloaded_files is None:
        downloaded_files = sorted(f for f in Path(DOWNLOAD_DIR).glob("*.csv.gz")
                                  if is_data_filename(f.name))

    if verbose:
        banner("decompress")
        phase("DÉCOMPRESSION", f"{len(downloaded_files)} fichier(s)")

    decompressed = []
    for i, file in enumerate(downloaded_files, 1):
        output_file = decompress_file(file, RAW_DIR)
        decompressed.append(output_file)
        if verbose:
            line(f"[{i}/{len(downloaded_files)}] {Path(file).name} → "
                 f"{humain(output_file.stat().st_size)}")

    if verbose:
        summary(fichiers=len(decompressed),
                volume=humain(sum(f.stat().st_size for f in decompressed)))
    return decompressed
