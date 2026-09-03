#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Louis Héraut <louis.heraut@inrae.fr>
# SPDX-License-Identifier: GPL-3.0-or-later
"""SAFRAN Fairy: turn the SIM2 reanalysis into one NetCDF per climate variable.

The chain is linear and every step can be run on its own, so that a long rebuild
can be resumed where it stopped:

    download -> decompress -> split -> convert -> build -> check -> upload -> ui

Nothing is ever published without check() having accepted it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def load_config(config_file):
    with open(config_file) as f:
        return json.load(f)


def print_welcome(welcome_file):
    if Path(welcome_file).exists():
        print(Path(welcome_file).read_text())


load_dotenv()
MODE = os.getenv("MODE")

CONFIG_FILE = os.getenv("CONFIG_FILE")
config = load_config(CONFIG_FILE)

RESOURCES_DIR = Path("resources")
WELCOME_FILE = RESOURCES_DIR / config["WELCOME_FILE"]
METADATA_VARIABLES_FILE = RESOURCES_DIR / config["METADATA_VARIABLES_FILE"]
STATE_FILE = config["STATE_FILE"]
DOWNLOAD_DIR = config["DOWNLOAD_DIR"]
RAW_DIR = config["RAW_DIR"]
SPLIT_DIR = config["SPLIT_DIR"]
CONVERT_DIR = config["CONVERT_DIR"]
OUTPUT_DIR = config["OUTPUT_DIR"]
CATALOG_DIR = config["CATALOG_DIR"]
METEO_BASE_URL = config["METEO_BASE_URL"]
METEO_DATASET_ID = config["METEO_DATASET_ID"]
S3_ENDPOINT = config["S3_ENDPOINT"]
S3_BUCKET = config["S3_BUCKET"]
S3_DATA_PREFIX = config["S3_DATA_PREFIX"].strip("/")
S3_REGION = config["S3_REGION"]

if MODE == "dev":
    try:
        get_ipython().run_line_magic("load_ext", "autoreload")
        get_ipython().run_line_magic("autoreload", "2")
        print("🔧 Mode développement activé")
    except Exception:
        pass

from safran_fairy import (apply_s3_bucket_cors, apply_s3_bucket_policy, build,
                          check, clean_local, clean_s3, convert, decompress,
                          download, generate_stac_catalog, split, upload_s3)

S3_CREDENTIALS = dict(S3_ACCESS_KEY=os.getenv("S3_ACCESS_KEY"),
                      S3_SECRET_KEY=os.getenv("S3_SECRET_KEY"),
                      S3_ENDPOINT=S3_ENDPOINT,
                      S3_REGION=S3_REGION)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="SAFRAN Fairy : pipeline SIM2 vers NetCDF par variable.")

    parser.add_argument("--setup", action="store_true",
                        help="configure le bucket S3 (policy et CORS), une seule fois")
    parser.add_argument("--all", action="store_true",
                        help="exécute la chaîne complète")

    etapes = parser.add_argument_group("étapes")
    for nom, aide in [("download", "télécharge ce qui a changé en amont"),
                      ("decompress", "décompresse les .csv.gz"),
                      ("split", "découpe les CSV par variable"),
                      ("convert", "convertit en NetCDF"),
                      ("build", "assemble une chronique par variable"),
                      ("check", "contrôle les fichiers de sortie"),
                      ("upload", "publie sur le S3"),
                      ("ui", "génère et publie le catalogue STAC"),
                      ("clean", "supprime les versions périmées, en local et sur le S3")]:
        etapes.add_argument(f"--{nom}", action="store_true", help=aide)

    parser.add_argument("--variables", nargs="+", metavar="VAR",
                        help="ne traiter que ces variables, ex. --variables TINF_H")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    etapes = ["download", "decompress", "split", "convert",
              "build", "check", "upload", "ui"]
    # Purging is maintenance, not a step of the chain: --all does not imply it,
    # since the chain already purges what it supersedes as it goes.
    if not args.setup and not any(getattr(args, e) for e in etapes):
        args.all = True
    if args.all:
        for etape in etapes:
            setattr(args, etape, True)

    print_welcome(WELCOME_FILE)
    variables = args.variables

    if args.setup:
        apply_s3_bucket_policy(S3_BUCKET=S3_BUCKET, **S3_CREDENTIALS)
        apply_s3_bucket_cors(S3_BUCKET=S3_BUCKET, **S3_CREDENTIALS)
        return

    downloaded = None
    csv_files = None
    parquet_files = None
    outputs = None

    if args.download:
        downloaded = download(STATE_FILE, DOWNLOAD_DIR,
                              METEO_BASE_URL, METEO_DATASET_ID)
        if not downloaded:
            print("\n✨ Rien de nouveau en amont, la chaîne s'arrête ici")
            return
        csv_files = [Path(DOWNLOAD_DIR) / r.filename for r in downloaded]

    if args.decompress:
        csv_files = decompress(DOWNLOAD_DIR, RAW_DIR, csv_files)

    if args.split:
        parquet_files = split(RAW_DIR, SPLIT_DIR, csv_files, variables=variables)

    if args.convert:
        convert(SPLIT_DIR, CONVERT_DIR, METADATA_VARIABLES_FILE, parquet_files)

    if args.build:
        outputs = build(CONVERT_DIR, OUTPUT_DIR, variables=variables)
        clean_local(OUTPUT_DIR, keep=outputs)

    # Nothing goes online without this passing, whatever the invocation.
    if args.check or args.upload:
        rejected = check(outputs, OUTPUT_DIR=None if outputs else OUTPUT_DIR)
        if rejected:
            sys.exit(1)

    if args.upload:
        if outputs is None:
            outputs = sorted(Path(OUTPUT_DIR).glob("*.nc"))
        not_uploaded = upload_s3(local_paths=outputs,
                                 S3_BUCKET=S3_BUCKET,
                                 s3_paths=[Path(p).name for p in outputs],
                                 S3_PREFIX="data/" + S3_DATA_PREFIX,
                                 **S3_CREDENTIALS)
        if not_uploaded:
            sys.exit(1)
        # Only once the new files are online.
        clean_s3(S3_BUCKET=S3_BUCKET, S3_PREFIX="data/" + S3_DATA_PREFIX,
                 **S3_CREDENTIALS)

    if args.clean:
        clean_local(OUTPUT_DIR)
        clean_s3(S3_BUCKET=S3_BUCKET, S3_PREFIX="data/" + S3_DATA_PREFIX,
                 **S3_CREDENTIALS)

    if args.ui:
        stac_files = generate_stac_catalog(
            CATALOG_DIR=CATALOG_DIR,
            S3_BUCKET=S3_BUCKET,
            S3_PREFIX="data/" + S3_DATA_PREFIX,
            METADATA_VARIABLES_FILE=METADATA_VARIABLES_FILE,
            **S3_CREDENTIALS)
        upload_s3(local_paths=stac_files,
                  S3_BUCKET=S3_BUCKET,
                  s3_paths=[Path(p).relative_to(CATALOG_DIR) for p in stac_files],
                  S3_PREFIX="stac-data/" + S3_DATA_PREFIX,
                  **S3_CREDENTIALS)

    print("\n✨ Pipeline terminé")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Interruption par l'utilisateur")
        sys.exit(130)
    except Exception as error:
        print(f"\n❌ Erreur : {error}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
