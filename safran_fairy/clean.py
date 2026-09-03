# SPDX-FileCopyrightText: 2026 Louis Héraut <louis.heraut@inrae.fr>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Remove superseded versions, locally and on the bucket.

Only output files need this: since the upstream reshuffle of 31 July 2026 no
source file name carries a date, so every intermediate file is overwritten in
place and nothing accumulates. An output file, on the other hand, is named after
its coverage, so a new one lands beside the old one.

Deletion always happens after the new file exists, never before, so that a run
interrupted midway leaves the previous version in place rather than a hole.
"""

from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path

import boto3

from .report import banner, line, phase, summary

from .tools import parse_filename


def _superseded(entries: list[dict]) -> list[dict]:
    """Among files of one variable, everything but the latest coverage."""
    if len(entries) <= 1:
        return []
    newest = max(e["date_fin"] for e in entries)
    return [e for e in entries if e["date_fin"] < newest]


def clean_local(directory, keep: list[Path] | None = None) -> list[Path]:
    """
    Supprime les sorties périmées d'un dossier, une par variable étant gardée.

    Args:
        directory (str | Path):    dossier à nettoyer.
        keep (list[Path], optional): fichiers à ne jamais supprimer, quels que
                                     soient leurs noms. Typiquement ceux que le
                                     run vient de produire.

    Returns:
        list[Path]: les fichiers supprimés.
    """
    directory = Path(directory)
    protected = {Path(p).resolve() for p in (keep or [])}

    # Grouped by (variable, version) and not by variable alone: during the
    # transition both namings coexist, and a legacy file must never be removed
    # because a file of the target naming happens to reach further.
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for path in directory.glob("*.nc"):
        parsed = parse_filename(path.name)
        if parsed:
            groups[(parsed["variable"], parsed["version"])].append(
                {"path": path, "date_fin": int(parsed["date_fin"])})

    removed = []
    for _, entries in sorted(groups.items(), key=lambda kv: str(kv[0])):
        for entry in _superseded(entries):
            if entry["path"].resolve() in protected:
                continue
            line(f"🗑️  {entry['path'].name}")
            entry["path"].unlink()
            removed.append(entry["path"])

    if removed:
        summary(supprimes=len(removed), dossier=os.path.abspath(directory))
    return removed


def clean_s3(S3_BUCKET: str,
             S3_PREFIX: str = "",
             S3_ACCESS_KEY: str = None,
             S3_SECRET_KEY: str = None,
             S3_ENDPOINT: str = None,
             S3_REGION: str = None) -> list[str]:
    """
    Supprime du bucket les sorties périmées, une par variable étant gardée.

    Returns:
        list[str]: les clés supprimées.
    """
    banner("clean")

    s3 = boto3.client("s3",
                      aws_access_key_id=S3_ACCESS_KEY,
                      aws_secret_access_key=S3_SECRET_KEY,
                      endpoint_url=S3_ENDPOINT,
                      region_name=S3_REGION)

    phase("NETTOYAGE S3", f"{S3_BUCKET}/{S3_PREFIX}")

    groups: dict[tuple, list[dict]] = defaultdict(list)
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=S3_PREFIX):
        for obj in page.get("Contents", []):
            parsed = parse_filename(Path(obj["Key"]).name)
            if parsed:
                # "version" is None on the target naming, set on legacy files:
                # both coexist on the bucket during the transition.
                groups[(parsed["variable"], parsed["version"])].append(
                    {"key": obj["Key"], "date_fin": int(parsed["date_fin"])})

    removed = []
    for key, entries in sorted(groups.items(), key=lambda kv: str(kv[0])):
        for entry in _superseded(entries):
            try:
                s3.delete_object(Bucket=S3_BUCKET, Key=entry["key"])
                line(f"🗑️  {Path(entry['key']).name}")
                removed.append(entry["key"])
            except Exception as error:
                line(f"❌ {Path(entry['key']).name} : {error}")

    summary(supprimes=len(removed))
    return removed
