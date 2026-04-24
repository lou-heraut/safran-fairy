import os
import re
import requests
from pathlib import Path
from datetime import datetime
from art import tprint
import boto3

from .tools import parse_filename


def clean_local(directory,
                extensions=['.csv', '.csv.gz', '.parquet', '.nc'],
                patterns={
                    'latest': r'latest-(\d{8})-(\d{8})',
                    'previous': r'previous-(\d{4})-(\d{6})'
                }):
    directory = Path(directory)
    print("\nNETTOYAGE")
    
    removed = []

    for file_type, pattern in patterns.items():
        print(f"\nRecherche de fichiers '{file_type}'...")
        
        files = list(directory.glob(f"*{file_type}*"))
        files = [f for f in files if ''.join(f.suffixes) in extensions]
        files = [f for f in files if re.search(pattern, f.name)]
        
        if not files:
            print(f"   - ℹ️ Aucun fichier trouvé")
            continue
        
        dates = [int(re.search(pattern, f.name).group(2)) for f in files]
        max_date = max(dates)
        files_to_delete = [f for f, d in zip(files, dates) if d < max_date]
        for file in files_to_delete:
            print(f"   - 🗑️ {file.name}")
            file.unlink()
            removed.append(file)
        
        print(f"   - 📊 {len(files_to_delete)} fichier(s) supprimé(s)")

    return removed


def clean_dataverse(dataset_DOI: str,
                    RDG_BASE_URL: str = os.getenv("RDG_BASE_URL"),
                    RDG_API_TOKEN: str = os.getenv("RDG_API_TOKEN")):
    """
    Supprime les fichiers NetCDF obsolètes d'un dataset Dataverse
    en ne gardant que le plus récent par couple (variable, version).
    """
    print("\nNETTOYAGE DATAVERSE")
    print(f"   Dataset: {dataset_DOI}")

    url = f"{RDG_BASE_URL}/api/datasets/:persistentId/?persistentId={dataset_DOI}"
    headers = {'X-Dataverse-key': RDG_API_TOKEN}
    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        print(f"   ❌ Impossible de récupérer les fichiers: {response.text}")
        return

    files_data = response.json()['data']['latestVersion']['files']

    from collections import defaultdict
    groups = defaultdict(list)
    for file_info in files_data:
        filename = file_info['dataFile']['filename']
        if not filename.endswith('.nc'):
            continue
        parsed = parse_filename(filename)
        if not parsed:
            continue
        group_key = (parsed['variable'], parsed['version'])
        groups[group_key].append({
            'id': file_info['dataFile']['id'],
            'filename': filename,
            'date_fin': int(parsed['date_fin'])
        })

    total_deleted = 0
    for (variable, version), files in sorted(groups.items()):
        if len(files) <= 1:
            continue
        max_date = max(f['date_fin'] for f in files)
        to_delete = [f for f in files if f['date_fin'] < max_date]
        print(f"\n{variable}/{version} — {len(to_delete)} obsolète(s)")
        for f in to_delete:
            del_response = requests.delete(
                f"{RDG_BASE_URL}/api/files/{f['id']}",
                headers=headers
            )
            if del_response.status_code in [200, 204]:
                print(f"   🗑️  {f['filename']}")
                total_deleted += 1
            else:
                print(f"   ❌ {f['filename']} : {del_response.text}")

    print(f"\n📊 Total supprimé : {total_deleted} fichier(s)")
    

def clean_s3(S3_BUCKET: str,
             S3_PREFIX: str = "",
             S3_ACCESS_KEY: str = os.getenv("S3_ACCESS_KEY"),
             S3_SECRET_KEY: str = os.getenv("S3_SECRET_KEY"),
             S3_ENDPOINT: str = os.getenv("S3_ENDPOINT"),
             S3_REGION: str = os.getenv("S3_REGION", "eu-west-1")):
    """
    Supprime les fichiers obsolètes par variable et par version.
    Garde uniquement le fichier le plus récent pour chaque couple (variable, version).
    """
    s3 = boto3.client('s3',
                      aws_access_key_id=S3_ACCESS_KEY,
                      aws_secret_access_key=S3_SECRET_KEY,
                      endpoint_url=S3_ENDPOINT,
                      region_name=S3_REGION)
    print("\nNETTOYAGE S3")
    print(f"   Bucket: {S3_BUCKET}/{S3_PREFIX or ''}")

    all_keys = []
    paginator = s3.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=S3_PREFIX):
        for obj in page.get('Contents', []):
            all_keys.append(obj['Key'])

    from collections import defaultdict
    groups = defaultdict(list)
    for key in all_keys:
        filename = Path(key).name
        if not filename.endswith('.nc'):
            continue
        parsed = parse_filename(filename)
        if not parsed:
            continue
        group_key = (parsed['variable'], parsed['version'])
        groups[group_key].append({
            'key': key,
            'filename': filename,
            'date_fin': int(parsed['date_fin'])
        })

    total_deleted = 0
    for (variable, version), files in sorted(groups.items()):
        if len(files) <= 1:
            continue
        max_date = max(f['date_fin'] for f in files)
        to_delete = [f for f in files if f['date_fin'] < max_date]
        print(f"\n{variable}/{version} — {len(to_delete)} obsolète(s)")
        for f in to_delete:
            try:
                s3.delete_object(Bucket=S3_BUCKET, Key=f['key'])
                print(f"   🗑️  {f['filename']}")
                total_deleted += 1
            except Exception as e:
                print(f"   ❌ {f['filename']} : {str(e)}")
    print(f"\n📊 Total supprimé : {total_deleted} fichier(s)")

