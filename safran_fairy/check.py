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

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import xarray as xr

from .report import banner, detail, line, phase, summary

from .convert import read_grid
from .tools import parse_filename


# Measured on the sound files of the archive, not deduced from documentation.
FIRST_DAY = pd.Timestamp("1958-08-01")  # début de l'archive SIM2, valeur par défaut
GRID_SHAPE = (134, 143)  # (y, x), grille complète : une colonne ne porte aucun point
GRID_POINTS = 9892       # cells of the SAFRAN domain inside that rectangle
SAMPLED_STEPS = 6        # time steps read in full to inspect the grid


def _check_time(ds: xr.Dataset, parsed: dict,
                first_day: pd.Timestamp = FIRST_DAY) -> list[str]:
    """Everything that can go wrong with the time axis.

    "first_day" is the day the record is expected to start on. It is an
    argument and not a constant only so that a file built from another
    Météo-France dataset on the same grid can be checked by the same code:
    the assertion is moved, never relaxed.
    """
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

    if time[0] != first_day:
        problems.append(f"commence le {time[0].date()} "
                        f"et non le {first_day.date()}")

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

    # « time: sum time: mean » déclare deux traitements pour la même dimension,
    # donc n'en déclare aucun. NCO 5.0.6 écrivait cela tout seul en concaténant,
    # sur 18 des 26 variables, celles dont l'étiquette n'était pas « time: mean ».
    methodes = re.findall(r"(\w+)\s*:", data.attrs.get("cell_methods", ""))
    repetees = sorted({nom for nom in methodes if methodes.count(nom) > 1})
    if repetees:
        problems.append(f"« cell_methods » déclare plusieurs méthodes pour "
                        f"{', '.join(repetees)} : {data.attrs['cell_methods']!r}")

    # La même annotation en posait une sur la coordonnée temporelle, où CF n'en
    # attend pas : cell_methods décrit une variable, jamais son axe.
    portantes = [nom for nom in ("time", "x", "y")
                 if nom in ds.variables and "cell_methods" in ds[nom].attrs]
    if portantes:
        problems.append(f"« cell_methods » posé sur la ou les coordonnées "
                        f"{', '.join(portantes)}, où CF n'en attend pas")

    if "crs" not in ds.variables:
        problems.append("variable « crs » absente, le géoréférencement est perdu")

    return problems


def check_file(path, first_day: pd.Timestamp = FIRST_DAY) -> list[str]:
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
            problems += _check_time(ds, parsed, first_day)
            problems += _check_grid(ds, variable)
        else:
            problems += _check_time(ds, parsed, first_day)
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
    banner("check")

    if paths is None:
        if OUTPUT_DIR is None:
            raise ValueError("check() attend soit paths, soit OUTPUT_DIR")
        paths = sorted(Path(OUTPUT_DIR).glob("*.nc"))
    paths = [Path(p) for p in paths]

    phase("CONTRÔLE", f"{len(paths)} fichier(s)")

    failed = []
    for i, path in enumerate(paths, 1):
        problems = check_file(path)
        if problems:
            failed.append(path)
            line(f"❌ {path.name}")
            for problem in problems:
                detail(f"- {problem}")
        else:
            line(f"✅ {path.name}")

    summary(sains=len(paths) - len(failed), rejetes=len(failed))
    if failed:
        line("⚠️  aucune publication ne doit avoir lieu")

    return failed


# ─── Le catalogue ────────────────────────────────────────────────────────────
#
# Le pendant, pour les documents STAC, de ce que les fonctions ci dessus font
# pour les NetCDF. Il n'existait pas, et deux défauts sont passés faute de lui :
# des items invalides sur « 'collection' is a required property », en ligne des
# mois durant sans que STAC Browser, tolérant, le montre ; et une emprise qui
# laissait la Corse dehors, trouvée à l'œil sur une carte.
#
# Le contrôle porte sur les fichiers écrits localement, avant l'envoi, et sur
# les assets déjà en ligne qu'ils désignent.


