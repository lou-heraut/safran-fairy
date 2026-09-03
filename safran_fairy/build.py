# SPDX-FileCopyrightText: 2026 Louis Héraut <louis.heraut@inrae.fr>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Assemble one continuous NetCDF per variable from the yearly cache.

The rule is the same every day, with no state and no mutation:

    output(VAR) = concat(year_1958, …, year_N)
                  ++ rolling[ days strictly after the end of year_N ]

The yearly files are the only source of truth. The rolling window, which is not
consolidated upstream, never overrides a day a yearly file already covers: it
only extends past the last one. When Météo-France refreshes a year, the
provisional days it had supplied are replaced on their own.

Everything goes through a single plain « ncrcat », never « ncrcat -A », which
writes a reversed attribute name with NCO 5.2.1. See CLAUDE.md.
"""

from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import netCDF4

import pandas as pd
import xarray as xr
from art import tprint

from .tools import build_filename


# Files left by convert.py in CONVERT_DIR.
_YEAR = re.compile(r"^(?P<variable>[A-Za-z0-9_]+)_QUOT_SIM2_(?P<year>\d{4})\.nc$")
_ROLLING = re.compile(r"^(?P<variable>[A-Za-z0-9_]+)_QUOT_SIM2_latest\.nc$")


def _run(command: list[str]) -> None:
    """Run an NCO command and refuse to continue quietly if it fails."""
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"échec de « {' '.join(command[:2])} » : "
                           f"{result.stderr.strip() or result.stdout.strip()}")


def inventory(CONVERT_DIR) -> dict[str, dict]:
    """
    Range le cache converti par variable.

    Returns:
        dict: {variable: {"years": {année: Path}, "rolling": Path | None}}
    """
    found: dict[str, dict] = {}
    for path in sorted(Path(CONVERT_DIR).glob("*.nc")):
        match = _YEAR.match(path.name)
        if match:
            entry = found.setdefault(match["variable"], {"years": {}, "rolling": None})
            entry["years"][int(match["year"])] = path
            continue
        match = _ROLLING.match(path.name)
        if match:
            entry = found.setdefault(match["variable"], {"years": {}, "rolling": None})
            entry["rolling"] = path
    return found


def _last_day(path: Path) -> pd.Timestamp:
    with xr.open_dataset(path) as ds:
        return pd.Timestamp(ds.time.max().values)


def _stamp_provenance(path: Path, years: list[int], tail: Path | None) -> None:
    """
    Rewrite the global attributes ncrcat inherited from its first input.

    Left alone, the assembled file claims to come from the 1958 Parquet alone,
    which is a false provenance statement on the very file that gets published.
    """
    source = f"fichiers annuels {min(years)} à {max(years)}"
    if tail is not None:
        source += ", prolongés par la fenêtre glissante de 60 jours"
    with netCDF4.Dataset(path, "a") as ds:
        ds.setncattr("history", f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} : "
                                f"assemblé par safran-fairy depuis les {source}")
        ds.setncattr("source_files", source)


def _bounds(path: Path) -> tuple[str, str]:
    with xr.open_dataset(path) as ds:
        return (f"{pd.Timestamp(ds.time.min().values):%Y%m%d}",
                f"{pd.Timestamp(ds.time.max().values):%Y%m%d}")


def _rolling_tail(rolling: Path, after: pd.Timestamp, work_dir: Path) -> Path | None:
    """
    Extract from the rolling window the days that no yearly file covers.

    Returns None when it brings nothing, which is the normal case on the days
    following an upstream refresh of the current year.
    """
    first_wanted = (after + timedelta(days=1)).strftime("%Y-%m-%d")
    with xr.open_dataset(rolling) as ds:
        available = pd.Timestamp(ds.time.max().values)
    if available <= after:
        return None

    tail = work_dir / f"{rolling.stem}_tail.nc"
    _run(["ncrcat", "-h", "-O", "-d", f"time,{first_wanted},",
          str(rolling), str(tail)])
    return tail


def build_variable(variable: str, entry: dict, OUTPUT_DIR: Path) -> Path:
    """
    Construit le fichier de sortie d'une variable et rend son chemin.

    Le fichier est écrit sous un nom temporaire puis renommé avec sa couverture
    réelle, lue dans le résultat et non déduite des entrées.
    """
    years = entry["years"]
    if not years:
        raise RuntimeError(f"{variable} : aucun fichier annuel dans le cache")

    ordered = [years[y] for y in sorted(years)]
    last_year_day = _last_day(ordered[-1])

    pieces = list(ordered)
    tail = None
    if entry["rolling"]:
        tail = _rolling_tail(entry["rolling"], last_year_day, OUTPUT_DIR)
        if tail:
            pieces.append(tail)

    apport = ""
    if tail:
        debut, fin = _bounds(tail)
        apport = f", glissant du {debut} au {fin}"
    print(f"\n🧩 {variable} : {len(ordered)} année(s) "
          f"({min(years)} à {max(years)}){apport}")

    tmp = OUTPUT_DIR / f"{variable}_QUOT_SIM2_tmp.nc"
    _run(["ncrcat", "-h", "-O"] + [str(p) for p in pieces] + [str(tmp)])
    if tail:
        tail.unlink(missing_ok=True)

    _stamp_provenance(tmp, sorted(years), tail)
    date_debut, date_fin = _bounds(tmp)
    output = OUTPUT_DIR / build_filename(variable, date_debut, date_fin)
    tmp.replace(output)
    print(f"   💾 {output.name}")
    return output


def build(CONVERT_DIR, OUTPUT_DIR, variables: list[str] | None = None) -> list[Path]:
    """
    Assemble une chronique continue par variable depuis le cache annuel.

    Args:
        CONVERT_DIR (str | Path):        cache des NetCDF par variable et par année.
        OUTPUT_DIR (str | Path):         dossier de sortie, créé si absent.
        variables (list[str], optional): variables à assembler. Si None, toutes
                                         celles présentes dans le cache.

    Returns:
        list[Path]: les fichiers assemblés, un par variable.
    """
    tprint("build", "small")

    OUTPUT_DIR = Path(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    found = inventory(CONVERT_DIR)
    if variables:
        inconnues = sorted(set(variables) - set(found))
        if inconnues:
            raise RuntimeError(f"absente(s) du cache : {', '.join(inconnues)}")
        found = {v: found[v] for v in variables}

    print("ASSEMBLAGE")
    print(f"   → {len(found)} variable(s) : {', '.join(sorted(found))}")

    built = []
    for i, variable in enumerate(sorted(found), 1):
        print(f"\n[{i}/{len(found)}]", end="")
        built.append(build_variable(variable, found[variable], OUTPUT_DIR))

    print("\nRÉSUMÉ")
    print(f"   - {len(built)} fichier(s) assemblé(s)")
    print(f"   - 📁 Dossier : {os.path.abspath(OUTPUT_DIR)}")
    return built
