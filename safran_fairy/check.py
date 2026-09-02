# SPDX-FileCopyrightText: 2026 Louis Héraut <louis.heraut@inrae.fr>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Structural checks on the NetCDF files produced by the pipeline.

A file that fails a blocking check must never be published. This module exists
because of what happened on 4 August 2026: a series whose time axis was not
monotonic, holding the whole record twice, went online and stayed there for a
month without anything noticing.

The checks are deliberately about structure, never about plausible values. The
pipeline transposes the data, it does not judge it.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from art import tprint

from .tools import parse_filename


# Measured on the sound files of the archive, not deduced from documentation.
FIRST_DAY = pd.Timestamp("1958-08-01")
GRID_SHAPE = (134, 142)  # (y, x)
GRID_POINTS = 9892       # cells of the SAFRAN domain inside that rectangle
SAMPLED_STEPS = 6        # time steps read in full to inspect the grid


def _check_time(ds: xr.Dataset, parsed: dict) -> list[str]:
    """Everything that can go wrong with the time axis."""
    problems = []
    time = pd.DatetimeIndex(ds.time.values)

    if len(time) == 0:
        return ["axe temporel vide"]

    if not time.is_unique:
        n = len(time) - time.nunique()
        problems.append(f"{n} pas de temps en double "
                        f"({len(time)} pas pour {time.nunique()} dates)")

    if not time.is_monotonic_increasing:
        steps = np.diff(time.values.astype("int64"))
        breaks = np.where(steps <= 0)[0]
        where = ", ".join(f"{time[i].date()} suivi de {time[i + 1].date()}"
                          for i in breaks[:3])
        problems.append(f"axe temporel non monotone, "
                        f"{len(breaks)} rupture(s) : {where}")

    # Gaps are reported on their own: a monotonic axis can still miss days.
    gaps = pd.Series(time).diff().dropna()
    holes = gaps[gaps > pd.Timedelta(days=1)]
    if len(holes):
        first = time[holes.index[0] - 1].date()
        problems.append(f"{len(holes)} trou(s) dans la chronique, "
                        f"le premier après le {first}")

    if time[0] != FIRST_DAY:
        problems.append(f"commence le {time[0].date()} "
                        f"et non le {FIRST_DAY.date()}")

    # The file name announces a coverage: it must be the real one.
    for label, announced, real in [("début", parsed["date_debut"], time[0]),
                                   ("fin", parsed["date_fin"], time[-1])]:
        if announced != f"{real:%Y%m%d}":
            problems.append(f"{label} annoncé {announced} dans le nom "
                            f"mais {real:%Y%m%d} dans le fichier")

    return problems


def _check_grid(ds: xr.Dataset, variable: str) -> list[str]:
    """Shape, coordinates and coverage of the spatial grid."""
    problems = []

    for axis in ("x", "y"):
        if axis not in ds.coords:
            problems.append(f"coordonnée « {axis} » absente")
    if problems:
        return problems

    # The SAFRAN grid is not regular: x has both 8 km and 16 km steps, because
    # a column of the rectangle holds no point. Only strict growth is required.
    for axis in ("x", "y"):
        values = ds[axis].values
        if not np.all(np.diff(values) > 0):
            problems.append(f"coordonnée « {axis} » non strictement croissante")

    shape = (ds.sizes.get("y"), ds.sizes.get("x"))
    if shape != GRID_SHAPE:
        problems.append(f"grille {shape[0]} x {shape[1]} "
                        f"au lieu de {GRID_SHAPE[0]} x {GRID_SHAPE[1]}")
        return problems

    data = ds[variable]
    n_time = ds.sizes["time"]
    steps = sorted(set(np.linspace(0, n_time - 1, SAMPLED_STEPS).astype(int)))
    counts = {i: int(np.isfinite(data.isel(time=i).values).sum()) for i in steps}

    too_many = {i: c for i, c in counts.items() if c > GRID_POINTS}
    if too_many:
        problems.append(f"plus de {GRID_POINTS} points renseignés à certains pas "
                        f"de temps : {too_many}")

    last = counts[steps[-1]]
    if last != GRID_POINTS:
        problems.append(f"{last} points renseignés au dernier pas de temps "
                        f"au lieu de {GRID_POINTS}")

    return problems


