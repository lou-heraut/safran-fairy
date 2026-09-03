# SPDX-FileCopyrightText: 2026 Louis Héraut <louis.heraut@inrae.fr>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the STAC catalogue describing what is published on the bucket.

The catalogue is generated from the bucket itself, never from the local output
folder: what it describes is what is actually online.

One collection holding one item per variable. The per variable sub collections
of the previous version served no purpose once a variable maps to a single file.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import boto3
import pandas as pd

from .convert import regular_axes
from .tools import parse_filename


STAC_VERSION = "1.1.0"
EXTENSIONS = [
    "https://stac-extensions.github.io/datacube/v2.2.0/schema.json",
    "https://stac-extensions.github.io/projection/v2.0.0/schema.json",
    "https://stac-extensions.github.io/scientific/v1.0.0/schema.json",
    "https://stac-extensions.github.io/processing/v1.2.0/schema.json",
]

# Envelope of the SAFRAN domain in WGS 84, from the reference grid.
BBOX = [-4.962155, 42.348763, 8.183832, 51.049739]
EPSG = 27572
STEP = 8000

DOI = "10.57745/BAZ12C"
CITATION = ("Météo-France, Données changement climatique SIM quotidienne "
            "(SAFRAN-ISBA-MODCOU), diffusées sur data.gouv.fr, "
            "https://doi.org/10.57745/BAZ12C")
LICENCE_URL = "https://www.etalab.gouv.fr/licence-ouverte-open-licence"
SOURCE_URL = "https://www.data.gouv.fr/datasets/6569b27598256cc583c917a7"

PROVIDERS = [
    {"name": "Météo-France / CNRM", "roles": ["producer", "licensor"],
     "url": "https://www.meteofrance.fr"},
    {"name": "INRAE, UR RiverLy", "roles": ["processor", "host"],
     "url": "https://www.riverly.inrae.fr/"},
]


def safe_str(value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value)


def fmt_date(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}T00:00:00Z"


def multihash_sha256(path: Path) -> str:
    """
    Empreinte au format multihash attendu par l'extension « file ».

    Le préfixe « 1220 » se lit 0x12 pour sha2-256 et 0x20 pour 32 octets : la
    chaîne dit d'elle-même quel algorithme la produit, de sorte que celui qui
    vérifie n'a pas à le deviner.
    """
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            digest.update(bloc)
    return "1220" + digest.hexdigest()


def cube_dimensions(x, y, date_debut: str, date_fin: str) -> dict:
    """Forme et étendue du cube, pour qui n'a pas téléchargé le fichier."""
    return {
        "time": {"type": "temporal",
                 "extent": [fmt_date(date_debut), fmt_date(date_fin)],
                 "step": "P1D"},
        "y": {"type": "spatial", "axis": "y", "unit": "m",
              "extent": [float(y[0]), float(y[-1])], "step": STEP,
              "reference_system": EPSG},
        "x": {"type": "spatial", "axis": "x", "unit": "m",
              "extent": [float(x[0]), float(x[-1])], "step": STEP,
              "reference_system": EPSG},
    }


def build_item(variable, fichier, meta, x, y, collection_id, urls) -> dict:
    """Un item, décrivant un fichier NetCDF publié."""
    item_id = (f"{variable}_SIM2_{fichier['version']}" if fichier["version"]
               else f"{variable}_SIM2")
    description = safe_str(meta.get("description")) or variable
    maintenant = f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}"

    asset = {
        "href": fichier["url"],
        "type": "application/netcdf",
        "title": fichier["filename"],
        "roles": ["data"],
        "file:size": fichier["size"],
    }
    if fichier.get("checksum"):
        asset["file:checksum"] = fichier["checksum"]

    return {
        "type": "Feature",
        "stac_version": STAC_VERSION,
        "stac_extensions": EXTENSIONS,
        "id": item_id,
        "collection": collection_id,
        "geometry": {"type": "Polygon", "coordinates": [[
            [BBOX[0], BBOX[1]], [BBOX[2], BBOX[1]], [BBOX[2], BBOX[3]],
            [BBOX[0], BBOX[3]], [BBOX[0], BBOX[1]]]]},
        "bbox": BBOX,
        "properties": {
            "datetime": None,
            "start_datetime": fmt_date(fichier["date_debut"]),
            "end_datetime": fmt_date(fichier["date_fin"]),
            "created": fichier["created"],
            "updated": maintenant,
            "title": f"SIM2 {variable} : {description}",
            "description": description,
            "license": "other",
            "providers": PROVIDERS,
            "sci:doi": DOI,
            "sci:citation": CITATION,
            "processing:software": {"safran-fairy": "en développement"},
            "processing:datetime": fichier["created"],
            "processing:lineage": (
                "Transposition sans altération des CSV quotidiens SIM2 publiés "
                f"par Météo-France sur data.gouv.fr : un NetCDF par variable, "
                f"grille Lambert II étendu inchangée."),
            "proj:code": f"EPSG:{EPSG}",
            "proj:shape": [len(y), len(x)],
            "proj:bbox": [float(x[0]) - STEP / 2, float(y[0]) - STEP / 2,
                          float(x[-1]) + STEP / 2, float(y[-1]) + STEP / 2],
            "cube:dimensions": cube_dimensions(x, y, fichier["date_debut"],
                                               fichier["date_fin"]),
            "cube:variables": {
                variable: {"dimensions": ["time", "y", "x"], "type": "data",
                           "description": description,
                           "unit": safe_str(meta.get("unite_cf"))}},
        },
        "assets": {"data": asset},
        "links": [
            {"rel": "root", "href": urls["catalog"], "type": "application/json"},
            {"rel": "parent", "href": urls["collection"], "type": "application/json"},
            {"rel": "collection", "href": urls["collection"], "type": "application/json"},
            {"rel": "self", "href": f"{urls['base']}/items/{item_id}.json",
             "type": "application/json"},
            {"rel": "cite-as", "href": f"https://doi.org/{DOI}"},
            {"rel": "license", "href": LICENCE_URL, "title": "Licence Ouverte 2.0 (Etalab)"},
            {"rel": "via", "href": SOURCE_URL, "title": "Jeu de données source"},
        ],
    }


