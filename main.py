#!/usr/bin/env python3
"""
SAFRAN Fairy - Pipeline de traitement des données SAFRAN
"""

import os
import sys
import json
import argparse
from pathlib import Path
from dotenv import load_dotenv


def load_config(config_file):
    """Charge la configuration depuis config.json"""
    with open(config_file, 'r') as f:
        return json.load(f)

def print_welcome(welcome_file):
    """Affiche le message de bienvenue"""
    if welcome_file.exists():
        with open(welcome_file, 'r') as f:
            print(f.read())


# Charger env
load_dotenv()
MODE = os.getenv("MODE")

# Configuration
CONFIG_FILE = os.getenv("CONFIG_FILE")
config = load_config(CONFIG_FILE)

RESOURCES_DIR = Path("resources")
WELCOME_FILE = RESOURCES_DIR / config['WELCOME_FILE']
METADATA_VARIABLES_FILE = RESOURCES_DIR / config['METADATA_VARIABLES_FILE']
STATE_FILE = config['STATE_FILE']
INDEX_PATH = config['INDEX_PATH']
DOWNLOAD_DIR = config['DOWNLOAD_DIR']
RAW_DIR = config['RAW_DIR']
SPLIT_DIR = config['SPLIT_DIR']
CONVERT_DIR = config['CONVERT_DIR']
OUTPUT_DIR = config['OUTPUT_DIR']
CATALOG_DIR = config['CATALOG_DIR']
METEO_BASE_URL = config['METEO_BASE_URL']
METEO_DATASET_ID = config['METEO_DATASET_ID']
RDG_BASE_URL = config['RDG_BASE_URL']
RDG_DATASET_DOI = config['RDG_DATASET_DOI']
RDG_API_TOKEN = os.getenv("RDG_API_TOKEN")
S3_ENDPOINT = config['S3_ENDPOINT']
S3_BUCKET = config['S3_BUCKET']
S3_DATA_PREFIX = config['S3_DATA_PREFIX'].strip("/")
S3_REGION = config['S3_REGION']
S3_ACCESS_KEY = os.getenv('S3_ACCESS_KEY')
S3_SECRET_KEY = os.getenv('S3_SECRET_KEY')

# Setup dev mode
if MODE == "dev":
    try:
        get_ipython().run_line_magic('load_ext', 'autoreload')
        get_ipython().run_line_magic('autoreload', '2')
        print("🔧 Mode développement activé")
    except:
        pass

from safran_fairy import (apply_s3_bucket_policy, apply_s3_bucket_cors,
                          list_s3_files, download, decompress, split, convert,
                          merge, upload_s3, delete_s3_files,
                          generate_stac_catalog, generate_index,
                          clean_local, clean_s3)

S3_CREDENTIALS = dict(S3_ACCESS_KEY=S3_ACCESS_KEY,
                      S3_SECRET_KEY=S3_SECRET_KEY,
                      S3_ENDPOINT=S3_ENDPOINT,
                      S3_REGION=S3_REGION)


