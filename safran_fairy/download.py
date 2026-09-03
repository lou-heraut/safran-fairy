# SPDX-FileCopyrightText: 2026 Louis Héraut <louis.heraut@inrae.fr>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Mirror the data.gouv.fr dataset locally, downloading only what changed.

Nothing here reads a source file name to guess what a file holds: that job
belongs to sources.py, so that a new upstream reshuffle touches one module.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import requests

from .report import (Chrono, banner, humain, is_terminal, line,
                     phase, summary)

from .sources import Resource, check_inventory, describe, list_resources


def load_state(STATE_FILE) -> dict:
    """Read what was downloaded last time, keyed by resource id."""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state: dict, STATE_FILE) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def local_path(resource: Resource, DOWNLOAD_DIR) -> Path:
    return Path(DOWNLOAD_DIR) / resource.filename


def has_changed(resource: Resource, state: dict, DOWNLOAD_DIR) -> bool:
    """
    Whether a resource must be downloaded again.

    Upstream offers no usable checksum: "analysis:checksum" is missing on the
    large files, which data.gouv marks "File too large to download". The pair
    (last_modified, size) is what is available, completed by the state of the
    local copy so that a truncated or deleted file is fetched again.
    """
    known = state.get(resource.id)
    if known is None:
        return True
    if known.get("last_modified") != resource.last_modified:
        return True
    if resource.size and known.get("size_bytes") != resource.size:
        return True

    path = local_path(resource, DOWNLOAD_DIR)
    if not path.exists():
        return True
    if resource.size and path.stat().st_size != resource.size:
        return True

    return False


def download_file(resource: Resource, DOWNLOAD_DIR) -> dict | None:
    """
    Fetch one resource. Writes to a « .part » file renamed once complete, so
    that an interrupted run never leaves behind a file that looks whole.
    """
    path = local_path(resource, DOWNLOAD_DIR)
    partial = path.with_suffix(path.suffix + ".part")
    anime = is_terminal()

    try:
        response = requests.get(resource.url, stream=True, timeout=60)
        response.raise_for_status()

        expected = int(response.headers.get("content-length", 0))
        written = 0
        with open(partial, "wb") as f:
            for chunk in response.iter_content(chunk_size=1 << 20):
                if not chunk:
                    continue
                f.write(chunk)
                written += len(chunk)
                # Une progression animée n'a de sens que sur un terminal :
                # dans un journal, le retour chariot empile au lieu d'effacer.
                if expected and anime:
                    print(f"   {resource.filename} {written / expected * 100:5.1f} %",
                          end="\r", flush=True)

        if expected and written != expected:
            partial.unlink(missing_ok=True)
            line(f"❌ {resource.filename} incomplet, "
                 f"{humain(written)} reçus sur {humain(expected)}")
            return None

        partial.replace(path)
        if anime:
            print(" " * 60, end="\r")

        return {
            "filename": resource.filename,
            "last_modified": resource.last_modified,
            "downloaded_at": datetime.now().isoformat(),
            "size_bytes": written,
        }

    except Exception as error:
        partial.unlink(missing_ok=True)
        line(f"❌ {resource.filename} : {error}")
        return None


def remove_orphans(resources: list[Resource], DOWNLOAD_DIR) -> list[Path]:
    """
    Supprime les fichiers locaux que l'amont ne publie plus.

    Le dossier est un miroir du dépôt distant : un fichier qui n'y correspond
    plus n'a aucune chance d'être relu, et sans cela il s'accumule à chaque
    recomposition. Le découpage par décennie de juillet 2026 avait ainsi laissé
    8,4 Go inertes.

    N'est appelée qu'après le contrôle d'inventaire : si l'amont renvoyait une
    liste incomplète, on refuserait de continuer bien avant d'arriver ici.
    """
    attendus = {r.filename for r in resources}
    orphelins = [f for f in Path(DOWNLOAD_DIR).glob("*")
                 if f.is_file() and f.name not in attendus]
    if not orphelins:
        return []

    poids = sum(f.stat().st_size for f in orphelins)
    phase("NETTOYAGE", f"{len(orphelins)} fichier(s) que l'amont ne publie plus, "
                       f"{humain(poids)}")
    for f in orphelins:
        line(f"🗑️  {f.name}")
        f.unlink()
    return orphelins


def download(STATE_FILE, DOWNLOAD_DIR, METEO_BASE_URL, METEO_DATASET_ID,
             resources: list[Resource] | None = None) -> list[Resource]:
    """
    Synchronise le miroir local du jeu de données amont.

    Args:
        STATE_FILE (str | Path):   fichier JSON de suivi, créé au premier appel.
        DOWNLOAD_DIR (str | Path): dossier de destination, créé si absent.
        METEO_BASE_URL (str):      racine de l'API data.gouv.fr.
        METEO_DATASET_ID (str):    identifiant du jeu de données.
        resources (list[Resource], optional): inventaire déjà lu. Sinon
                                              l'API est interrogée.

    Returns:
        list[Resource]: les ressources de données effectivement téléchargées,
                        années puis glissant. Liste vide si tout est à jour.

    Raises:
        RuntimeError: si l'inventaire amont ne ressemble plus à ce qui est
                      attendu. Mieux vaut s'arrêter que produire une chronique
                      tronquée en silence.
    """
    banner("download")

    Path(DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)

    if resources is None:
        resources = list_resources(METEO_BASE_URL, METEO_DATASET_ID)

    phase("INVENTAIRE", describe(resources))

    anomalies = check_inventory(resources)
    if anomalies:
        for anomalie in anomalies:
            line(f"❌ {anomalie}")
        raise RuntimeError("l'inventaire amont ne correspond plus au format attendu")

    remove_orphans(resources, DOWNLOAD_DIR)

    state = load_state(STATE_FILE)
    to_download = [r for r in resources if has_changed(r, state, DOWNLOAD_DIR)]
    volume = sum(r.size or 0 for r in to_download)

    phase("TÉLÉCHARGEMENT",
          f"{len(to_download)} à prendre ({humain(volume)}), "
          f"{len(resources) - len(to_download)} déjà à jour")

    if not to_download:
        return []

    downloaded, failed = [], []
    with Chrono() as total:
        for i, resource in enumerate(to_download, 1):
            with Chrono() as chrono:
                result = download_file(resource, DOWNLOAD_DIR)
            if result:
                state[resource.id] = result
                save_state(state, STATE_FILE)
                downloaded.append(resource)
                line(f"[{i}/{len(to_download)}] {resource.filename:32s} "
                     f"{humain(result['size_bytes']):>8s}   {chrono}")
            else:
                failed.append(resource)

    summary(pris=len(downloaded), echecs=len(failed),
            volume=humain(sum(r.size or 0 for r in downloaded)),
            duree=str(total))

    data = [r for r in downloaded if r.is_data]
    return sorted(data, key=lambda r: (r.kind == "rolling", r.year or 0))