def build_collection(items, variables_meta, collection_id, urls, temporel) -> dict:
    """La collection, qui résume ce que ses items contiennent."""
    return {
        "type": "Collection",
        "stac_version": STAC_VERSION,
        "stac_extensions": [EXTENSIONS[2]],
        "id": collection_id,
        "title": ("SIM2 : réanalyse hydrométéorologique quotidienne "
                  "SAFRAN-ISBA-MODCOU"),
        "description": (
            "Données quotidiennes de réanalyse atmosphérique et de bilan "
            "hydrique sur la France métropolitaine, sur une grille de 8 km, "
            "depuis le 1er août 1958. Composante de surface de la chaîne "
            "hydrométéorologique SIM développée par Météo-France et le CNRM. "
            "Ce dépôt transpose les CSV quotidiens publiés sur data.gouv.fr en "
            "un fichier NetCDF par variable, sans altérer les valeurs."),
        "license": "other",
        "extent": {
            "spatial": {"bbox": [BBOX]},
            "temporal": {"interval": [list(temporel)]},
        },
        "keywords": ["SAFRAN", "SIM2", "ISBA", "MODCOU", "réanalyse",
                     "hydrométéorologie", "France", "Météo-France"],
        "providers": PROVIDERS,
        "sci:doi": DOI,
        "sci:citation": CITATION,
        "summaries": {
            "variable": sorted({v for i in items
                                for v in i["properties"]["cube:variables"]}),
            "proj:code": [f"EPSG:{EPSG}"],
        },
        "item_assets": {
            "data": {"type": "application/netcdf", "roles": ["data"],
                     "title": "Chronique complète de la variable, au format NetCDF"}},
        "links": [
            {"rel": "root", "href": urls["catalog"], "type": "application/json"},
            {"rel": "parent", "href": urls["catalog"], "type": "application/json"},
            {"rel": "self", "href": urls["collection"], "type": "application/json"},
            {"rel": "cite-as", "href": f"https://doi.org/{DOI}"},
            {"rel": "license", "href": LICENCE_URL, "title": "Licence Ouverte 2.0 (Etalab)"},
            {"rel": "via", "href": SOURCE_URL, "title": "Jeu de données source"},
            *[{"rel": "item", "href": f"{urls['base']}/items/{i['id']}.json",
               "type": "application/json", "title": i["properties"]["title"]}
              for i in items],
        ],
    }


def build_root_catalog(catalog_id, urls, titre_collection, existant=None) -> dict:
    """
    Le catalogue racine du bucket, point d'entrée de tout le reste.

    Les liens « child » qui ne sont pas les nôtres sont conservés tels quels :
    le bucket n'héberge aujourd'hui que ce jeu, mais s'il en accueillait un
    autre, le regénérer d'ici ne doit pas l'effacer.
    """
    autres = [l for l in (existant or {}).get("links", [])
              if l.get("rel") == "child" and l.get("href") != urls["collection"]]
    return {
        "type": "Catalog",
        "stac_version": STAC_VERSION,
        "id": catalog_id,
        "title": "RiverLy Data Lake",
        "description": (
            "Catalogue des jeux de données hydrologiques et climatiques mis à "
            "disposition par l'unité de recherche RiverLy d'INRAE."),
        "links": [
            {"rel": "root", "href": urls["catalog"], "type": "application/json"},
            {"rel": "self", "href": urls["catalog"], "type": "application/json"},
            {"rel": "child", "href": urls["collection"],
             "type": "application/json", "title": titre_collection},
            *autres,
        ],
    }


def read_root_catalog(s3, S3_BUCKET):
    """Le catalogue racine en ligne, ou None s'il n'existe pas encore."""
    try:
        return json.loads(
            s3.get_object(Bucket=S3_BUCKET, Key="stac-data/catalog.json")["Body"].read())
    except Exception:
        return None