def main():
    parser = argparse.ArgumentParser(description='SAFRAN Fairy - Pipeline de traitement')

    # Setup bucket (hors pipeline)
    parser.add_argument('--setup',      action='store_true', help='Configure le bucket S3 (policy + CORS)')

    # Pipeline complet
    parser.add_argument('--all',        action='store_true', help='Exécute le pipeline complet')

    # Étapes individuelles
    parser.add_argument('--download',   action='store_true', help='Télécharge les fichiers')
    parser.add_argument('--decompress', action='store_true', help='Décompresse les fichiers')
    parser.add_argument('--split',      action='store_true', help='Découpe les CSV par variable')
    parser.add_argument('--convert',    action='store_true', help='Convertit en NetCDF')
    parser.add_argument('--merge',      action='store_true', help='Fusionne temporellement')
    parser.add_argument('--upload',     action='store_true', help='Upload sur le S3')
    parser.add_argument('--ui',         action='store_true', help='Génère et uploade le catalogue STAC')
    parser.add_argument('--clean',      action='store_true', help='Nettoie les anciennes versions')

    # Options
    parser.add_argument('--overwrite',  action='store_true', help='Écrase les fichiers existants')
    parser.add_argument('--process',    action='store_true', help='Traite uniquement (decompress + split + convert + merge)')

    args = parser.parse_args()

    if not any([args.all, args.setup, args.download, args.decompress, args.split,
                args.convert, args.merge, args.upload, args.ui,
                args.clean, args.overwrite]):
        args.all = True
        args.overwrite = True

    print_welcome(WELCOME_FILE)

    downloaded_files  = None
    decompressed_files = None
    splited_files     = None
    converted_files   = None
    merged_files      = None

    # 0. SETUP BUCKET (une seule fois)
    if args.setup:
        apply_s3_bucket_policy(S3_BUCKET=S3_BUCKET, **S3_CREDENTIALS)
        apply_s3_bucket_cors(S3_BUCKET=S3_BUCKET, **S3_CREDENTIALS)

    # 1. TÉLÉCHARGEMENT
    if args.all or args.download:
        downloaded_files = download(STATE_FILE, DOWNLOAD_DIR,
                                    METEO_BASE_URL, METEO_DATASET_ID)
        removed = clean_local(DOWNLOAD_DIR)
        downloaded_files = [f for f in downloaded_files if f not in removed]
        if not downloaded_files:
            return

    # 2. DÉCOMPRESSION
    if args.all or args.process or args.decompress:
        decompressed_files = decompress(DOWNLOAD_DIR, RAW_DIR, downloaded_files)
        clean_local(RAW_DIR)

    # 3. SPLIT
    if args.all or args.process or args.split:
        splited_files = split(RAW_DIR, SPLIT_DIR, decompressed_files)
        clean_local(SPLIT_DIR)

    # 4. CONVERSION
    if args.all or args.process or args.convert:
        converted_files = convert(SPLIT_DIR, CONVERT_DIR,
                                  METADATA_VARIABLES_FILE, splited_files)
        clean_local(CONVERT_DIR)

    # 5. MERGE
    if args.all or args.process or args.merge:
        merged_files = merge(CONVERT_DIR, OUTPUT_DIR, converted_files)
        clean_local(OUTPUT_DIR,
                    patterns={'historical': r'historical-(\d{8})-(\d{8})',
                              'latest':     r'latest-(\d{8})-(\d{8})',
                              'previous':   r'previous-(\d{8})-(\d{8})'})

    # 6. UPLOAD
    if args.all or args.upload:
        if merged_files is None:
            merged_files = list(Path(OUTPUT_DIR).glob("*.nc"))
        s3_paths = [Path(p).relative_to(OUTPUT_DIR) for p in merged_files]

        not_uploaded = upload_s3(local_paths=merged_files,
                                 S3_BUCKET=S3_BUCKET,
                                 s3_paths=s3_paths,
                                 S3_PREFIX="data/"+S3_DATA_PREFIX,
                                 **S3_CREDENTIALS)
        clean_s3(S3_BUCKET=S3_BUCKET,
                 S3_PREFIX="data/"+S3_DATA_PREFIX,
                 **S3_CREDENTIALS)

        if not_uploaded:
            sys.exit(1)

    # 7. CATALOGUE STAC
    if args.all or args.ui:
        stac_files = generate_stac_catalog(CATALOG_DIR=CATALOG_DIR,
                                           S3_BUCKET=S3_BUCKET,
                                           S3_PREFIX="data/"+S3_DATA_PREFIX,
                                           METADATA_VARIABLES_FILE=METADATA_VARIABLES_FILE,
                                           **S3_CREDENTIALS)
        s3_paths = [Path(p).relative_to(CATALOG_DIR) for p in stac_files]

        upload_s3(local_paths=stac_files,
                  S3_BUCKET=S3_BUCKET,
                  s3_paths=s3_paths,
                  S3_PREFIX="stac-data/"+S3_DATA_PREFIX,
                  **S3_CREDENTIALS)

    # 8. NETTOYAGE
    if args.clean:
        clean_local(directory=DOWNLOAD_DIR)
        clean_local(directory=RAW_DIR)
        clean_local(directory=SPLIT_DIR)
        clean_local(directory=CONVERT_DIR)
        clean_local(directory=OUTPUT_DIR,
                    patterns={'historical': r'historical-(\d{8})-(\d{8})',
                              'latest':     r'latest-(\d{8})-(\d{8})',
                              'previous':   r'previous-(\d{8})-(\d{8})'})
        clean_s3(S3_BUCKET=S3_BUCKET,
                 S3_PREFIX="data/"+S3_DATA_PREFIX,
                 **S3_CREDENTIALS)

    print("\n✨ Pipeline terminé avec succès!")