def _stac_schema(path: Path) -> tuple[list[str], list[str]]:
    """
    La conformité au schéma STAC, si « stac_valid » est installé.

    La dépendance est facultative, comme le dit requirements.txt : son absence
    retire ce contrôle et laisse tous les autres, elle ne fait échouer personne.

    Les schémas sont récupérés sur schemas.stacspec.org. Un document qui les
    viole est refusé ; un schéma qu'on n'a pas pu atteindre ne prouve rien et
    ne doit donc pas arrêter une publication, sans quoi la panne d'un service
    tiers suffirait à interrompre le service.

    Returns:
        tuple[list[str], list[str]]: les violations, puis ce qui n'a pas pu
            être vérifié.
    """
    try:
        from stac_validator.stac_validator import StacValidate
    except ImportError:
        return [], []

    try:
        validateur = StacValidate(str(path))
        if validateur.run():
            return [], []
        messages = validateur.message
    except Exception as error:
        return [], [f"schéma non vérifié : {type(error).__name__} {error}"]

    problems, reserves = [], []
    for message in messages:
        detail_message = message.get("error_message") or message.get("error_type", "?")
        if message.get("error_type") == "JSONSchemaValidationError":
            problems.append(f"invalide pour le schéma STAC : {detail_message}")
        else:
            reserves.append(f"schéma non vérifié : {detail_message}")
    return problems, reserves


def _check_item(doc: dict, attendues: set, enveloppe: tuple,
                verifier_assets: bool) -> tuple[list[str], list[str]]:
    """
    Un item : sa variable, son emprise, et le fichier qu'il désigne.

    Returns:
        tuple[list[str], list[str]]: ce qui interdit de publier, puis ce qui
            mérite d'être dit sans l'interdire.
    """
    problems, avertissements = [], []

    variable = doc.get("id", "").removesuffix("_SIM2")
    if attendues and variable not in attendues:
        problems.append(f"variable « {variable} » absente du fichier de "
                        f"métadonnées : rien ne doit publier ce qui n'est pas "
                        f"déclaré")
    if not doc.get("collection"):
        problems.append("sans « collection », ce qui rend l'item invalide")

    # L'emprise doit contenir toute la grille. Une bbox trop petite est passée
    # inaperçue un mois : elle valait celle de la France continentale.
    bbox = doc.get("bbox")
    if not bbox or len(bbox) != 4:
        problems.append("sans emprise exploitable")
    else:
        ouest, sud, est, nord = enveloppe
        if not (bbox[0] <= ouest and bbox[1] <= sud
                and bbox[2] >= est and bbox[3] >= nord):
            problems.append(
                f"emprise [{bbox[0]:.3f}, {bbox[1]:.3f}, {bbox[2]:.3f}, "
                f"{bbox[3]:.3f}] ne couvre pas la grille de référence "
                f"[{ouest:.3f}, {sud:.3f}, {est:.3f}, {nord:.3f}]")

    debut = doc.get("properties", {}).get("start_datetime")
    fin = doc.get("properties", {}).get("end_datetime")
    if not debut or not fin:
        problems.append("sans bornes temporelles")
    elif debut > fin:
        problems.append(f"bornes temporelles inversées, {debut} après {fin}")

    assets = doc.get("assets") or {}
    if not assets:
        problems.append("sans asset, l'item ne mène à aucun fichier")
    for nom, asset in assets.items():
        # L'empreinte est calculée sur la copie locale du fichier, donc elle
        # est toujours là quand le catalogue est fabriqué sur la machine qui
        # publie. Qu'elle manque signale que ce n'est pas le cas, ou que la
        # copie locale ne correspond plus à ce qui est en ligne : dans les deux
        # cas quelque chose d'anormal, et rien ne doit partir.
        if "file:checksum" not in asset:
            problems.append(f"asset « {nom} » sans empreinte")
        if not verifier_assets:
            continue
        # Une panne de réseau ne dit rien du fichier : elle empêche seulement
        # de le vérifier. La confondre avec un défaut ferait échouer un run de
        # nuit sur un incident passager, alors que les données, elles, sont
        # déjà en ligne.
        try:
            reponse = requests.head(asset["href"], timeout=30)
        except requests.RequestException as error:
            avertissements.append(f"asset « {nom} » non vérifié : "
                                  f"{type(error).__name__}")
            continue
        if reponse.status_code != 200:
            problems.append(f"asset « {nom} » : HTTP {reponse.status_code} "
                            f"sur {asset['href']}")
        elif int(reponse.headers.get("content-length", 0)) != asset.get("file:size"):
            problems.append(f"asset « {nom} » annoncé à {asset.get('file:size')} "
                            f"octets pour {reponse.headers.get('content-length')} "
                            f"en ligne")
    return problems, avertissements


