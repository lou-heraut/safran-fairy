# SPDX-FileCopyrightText: 2026 Louis Héraut <louis.heraut@inrae.fr>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Cut each source CSV into one Parquet file per climate variable.

The CSV are read in chunks: a yearly file weighs several hundred megabytes
uncompressed and holds 26 variables side by side.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .report import banner, humain, line, phase, summary


ID_COLUMNS = ["LAMBX", "LAMBY", "DATE"]
CHUNK_SIZE = 500_000


def split_file(input_file, SPLIT_DIR, variables: list[str] | None = None,
               chunk_size: int = CHUNK_SIZE) -> list[Path]:
    """
    Découpe un CSV en un fichier Parquet par variable.

    Args:
        input_file (str | Path):        CSV décompressé à découper.
        SPLIT_DIR (str | Path):         dossier de sortie, créé si absent.
        variables (list[str], optional): variables à extraire. Si None, toutes.
                                        Sert à alléger un essai sur une seule.
        chunk_size (int):               nombre de lignes lues à la fois.

    Returns:
        list[Path]: les fichiers Parquet écrits.
    """
    input_file = Path(input_file)
    SPLIT_DIR = Path(SPLIT_DIR)
    SPLIT_DIR.mkdir(parents=True, exist_ok=True)
    base_name = input_file.stem


    header = pd.read_csv(input_file, sep=";", nrows=0)
    available = [c for c in header.columns if c not in ID_COLUMNS]

    if variables is None:
        wanted = available
    else:
        wanted = [v for v in variables if v in available]
        manquantes = sorted(set(variables) - set(available))
        if manquantes:
            raise RuntimeError(f"{input_file.name} : variable(s) absente(s) "
                               f"du CSV : {', '.join(manquantes)}")

    outputs = {var: SPLIT_DIR / f"{var}_{base_name}.parquet" for var in wanted}
    writers: dict[str, pq.ParquetWriter] = {}

    columns = ID_COLUMNS + wanted
    try:
        for chunk in pd.read_csv(input_file, sep=";", usecols=columns,
                                 chunksize=chunk_size):
            for var in wanted:
                table = pa.Table.from_pandas(chunk[ID_COLUMNS + [var]],
                                             preserve_index=False)
                if var not in writers:
                    writers[var] = pq.ParquetWriter(outputs[var], table.schema,
                                                    compression="snappy")
                writers[var].write_table(table)
    finally:
        for writer in writers.values():
            writer.close()

    return list(outputs.values())


def split(RAW_DIR, SPLIT_DIR, decompressed_files=None,
          variables: list[str] | None = None,
          verbose: bool = True) -> list[Path]:
    """
    Découpe les CSV bruts en fichiers Parquet, un par variable et par fichier source.

    Args:
        RAW_DIR (str | Path):           dossier des CSV décompressés.
        SPLIT_DIR (str | Path):         dossier de sortie, créé si absent.
        decompressed_files (list[Path], optional): CSV à traiter. Si None, tous
                                                   les *.csv de RAW_DIR.
        variables (list[str], optional): variables à extraire. Si None, toutes.

    Returns:
        list[Path]: à plat, tous les fichiers Parquet écrits.
    """
    Path(SPLIT_DIR).mkdir(parents=True, exist_ok=True)
    if decompressed_files is None:
        decompressed_files = sorted(Path(RAW_DIR).glob("*.csv"))

    if verbose:
        banner("split")
        phase("DÉCOUPAGE", f"{len(decompressed_files)} fichier(s) source")

    splited_files: list[Path] = []
    for i, file in enumerate(decompressed_files, 1):
        ecrits = split_file(file, SPLIT_DIR, variables=variables)
        splited_files += ecrits
        if verbose:
            line(f"[{i}/{len(decompressed_files)}] {Path(file).name} → "
                 f"{len(ecrits)} variable(s)")

    if verbose:
        summary(parquet=len(splited_files),
                volume=humain(sum(f.stat().st_size for f in splited_files)))
    return splited_files