if __name__ == "__main__":
    try:
        if MODE == "prod":
            main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Interruption par l'utilisateur")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


## HTML INDEX ________________________________________________________
# generate_index(S3_BUCKET=S3_BUCKET,
#                S3_PREFIX="data/"+S3_DATA_PREFIX,
#                METADATA_VARIABLES_FILE=METADATA_VARIABLES_FILE,
#                INDEX_PATH=INDEX_PATH,
#                S3_ACCESS_KEY=S3_ACCESS_KEY,
#                S3_SECRET_KEY=S3_SECRET_KEY,
#                S3_ENDPOINT=S3_ENDPOINT,
#                S3_REGION=S3_REGION)

# upload_dataverse_index(INDEX_PATH=INDEX_PATH,
#                        RDG_DATASET_DOI=RDG_DATASET_DOI,
#                        RDG_BASE_URL=RDG_BASE_URL,
#                        RDG_API_TOKEN=RDG_API_TOKEN)


## DRAFT _____________________________________________________________        
# keys = ["catalog.json", "collection.json"]
# delete_s3_files(keys,
#                 S3_BUCKET=S3_BUCKET,
#                 S3_ACCESS_KEY=S3_ACCESS_KEY,
#                 S3_SECRET_KEY=S3_SECRET_KEY,
#                 S3_ENDPOINT=S3_ENDPOINT,
#                 S3_REGION=S3_REGION)

# stac_keys = list_s3_files(S3_BUCKET, S3_PREFIX="stac-data/data/",
#                           S3_ACCESS_KEY=S3_ACCESS_KEY,
#                           S3_SECRET_KEY=S3_SECRET_KEY,
#                           S3_ENDPOINT=S3_ENDPOINT,
#                           S3_REGION=S3_REGION)
# stac_keys = list_s3_files(S3_BUCKET, S3_PREFIX="stac-data/safran-fairy/",
#                           S3_ACCESS_KEY=S3_ACCESS_KEY,
#                           S3_SECRET_KEY=S3_SECRET_KEY,
#                           S3_ENDPOINT=S3_ENDPOINT,
#                           S3_REGION=S3_REGION)
# delete_s3_files(stac_keys, S3_BUCKET,
#                 S3_ACCESS_KEY=S3_ACCESS_KEY,
#                 S3_SECRET_KEY=S3_SECRET_KEY,
#                 S3_ENDPOINT=S3_ENDPOINT,
#                 S3_REGION=S3_REGION)


# browser_keys = list_s3_files(S3_BUCKET, S3_PREFIX="assets/",
#                              S3_ACCESS_KEY=S3_ACCESS_KEY,
#                              S3_SECRET_KEY=S3_SECRET_KEY,
#                              S3_ENDPOINT=S3_ENDPOINT,
#                              S3_REGION=S3_REGION)
# browser_keys += list_s3_files(S3_BUCKET, S3_PREFIX="", extension=".html",
#                               S3_ACCESS_KEY=S3_ACCESS_KEY,
#                               S3_SECRET_KEY=S3_SECRET_KEY,
#                               S3_ENDPOINT=S3_ENDPOINT,
#                               S3_REGION=S3_REGION)
# delete_s3_files(browser_keys, S3_BUCKET,
#                 S3_ACCESS_KEY=S3_ACCESS_KEY,
#                 S3_SECRET_KEY=S3_SECRET_KEY,
#                 S3_ENDPOINT=S3_ENDPOINT,
#                 S3_REGION=S3_REGION)
