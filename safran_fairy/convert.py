# SPDX-FileCopyrightText: 2026 Louis Héraut <louis.heraut@inrae.fr>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Turn the per variable Parquet files into georeferenced NetCDF.

The storage layout is chosen here and inherited by the assembled file, since
ncrcat takes the chunking of its first input.
"""

import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import xarray as xr
from art import tprint


# Storage layout of the produced NetCDF, in (time, y, x). The spatial tile is
# what matters: with 16 x 16 tiles a basin average over the whole record costs
# 0,17 s instead of 8,70 s. The time depth barely changes those reads, and a
# small one keeps map reads fast, so it is fixed rather than derived from the
# file length: that way the layout of the assembled file does not depend on
# which yearly file comes first. Measured, see chantier.md phase 4.
TIME_CHUNK = 128
SPACE_CHUNK = 16

CONVENTIONS = "CF-1.10"
REFERENCES = ("https://www.data.gouv.fr/datasets/6569b27598256cc583c917a7 ; "
              "https://doi.org/10.57745/BAZ12C")


def var_title(var, metadata_variables):
    """Human readable name of a variable, falling back on its code."""
    if var in metadata_variables.index:
        return str(metadata_variables.loc[var]['description'])
    return var


def create_netcdf(file, CONVERT_DIR, METADATA_VARIABLES_FILE):
    metadata_variables = pd.read_csv(METADATA_VARIABLES_FILE,
                                     index_col='variable')
    
    var = file.stem.split('_QUOT_SIM2')[0]
    print(f"\n🌐 Conversion NetCDF: {file.name}")
    print(f"   → variable: {var}")
    
    data = pd.read_parquet(file)
    data = data.rename(columns={"LAMBX": "L2_X", "LAMBY": "L2_Y", "DATE": "time"})
    data['L2_X'] = data['L2_X'] * 100
    data['L2_Y'] = data['L2_Y'] * 100
    data['time'] = pd.to_datetime(data['time'], format='%Y%m%d')
    
    print(f"   → {len(data['time'].unique())} pas de temps | {data['L2_X'].nunique()}x{data['L2_Y'].nunique()} points de grille")
    
    ds = (data.set_index(['time', 'L2_Y', 'L2_X'])
              .to_xarray()
              .rename({'L2_Y': 'y', 'L2_X': 'x'}))
    
    # Métadonnées globales
    ds.attrs['Conventions'] = CONVENTIONS
    ds.attrs['title'] = f"SIM2 {var} : {var_title(var, metadata_variables)}"
    ds.attrs['history'] = (
        f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} : produit par "
        f"safran-fairy depuis {file.name}")
    ds.attrs['references'] = REFERENCES
    ds.attrs['crs'] = 'EPSG:27572'
    ds.attrs['grid_mapping_name'] = 'lambert_conformal_conic'
    ds.attrs['spatial_resolution'] = '8 km (0.072°)'
    ds.attrs['projection'] = 'Lambert II étendu'
    ds.attrs['source'] = 'SAFRAN-ISBA-MODCOU (SIM2)'
    ds.attrs['institution'] = 'Météo-France'
    
    # Métadonnées des coordonnées
    ds['x'].attrs = {
        'standard_name': 'projection_x_coordinate',
        'long_name': 'x coordinate of projection (Lambert II étendu)',
        'units': 'm',
        'axis': 'X'
    }
    
    ds['y'].attrs = {
        'standard_name': 'projection_y_coordinate',
        'long_name': 'y coordinate of projection (Lambert II étendu)',
        'units': 'm',
        'axis': 'Y'
    }
    
    ds['time'].attrs = {
        'standard_name': 'time',
        'long_name': 'time',
        'axis': 'T'
    }
    
    # Variable CRS
    ds['crs'] = xr.DataArray(
        data=0,
        attrs={
            'grid_mapping_name': 'lambert_conformal_conic',
            'longitude_of_central_meridian': 2.337229,
            'latitude_of_projection_origin': 46.8,
            'standard_parallel': [45.898919, 47.696014],
            'false_easting': 600000.0,
            'false_northing': 2200000.0,
            'semi_major_axis': 6378249.2,
            'semi_minor_axis': 6356515.0,
            'inverse_flattening': 293.46602,
            'spatial_ref': 'EPSG:27572'
        }
    )
    
    # Métadonnées de la variable depuis le CSV
    if var in metadata_variables.index:
        var_meta = metadata_variables.loc[var]
        ds[var].attrs['long_name'] = var_meta['description']
        # "units" carries the udunits form, which CF requires: « °C » is not
        # parseable, « degC » is. The human readable form stays in long_name.
        ds[var].attrs['units'] = var_meta['unite_cf']
        for source, cible in [('standard_name', 'standard_name'),
                              ('cell_methods', 'cell_methods')]:
            valeur = var_meta[source]
            if pd.notna(valeur) and str(valeur).strip():
                ds[var].attrs[cible] = str(valeur)
        if pd.notna(var_meta['precision']):
            ds[var].attrs['precision'] = var_meta['precision']
        if pd.notna(var_meta['periode_agregation']):
            ds[var].attrs['aggregation_period'] = var_meta['periode_agregation']
        ds[var].attrs['grid_mapping'] = 'crs'
    
    output_file = CONVERT_DIR / file.with_suffix('.nc').name
    encoding = {
        var: {'zlib': True, 'complevel': 4, 'dtype': 'float32',
              'chunksizes': (min(TIME_CHUNK, ds.sizes['time']),
                             min(SPACE_CHUNK, ds.sizes['y']),
                             min(SPACE_CHUNK, ds.sizes['x']))},
        'time': {'units': 'days since 1970-01-01 00:00:00',
                 'calendar': 'standard', 'dtype': 'float64'}
    }
    
    ds.to_netcdf(output_file, encoding=encoding, unlimited_dims=['time'])
    print(f"   💾 {output_file.name}")
    
    return output_file


def convert(SPLIT_DIR, CONVERT_DIR, METADATA_VARIABLES_FILE,
            splited_files=None):
    """
    Convertit les fichiers Parquet en fichiers NetCDF géoréférencés.

    Args:
        SPLIT_DIR (str | Path):            Dossier contenant les fichiers Parquet.
        CONVERT_DIR (str | Path):          Dossier de sortie pour les fichiers NetCDF.
                                           Créé automatiquement s'il n'existe pas.
        splited_files (list[Path], optional): Fichiers Parquet à convertir.
                                              Si None, traite tous les *.parquet de SPLIT_DIR.

    Returns:
        list[Path]: Chemins des fichiers NetCDF créés.
                    Ex: [CONVERT_DIR/T_QUOT_SIM2_1958-1959.nc, ...]

    Notes:
        - CRS : EPSG:27572 (Lambert II étendu).
        - Compression : zlib niveau 4, variables en float32, time en float64.
    """
        
    SPLIT_DIR = Path(SPLIT_DIR)
    CONVERT_DIR = Path(CONVERT_DIR)
    CONVERT_DIR.mkdir(parents=True, exist_ok=True)

    if splited_files is None:
        splited_files = sorted(Path(SPLIT_DIR).glob("*.parquet"))

    tprint("convert", "small")
    print("CONVERSION")
        
    converted_files = []
    for i, file in enumerate(splited_files, start=1):
        print(f"\n[{i}/{len(splited_files)}]")
        output_file = create_netcdf(file, CONVERT_DIR,
                                    METADATA_VARIABLES_FILE)       
        converted_files.append(output_file)
        
    print("\nRÉSUMÉ")
    print(f"   - {len(converted_files)} fichier(s) converti(s)")
    print(f"   - 📁 Dossier: {os.path.abspath(CONVERT_DIR)}")
        
    return converted_files
