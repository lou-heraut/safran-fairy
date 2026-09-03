# SPDX-FileCopyrightText: 2026 Louis Héraut <louis.heraut@inrae.fr>
# SPDX-License-Identifier: GPL-3.0-or-later
import os
import requests
import json
import time
from pathlib import Path
from .report import banner, humain, line, phase, summary
import boto3
import mimetypes

from .tools import parse_filename

    
def apply_s3_bucket_policy(S3_BUCKET: str,
                           S3_ACCESS_KEY: str = os.getenv("S3_ACCESS_KEY"),
                           S3_SECRET_KEY: str = os.getenv("S3_SECRET_KEY"),
                           S3_ENDPOINT: str = os.getenv("S3_ENDPOINT"),
                           S3_REGION: str = os.getenv("S3_REGION", "eu-west-1")):
    s3 = boto3.client('s3',
                      aws_access_key_id=S3_ACCESS_KEY,
                      aws_secret_access_key=S3_SECRET_KEY,
                      endpoint_url=S3_ENDPOINT,
                      region_name=S3_REGION)
    policy = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "PublicRead",
            "Effect": "Allow",
            "Principal": "*",
            "Action": "s3:GetObject",
            "Resource": f"arn:aws:s3:::{S3_BUCKET}/*"
        }]
    })
    try:
        s3.put_bucket_policy(Bucket=S3_BUCKET, Policy=policy)
        print(f"✅ Policy appliquée sur {S3_BUCKET}")
    except Exception as e:
        print(f"❌ Erreur : {str(e)}")

        
def apply_s3_bucket_cors(S3_BUCKET: str,
                         S3_ACCESS_KEY: str = os.getenv("S3_ACCESS_KEY"),
                         S3_SECRET_KEY: str = os.getenv("S3_SECRET_KEY"),
                         S3_ENDPOINT: str = os.getenv("S3_ENDPOINT"),
                         S3_REGION: str = os.getenv("S3_REGION", "eu-west-1")):
    s3 = boto3.client('s3',
                      aws_access_key_id=S3_ACCESS_KEY,
                      aws_secret_access_key=S3_SECRET_KEY,
                      endpoint_url=S3_ENDPOINT,
                      region_name=S3_REGION)
    cors = {
        "CORSRules": [{
            "AllowedOrigins": ["*"],
            "AllowedMethods": ["GET"],
            "AllowedHeaders": ["*"],
            "MaxAgeSeconds": 3000
        }]
    }
    try:
        s3.put_bucket_cors(Bucket=S3_BUCKET, CORSConfiguration=cors)
        print(f"✅ CORS appliqué sur {S3_BUCKET}")
    except Exception as e:
        print(f"❌ Erreur : {str(e)}")
        
        
def list_s3_files(S3_BUCKET: str,
                  S3_PREFIX: str = "",
                  extension: str = None,
                  S3_ACCESS_KEY: str = os.getenv("S3_ACCESS_KEY"),
                  S3_SECRET_KEY: str = os.getenv("S3_SECRET_KEY"),
                  S3_ENDPOINT: str = os.getenv("S3_ENDPOINT"),
                  S3_REGION: str = os.getenv("S3_REGION")):
    """
    Liste les fichiers d'un bucket S3.
    """
    s3 = boto3.client('s3',
                      aws_access_key_id=S3_ACCESS_KEY,
                      aws_secret_access_key=S3_SECRET_KEY,
                      endpoint_url=S3_ENDPOINT,
                      region_name=S3_REGION)

    paginator = s3.get_paginator('list_objects_v2')
    files = []
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=S3_PREFIX):
        for obj in page.get('Contents', []):
            if extension is None or obj['Key'].endswith(extension):
                files.append(obj['Key'])
                print(obj['Key'])

    print(f"\n📊 {len(files)} fichier(s) trouvé(s)")
    return files