def generate_stac_catalog(CATALOG_DIR,
                          S3_BUCKET: str,
                          S3_PREFIX: str = "",
                          METADATA_VARIABLES_FILE: str = None,
                          METADATA_GRID_FILE: str = None,
                          OUTPUT_DIR: str = None,
                          S3_ACCESS_KEY: str = None,
                          S3_SECRET_KEY: str = None,
                          S3_ENDPOINT: str = None,
                          S3_REGION: str = None) -> list:
    """
    Génère le catalogue STAC décrivant ce qui est publié sur le bucket.

    Args:
        CATALOG_DIR (str | Path):      dossier de sortie du catalogue.
        S3_PREFIX (str):               préfixe des données sur le bucket.
        METADATA_VARIABLES_FILE (str): table des variables.
        METADATA_GRID_FILE (str):      grille de référence, pour les dimensions du cube.
        OUTPUT_DIR (str, optional):    dossier des sorties locales. Quand un fichier
                                       du bucket s'y retrouve à l'identique, son
                                       empreinte est calculée et publiée.

    Returns:
        list[Path]: les fichiers JSON écrits.
    """
    base_url = f"{S3_ENDPOINT.rstrip('/')}/{S3_BUCKET}"
    dataset = S3_PREFIX.strip("/").split("/")[-1] if S3_PREFIX else "dataset"
    urls = {"base": f"{base_url}/stac-data/{dataset}",
            "catalog": f"{base_url}/stac-data/catalog.json",
            "collection": f"{base_url}/stac-data/{dataset}/collection.json"}
    collection_id = f"sim2-{dataset}"

    s3 = boto3.client("s3", aws_access_key_id=S3_ACCESS_KEY,
                      aws_secret_access_key=S3_SECRET_KEY,
                      endpoint_url=S3_ENDPOINT, region_name=S3_REGION)

    # Le plus récent par (variable, version) : les deux nommages coexistent
    # tant que les fichiers hérités n'ont pas été retirés du bucket.
    retenus = {}
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=S3_BUCKET,
                                                             Prefix=S3_PREFIX):
        for obj in page.get("Contents", []):
            nom = Path(obj["Key"]).name
            parsed = parse_filename(nom)
            if not parsed:
                continue
            cle = (parsed["variable"], parsed["version"])
            if cle in retenus and retenus[cle]["date_fin"] >= parsed["date_fin"]:
                continue
            retenus[cle] = {**parsed, "filename": nom,
                            "url": f"{base_url}/{obj['Key']}",
                            "size": obj["Size"],
                            "created": f"{obj['LastModified']:%Y-%m-%dT%H:%M:%SZ}"}

    if not retenus:
        print("⚠️  aucun fichier reconnu sur le bucket")
        return []

    # Empreinte calculée sur la copie locale, quand elle correspond à l'octet près.
    if OUTPUT_DIR:
        for fichier in retenus.values():
            local = Path(OUTPUT_DIR) / fichier["filename"]
            if local.exists() and local.stat().st_size == fichier["size"]:
                fichier["checksum"] = multihash_sha256(local)

    var_meta = {}
    if METADATA_VARIABLES_FILE and Path(METADATA_VARIABLES_FILE).exists():
        var_meta = pd.read_csv(METADATA_VARIABLES_FILE,
                               index_col="variable").to_dict(orient="index")
    x, y = regular_axes(METADATA_GRID_FILE)

    items = [build_item(variable, fichier, var_meta.get(variable, {}),
                        x, y, collection_id, urls)
             for (variable, _), fichier in sorted(retenus.items())]
    temporel = (min(i["properties"]["start_datetime"] for i in items),
                max(i["properties"]["end_datetime"] for i in items))
    collection = build_collection(items, var_meta, collection_id, urls, temporel)

    racine = build_root_catalog(S3_BUCKET, urls, collection["title"],
                                read_root_catalog(s3, S3_BUCKET))

    # L'arborescence locale reproduit celle du bucket, de sorte que la
    # publication soit une recopie et que ce qui traîne se repère au même
    # endroit des deux côtés.
    catalog_dir = Path(CATALOG_DIR)
    items_dir = catalog_dir / dataset / "items"
    items_dir.mkdir(parents=True, exist_ok=True)
    for ancien in catalog_dir.rglob("*.json"):
        ancien.unlink()

    ecrits = []
    for objet, chemin in ([(racine, catalog_dir / "catalog.json"),
                           (collection, catalog_dir / dataset / "collection.json")]
                          + [(i, items_dir / f"{i['id']}.json") for i in items]):
        chemin.write_text(json.dumps(objet, ensure_ascii=False, indent=2))
        ecrits.append(chemin)

    avec_empreinte = sum(1 for f in retenus.values() if f.get("checksum"))
    print(f"✅ catalogue STAC {STAC_VERSION} : 1 catalogue racine, 1 collection, "
          f"{len(items)} item(s), {avec_empreinte} empreinte(s)")
    return ecrits
