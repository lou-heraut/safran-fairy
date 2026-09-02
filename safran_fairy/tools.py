# SPDX-FileCopyrightText: 2026 Louis Héraut <louis.heraut@inrae.fr>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared helpers, kept free of any dependency on the rest of the package."""

from __future__ import annotations

import re


# Two shapes are accepted on purpose, for as long as both coexist on the S3
# bucket: the target one, a single file per variable, and the legacy one that
# carried a historical / previous / latest token. "version" is None on the
# target shape.
_FILENAME = re.compile(
    r"^(?P<variable>[A-Za-z0-9_]+)_QUOT_SIM2_"
    r"(?:(?P<version>historical|previous|latest)-)?"
    r"(?P<date_debut>\d{8})-(?P<date_fin>\d{8})\.nc$"
)


def parse_filename(name: str) -> dict | None:
    """
    Lit un nom de fichier NetCDF produit par le pipeline.

    Args:
        name (str): nom de fichier seul, sans chemin.
                    Ex: « T_QUOT_SIM2_19580801-20260901.nc »

    Returns:
        dict | None: clés « variable », « version », « date_debut »,
                     « date_fin », ou None si le nom ne correspond pas.
                     « version » vaut None pour un fichier au nommage cible.
    """
    match = _FILENAME.match(name)
    if not match:
        return None
    return match.groupdict()


def build_filename(variable: str, date_debut: str, date_fin: str) -> str:
    """
    Construit le nom d'un fichier de sortie, au nommage cible.

    Args:
        variable (str):   nom de la variable Météo-France. Ex: « TINF_H »
        date_debut (str): première date de la chronique, en AAAAMMJJ.
        date_fin (str):   dernière date de la chronique, en AAAAMMJJ.

    Returns:
        str: ex. « TINF_H_QUOT_SIM2_19580801-20260901.nc »
    """
    return f"{variable}_QUOT_SIM2_{date_debut}-{date_fin}.nc"
