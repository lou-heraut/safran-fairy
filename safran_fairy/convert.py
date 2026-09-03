# SPDX-FileCopyrightText: 2026 Louis Héraut <louis.heraut@inrae.fr>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Turn the per variable Parquet files into georeferenced NetCDF.

The storage layout is chosen here and inherited by the assembled file, since
ncrcat takes the chunking of its first input.
"""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from pyproj import CRS

from .report import banner, humain, line, phase, summary


# Storage layout of the produced NetCDF, in (time, y, x). The spatial tile is
# what matters: with 16 x 16 tiles a basin average over the whole record costs
# 0,17 s instead of 8,70 s. The time depth barely changes those reads, and a
# small one keeps map reads fast, so it is fixed rather than derived from the
# file length: that way the layout of the assembled file does not depend on
# which yearly file comes first. Measured, see chantier.md phase 4.
TIME_CHUNK = 128
SPACE_CHUNK = 16

EPSG = 27572  # Lambert II étendu
CONVENTIONS = "CF-1.10"
REFERENCES = ("https://www.data.gouv.fr/datasets/6569b27598256cc583c917a7 ; "
              "https://doi.org/10.57745/BAZ12C")


def read_grid(METADATA_GRID_FILE):
    """
    Lit la grille de référence fournie par Météo-France.

    Returns:
        pandas.DataFrame: indexé par (y, x) en mètres, colonnes « lat » et « lon ».

    Notes:
        - Le fichier est en point-virgule et en virgule décimale.
        - Les coordonnées sont recopiées telles quelles, jamais reprojetées :
          c'est le producteur qui les donne.
    """
    grid = pd.read_csv(METADATA_GRID_FILE, sep=";", decimal=",")
    grid = grid.rename(columns={"LAMBX (hm)": "x", "LAMBY (hm)": "y",
                                "LAT_DG": "lat", "LON_DG": "lon"})
    grid["x"] *= 100
    grid["y"] *= 100
    return grid.set_index(["y", "x"])[["lat", "lon"]]


def regular_axes(METADATA_GRID_FILE):
    """
    Les axes x et y complets de la grille SAFRAN, au pas régulier de 8 km.

    Les axes sont tirés de la grille de référence et non des données présentes :
    une colonne du rectangle ne porte aucun point, et la reconstruire depuis les
    données la ferait disparaître, rendant l'axe irrégulier. Mesuré : dans cet
    état GDAL refuse de caler le fichier et le lit en coordonnées pixel. Cela
    garantit aussi que tous les fichiers annuels partagent exactement la même
    grille, ce dont ncrcat a besoin pour les concaténer.
    """
    grid = read_grid(METADATA_GRID_FILE).reset_index()
    pas = 8000
    x = np.arange(grid["x"].min(), grid["x"].max() + pas, pas)
    y = np.arange(grid["y"].min(), grid["y"].max() + pas, pas)
    return x, y


def add_lat_lon(ds, METADATA_GRID_FILE):
    """
    Ajoute latitude et longitude comme variables auxiliaires bidimensionnelles.

    Le fichier reste en Lambert II étendu ; ces deux tableaux s'ajoutent sans
    rien remplacer, pour qu'un utilisateur puisse situer un point sans savoir
    reprojeter. Coût mesuré : environ 150 Ko sur un fichier de 422 Mo.

    Elles s'appellent « latitude » et « longitude » et non « lat » et « lon » :
    le pilote netCDF de GDAL traite les noms courts comme des tableaux de
    géolocalisation et abandonne alors la géotransformation, ce qui rend le
    fichier illisible comme raster. Vérifié sur les deux formes.
    """
    grid = read_grid(METADATA_GRID_FILE)
    forme = (ds.sizes["y"], ds.sizes["x"])
    lat = np.full(forme, np.nan)
    lon = np.full(forme, np.nan)
    index_y = {v: i for i, v in enumerate(ds.y.values)}
    index_x = {v: i for i, v in enumerate(ds.x.values)}

    manquants = 0
    for (y, x), ligne in grid.iterrows():
        i, j = index_y.get(y), index_x.get(x)
        if i is None or j is None:
            manquants += 1
            continue
        lat[i, j], lon[i, j] = ligne["lat"], ligne["lon"]
    if manquants:
        print(f"   ⚠️  {manquants} point(s) de la grille hors du domaine du fichier")

    ds = ds.assign(
        latitude=(("y", "x"), lat, {"standard_name": "latitude",
                                    "long_name": "latitude",
                                    "units": "degrees_north"}),
        longitude=(("y", "x"), lon, {"standard_name": "longitude",
                                     "long_name": "longitude",
                                     "units": "degrees_east"}))
    return ds


def add_time_bounds(ds, bornes):
    """
    Ajoute les bornes de la fenêtre d'agrégation quotidienne.

    Args:
        bornes (str): décalages en heures depuis minuit UTC du jour porté par la
                      date, sous la forme « début:fin ». Ex: « 6:30 » pour
                      ]06UTC-06UTC], « -6:18 » pour ]18UTC-18UTC].

    Notes:
        - Le sens de ]06UTC-06UTC] est établi sur les données, sur 53 241 jours
          de fonte nivale ; celui de ]18UTC-18UTC] par corrélation. Voir
          chantier.md.
        - Rien n'est ajouté pour une valeur instantanée ou une fenêtre inconnue.
    """
    debut_h, fin_h = (int(v) for v in bornes.split(":"))
    jours = pd.DatetimeIndex(ds.time.values)
    bnds = np.stack([jours + timedelta(hours=debut_h),
                     jours + timedelta(hours=fin_h)], axis=1)
    ds = ds.assign(time_bnds=(("time", "nv"), bnds))
    ds.time.attrs["bounds"] = "time_bnds"
    return ds


def var_title(var, metadata_variables):
    """Human readable name of a variable, falling back on its code."""
    if var in metadata_variables.index:
        return str(metadata_variables.loc[var]['description'])
    return var


def create_netcdf(file, CONVERT_DIR, METADATA_VARIABLES_FILE,
                  METADATA_GRID_FILE=None):
    metadata_variables = pd.read_csv(METADATA_VARIABLES_FILE,
                                     index_col='variable')
    
    var = file.stem.split('_QUOT_SIM2')[0]
    
    data = pd.read_parquet(file)
    data = data.rename(columns={"LAMBX": "L2_X", "LAMBY": "L2_Y", "DATE": "time"})
    data['L2_X'] = data['L2_X'] * 100
    data['L2_Y'] = data['L2_Y'] * 100
    data['time'] = pd.to_datetime(data['time'], format='%Y%m%d')
    
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
    ds.attrs['crs'] = f'EPSG:{EPSG}'
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
            # WKT et non « EPSG:27572 » : GDAL lit ces deux attributs comme du
            # WKT, et échouait sur « missing [ » devant une chaîne qui n'en est
            # pas. Sans eux le fichier s'ouvre sans système de coordonnées, donc
            # ne se superpose à rien dans un SIG. Le WKT vient de la base EPSG
            # plutôt que d'être recopié, pour ne pas dériver.
            'crs_wkt': CRS.from_epsg(EPSG).to_wkt(),
            'spatial_ref': CRS.from_epsg(EPSG).to_wkt(),
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
    
    if METADATA_GRID_FILE:
        x, y = regular_axes(METADATA_GRID_FILE)
        # La grille vient de la référence : une colonne du rectangle ne porte
        # aucun point, et la déduire des données la ferait disparaître.
        ds = ds.reindex(x=x, y=y)
        ds = add_lat_lon(ds, METADATA_GRID_FILE)
    if var in metadata_variables.index:
        bornes = metadata_variables.loc[var]['bornes_h']
        if pd.notna(bornes) and str(bornes).strip():
            ds = add_time_bounds(ds, str(bornes).strip())

    output_file = CONVERT_DIR / file.with_suffix('.nc').name
    encoding = {
        var: {'zlib': True, 'complevel': 4, 'dtype': 'float32',
              'chunksizes': (min(TIME_CHUNK, ds.sizes['time']),
                             min(SPACE_CHUNK, ds.sizes['y']),
                             min(SPACE_CHUNK, ds.sizes['x']))},
        'time': {'units': 'days since 1970-01-01 00:00:00',
                 'calendar': 'standard', 'dtype': 'float64'},
        'latitude': {'zlib': True, 'complevel': 4, 'dtype': 'float32'},
        'longitude': {'zlib': True, 'complevel': 4, 'dtype': 'float32'},
    }
    if 'time_bnds' in ds:
        encoding['time_bnds'] = {'units': 'days since 1970-01-01 00:00:00',
                                 'calendar': 'standard', 'dtype': 'float64'}
    encoding = {k: v for k, v in encoding.items() if k in ds.variables}
    
    ds.to_netcdf(output_file, encoding=encoding, unlimited_dims=['time'])
    return output_file


def convert(SPLIT_DIR, CONVERT_DIR, METADATA_VARIABLES_FILE,
            splited_files=None, METADATA_GRID_FILE=None,
            verbose: bool = True):
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

    if verbose:
        banner("convert")
        phase("CONVERSION", f"{len(splited_files)} fichier(s)")

    converted_files = []
    for i, file in enumerate(splited_files, start=1):
        output_file = create_netcdf(file, CONVERT_DIR, METADATA_VARIABLES_FILE,
                                    METADATA_GRID_FILE)
        converted_files.append(output_file)
        if verbose:
            line(f"[{i}/{len(splited_files)}] {output_file.name}")

    if verbose:
        summary(netcdf=len(converted_files),
                volume=humain(sum(f.stat().st_size for f in converted_files)))
    return converted_files