def to_upload(local_paths: list,
              S3_BUCKET: str,
              S3_PREFIX: str = "",
              S3_ACCESS_KEY: str = None,
              S3_SECRET_KEY: str = None,
              S3_ENDPOINT: str = None,
              S3_REGION: str = None) -> tuple:
    """
    Départage les fichiers à envoyer de ceux que le bucket a déjà.

    La décision se prend en regardant le bucket, jamais le fait qu'on vienne ou
    non de reconstruire : sinon un envoi ayant échoué la veille ne serait jamais
    rattrapé, et l'assemblage sautant désormais ce qui est à jour, plus rien ne
    le corrigerait.

    Args:
        local_paths (list[Path]): fichiers candidats à l'envoi.

    Returns:
        tuple[list[Path], list[Path]]: ceux à envoyer, ceux déjà à jour.

    Notes:
        - La comparaison porte sur la présence et la taille. L'ETag ne peut pas
          servir : boto3 envoie ces fichiers en plusieurs parties, et l'ETag
          n'est alors pas la somme MD5 du contenu.
        - Deux contenus différents de taille rigoureusement identique passeraient
          au travers. Sur des NetCDF compressés de plusieurs centaines de méga-
          octets c'est hautement improbable, mais ce n'est pas une preuve : la
          comparaison deviendra exacte quand le catalogue portera « file:checksum ».
    """
    s3 = boto3.client('s3',
                      aws_access_key_id=S3_ACCESS_KEY,
                      aws_secret_access_key=S3_SECRET_KEY,
                      endpoint_url=S3_ENDPOINT,
                      region_name=S3_REGION)

    distant = {}
    prefix = S3_PREFIX.strip("/") + "/" if S3_PREFIX else ""
    for page in s3.get_paginator('list_objects_v2').paginate(Bucket=S3_BUCKET,
                                                             Prefix=prefix):
        for obj in page.get('Contents', []):
            distant[Path(obj['Key']).name] = obj['Size']

    a_envoyer, a_jour = [], []
    for path in local_paths:
        path = Path(path)
        taille = distant.get(path.name)
        if taille is None or taille != path.stat().st_size:
            a_envoyer.append(path)
        else:
            a_jour.append(path)
    return a_envoyer, a_jour


def get_content_type(filename: str) -> str:
    content_type, _ = mimetypes.guess_type(filename)
    return content_type or "application/octet-stream"


def upload_s3(local_paths: list,
              S3_BUCKET: str,
              s3_paths: list = None,
              S3_PREFIX: str = "",
              S3_ACCESS_KEY: str = None,
              S3_SECRET_KEY: str = None,
              S3_ENDPOINT: str = None,
              S3_REGION: str = None) -> list:
    """Upload une liste de fichiers sur S3."""

    s3 = boto3.client('s3',
                      aws_access_key_id=S3_ACCESS_KEY,
                      aws_secret_access_key=S3_SECRET_KEY,
                      endpoint_url=S3_ENDPOINT,
                      region_name=S3_REGION)

    # Si pas de s3_paths, on utilise les local_paths
    if s3_paths is None:
        s3_paths = local_paths

    banner("upload")

    not_uploaded = []
    for i, (local_path, s3_path) in enumerate(zip(local_paths, s3_paths)):
        # s3_key = f"{S3_PREFIX}/{s3_path}".lstrip("/")
        s3_key = "/".join([S3_PREFIX.strip("/"), str(s3_path).strip("/")])
        try:
            file_size = os.path.getsize(local_path) / (1024**2)
            start_time = time.time()
            s3.upload_file(
                local_path, S3_BUCKET, s3_key,
                ExtraArgs={'ContentType': get_content_type(local_path)}
            )
            elapsed = time.time() - start_time
            line(f"[{i+1}/{len(local_paths)}] {Path(s3_key).name:52s} "
                 f"{humain(file_size * 1e6):>8s} à {file_size/elapsed:.1f} Mo/s")
        except Exception as e:
            line(f"❌ {Path(s3_key).name} : {e}")
            not_uploaded.append(local_path)

    summary(envoyes=len(local_paths) - len(not_uploaded), echecs=len(not_uploaded))
    return not_uploaded

def delete_s3_files(keys: list,
                    S3_BUCKET: str,
                    S3_ACCESS_KEY: str = os.getenv("S3_ACCESS_KEY"),
                    S3_SECRET_KEY: str = os.getenv("S3_SECRET_KEY"),
                    S3_ENDPOINT: str = os.getenv("S3_ENDPOINT"),
                    S3_REGION: str = os.getenv("S3_REGION", "eu-west-1")):
    s3 = boto3.client('s3',
                      aws_access_key_id=S3_ACCESS_KEY,
                      aws_secret_access_key=S3_SECRET_KEY,
                      endpoint_url=S3_ENDPOINT,
                      region_name=S3_REGION)
    for key in keys:
        s3.delete_object(Bucket=S3_BUCKET, Key=key)
        print(f"🗑️  {key}")
