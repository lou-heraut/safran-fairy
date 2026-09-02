# SPDX-FileCopyrightText: 2026 Louis Héraut <louis.heraut@inrae.fr>
# SPDX-License-Identifier: GPL-3.0-or-later
import os
import gzip
import shutil
import requests
from pathlib import Path
from art import tprint



def decompress_file(gz_file, RAW_DIR):
    """Dézippe un fichier .gz dans le dossier RAW_DIR"""
    output_file = Path(RAW_DIR) / gz_file.stem

    print(f"\n📦 Décompression: {gz_file.name}")            
    print(f"   → {output_file}")
    
    with gzip.open(gz_file, 'rb') as f_in:
        with open(output_file, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)  
    return output_file


def decompress(DOWNLOAD_DIR, RAW_DIR, downloaded_files=None):
    """
    Décompresse les fichiers .csv.gz en fichiers CSV bruts.

    Args:
        DOWNLOAD_DIR (str | Path):         Dossier contenant les fichiers .csv.gz.
        RAW_DIR (str | Path):              Dossier de destination pour les fichiers décompressés.
                                           Créé automatiquement s'il n'existe pas.
        downloaded_files (list[str], optional): Noms des fichiers à traiter.
                                                Si None, traite tous les *.csv.gz de DOWNLOAD_DIR.

    Returns:
        list[Path]: Chemins des fichiers CSV décompressés.
                    Ex: [RAW_DIR/QUOT_SIM2_1958-1959.csv, ...]
    """

    tprint("decompress", "small")

    Path(RAW_DIR).mkdir(parents=True, exist_ok=True)    
    if downloaded_files is None:
        downloaded_files = list(Path(DOWNLOAD_DIR).glob("*.csv.gz"))
        
    print("DÉCOMPRESSION")
    
    decompressed_files = []    
    for i, file in enumerate(downloaded_files, start=1):
        print(f"\n[{i}/{len(downloaded_files)}]")
        output_file = decompress_file(file, RAW_DIR)
        decompressed_files.append(output_file)
        
    print("\nRÉSUMÉ")
    print(f"   - {len(decompressed_files)} fichier(s) décompressés")
    print(f"   - 📁 Dossier: {os.path.abspath(RAW_DIR)}")
        
    return decompressed_files