def _check_variable(ds: xr.Dataset, variable: str) -> list[str]:
    """Presence, type and metadata of the climate variable."""
    problems = []

    if variable not in ds.variables:
        return [f"variable « {variable} » absente du fichier "
                f"(présentes : {', '.join(sorted(ds.data_vars))})"]

    data = ds[variable]
    if data.dtype != np.float32:
        problems.append(f"variable en {data.dtype} et non en float32")

    if data.dims != ("time", "y", "x"):
        problems.append(f"dimensions {data.dims} au lieu de (time, y, x)")

    for attribute in ("long_name", "units", "grid_mapping"):
        if attribute not in data.attrs:
            problems.append(f"attribut « {attribute} » manquant sur la variable")

    # Attribute names written backwards have been observed on files produced by
    # older versions of the chain, "eulaVlliF_" for "_FillValue" among them.
    reversed_names = [name for name in data.attrs
                      if name[::-1] in ("_FillValue", "units", "long_name")]
    if reversed_names:
        problems.append(f"nom(s) d'attribut inversé(s) : {', '.join(reversed_names)}")

    if "crs" not in ds.variables:
        problems.append("variable « crs » absente, le géoréférencement est perdu")

    return problems


def check_file(path) -> list[str]:
    """Return the list of problems found on one NetCDF file, empty if sound."""
    path = Path(path)

    parsed = parse_filename(path.name)
    if parsed is None:
        return [f"nom de fichier non conforme : {path.name}"]

    try:
        ds = xr.open_dataset(path)
    except Exception as error:
        return [f"ouverture impossible : {error}"]

    try:
        variable = parsed["variable"]
        problems = _check_variable(ds, variable)
        # The grid checks need the variable, so they only run once it is there.
        if not any(p.startswith("variable «") for p in problems):
            problems += _check_time(ds, parsed)
            problems += _check_grid(ds, variable)
        else:
            problems += _check_time(ds, parsed)
    finally:
        ds.close()

    return problems


def check(paths=None, OUTPUT_DIR=None) -> list[Path]:
    """
    Contrôle structurel des fichiers NetCDF avant publication.

    Args:
        paths (list[Path], optional): fichiers à contrôler. Si None, tous les
                                      *.nc de OUTPUT_DIR.
        OUTPUT_DIR (str | Path, optional): dossier à parcourir si paths est None.

    Returns:
        list[Path]: les fichiers qui ont échoué. Liste vide si tout est sain.
                    L'appelant ne doit rien publier si elle ne l'est pas.
    """
    tprint("check", "small")

    if paths is None:
        if OUTPUT_DIR is None:
            raise ValueError("check() attend soit paths, soit OUTPUT_DIR")
        paths = sorted(Path(OUTPUT_DIR).glob("*.nc"))
    paths = [Path(p) for p in paths]

    print("CONTRÔLE")
    print(f"   → {len(paths)} fichier(s) à contrôler")

    failed = []
    for i, path in enumerate(paths, 1):
        problems = check_file(path)
        if problems:
            failed.append(path)
            print(f"\n[{i}/{len(paths)}] ❌ {path.name}")
            for problem in problems:
                print(f"   - {problem}")
        else:
            print(f"\n[{i}/{len(paths)}] ✅ {path.name}")

    print("\nRÉSUMÉ")
    print(f"   - ✅ Sains : {len(paths) - len(failed)}")
    print(f"   - ❌ Rejetés : {len(failed)}")
    if failed:
        print("   - ⚠️  Aucune publication ne doit avoir lieu")

    return failed