def _check_collection(doc: dict, attendues: set) -> list[str]:
    """Une collection : sa licence, et qu'il ne manque aucune variable."""
    problems = []

    items = [lien for lien in doc.get("links", []) if lien.get("rel") == "item"]
    if attendues and len(items) != len(attendues):
        problems.append(f"{len(items)} item(s) pour {len(attendues)} variable(s) "
                        f"attendue(s)")

    # Les données ne sont pas sous la licence du code : le confondre serait une
    # affirmation fausse sur des données qui ne nous appartiennent pas.
    licences = [lien for lien in doc.get("links", []) if lien.get("rel") == "license"]
    if not licences:
        problems.append("sans lien « license »")
    elif any("gpl" in (lien.get("href", "") + lien.get("title", "")).lower()
             for lien in licences):
        problems.append("déclare une licence GPL, or les données SIM2 sont sous "
                        "Licence Ouverte 2.0")
    return problems


def check_catalog(stac_files, METADATA_VARIABLES_FILE=None,
                  METADATA_GRID_FILE=None, verifier_assets: bool = True) -> list[Path]:
    """
    Contrôle les documents STAC avant leur publication.

    Args:
        stac_files (list[Path]): les fichiers écrits par generate_stac_catalog.
        METADATA_VARIABLES_FILE (str | Path, optional): pour savoir quelles
            variables doivent être décrites, et lesquelles n'ont rien à y faire.
        METADATA_GRID_FILE (str | Path, optional): grille de référence, pour
            vérifier que l'emprise annoncée la couvre.
        verifier_assets (bool): interroger le bucket pour chaque asset.

    Returns:
        list[Path]: les fichiers qui ont échoué. Liste vide si tout est sain.
                    L'appelant ne doit rien publier si elle ne l'est pas.
    """
    banner("check")

    stac_files = [Path(p) for p in stac_files]
    phase("CONTRÔLE DU CATALOGUE", f"{len(stac_files)} document(s)")

    attendues = set()
    if METADATA_VARIABLES_FILE and Path(METADATA_VARIABLES_FILE).exists():
        attendues = set(pd.read_csv(METADATA_VARIABLES_FILE)["variable"])
    enveloppe = None
    if METADATA_GRID_FILE and Path(METADATA_GRID_FILE).exists():
        grid = read_grid(METADATA_GRID_FILE)
        enveloppe = (grid["lon"].min(), grid["lat"].min(),
                     grid["lon"].max(), grid["lat"].max())

    failed, signales = [], 0
    for path in stac_files:
        try:
            doc = json.loads(path.read_text())
        except Exception as error:
            failed.append(path)
            line(f"❌ {path.name}")
            detail(f"- illisible : {error}")
            continue

        problems, avertissements = _stac_schema(path)
        if doc.get("type") == "Feature":
            trouves, reserves = _check_item(
                doc, attendues, enveloppe or (0, 0, 0, 0),
                verifier_assets and enveloppe is not None)
            problems += trouves
            avertissements += reserves
        elif doc.get("type") == "Collection":
            problems += _check_collection(doc, attendues)
        elif doc.get("type") == "Catalog":
            if not any(lien.get("rel") == "child" for lien in doc.get("links", [])):
                problems.append("catalogue racine sans aucun enfant")

        if problems:
            failed.append(path)
            line(f"❌ {path.name}")
            for problem in problems:
                detail(f"- {problem}")
        elif avertissements:
            signales += 1
            line(f"⚠️  {path.name}")
            for avertissement in avertissements:
                detail(f"- {avertissement}")

    summary(sains=len(stac_files) - len(failed), rejetes=len(failed),
            avec_reserve=signales)
    if failed:
        line("⚠️  le catalogue ne doit pas être publié dans cet état")
    return failed
