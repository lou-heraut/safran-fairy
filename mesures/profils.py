#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Louis Héraut <louis.heraut@inrae.fr>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Les deux ETP occupent-elles la même tranche de 24 heures, ou seulement le même jour ?

Corréler les deux ETP entre elles ne peut pas répondre : deux fenêtres décalées
de six heures se recouvrent sur dix-huit, et le maximum tombe en k = 0 dans les
deux cas. Il faut un troisième témoin dont la fenêtre est différente et connue.

La température T de SIM2 est en ]00UTC-00UTC], le jour civil. Une grandeur en
]06UTC-06UTC] portée par la date J recouvre le jour civil J sur dix-huit heures
et le jour civil J+1 sur six : son profil de corrélation contre T est donc
dissymétrique, penché vers J+1. Une grandeur en ]00UTC-00UTC] donnerait un
profil symétrique et plus piqué.

On compare donc le profil de l'ETP Hargreaves à celui de l'ETP de SIM2, dont la
fenêtre est établie. Deux profils superposables valent bien mieux qu'un
maximum commun en k = 0.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

HARGREAVES = sys.argv[1]
SIM2_ETP = sys.argv[2]
SIM2_T = sys.argv[3]
GRILLE = Path("resources/safran-grille_2026-09-03.csv")
LAGS = range(-2, 3)
N_POINTS = 30


def points_echantillon(n: int):
    grid = pd.read_csv(GRILLE, sep=";", decimal=",")
    grid = grid.rename(columns={"LAMBX (hm)": "x", "LAMBY (hm)": "y"})
    grid["x"] *= 100
    grid["y"] *= 100
    pas = max(1, len(grid) // n)
    echantillon = grid.iloc[::pas][:n]
    return list(zip(echantillon["y"], echantillon["x"]))


def series(path: str, variable: str, points) -> pd.DataFrame:
    with xr.open_dataset(path) as ds:
        y = xr.DataArray([p[0] for p in points], dims="point")
        x = xr.DataArray([p[1] for p in points], dims="point")
        extrait = ds[variable].sel(y=y, x=x).load()
    return pd.DataFrame(extrait.values, index=pd.DatetimeIndex(extrait.time.values))


def anomalies(df: pd.DataFrame) -> pd.DataFrame:
    return df - df.groupby(df.index.dayofyear).transform("mean")


def profil(a: pd.DataFrame, b: pd.DataFrame) -> dict[int, float]:
    """corr( a(J), b(J+k) ) pour chaque décalage."""
    resultats = {}
    for k in LAGS:
        gauche = a.iloc[max(0, -k): len(a) - max(0, k)].values
        droite = b.iloc[max(0, k): len(b) - max(0, -k)].values
        masque = np.isfinite(gauche) & np.isfinite(droite)
        resultats[k] = float(np.corrcoef(gauche[masque], droite[masque])[0, 1])
    return resultats


def main() -> None:
    points = points_echantillon(N_POINTS)

    hargreaves = series(HARGREAVES, "ETP_Q_H0175", points)
    etp_sim2 = series(SIM2_ETP, "ETP", points)
    temperature = series(SIM2_T, "T", points)

    commun = hargreaves.index.intersection(etp_sim2.index).intersection(
        temperature.index)
    print(f"{len(points)} mailles, recouvrement {commun[0].date()} à "
          f"{commun[-1].date()}, {len(commun)} jours\n")

    h = anomalies(hargreaves.loc[commun])
    e = anomalies(etp_sim2.loc[commun])
    t = anomalies(temperature.loc[commun])

    profil_h = profil(h, t)
    profil_e = profil(e, t)

    print("corrélation des anomalies contre la température T, ]00UTC-00UTC]")
    print()
    print("   k      ETP Hargreaves   ETP SIM2   écart")
    print("   " + "-" * 44)
    for k in LAGS:
        print(f"  {k:+d}          {profil_h[k]:.4f}       {profil_e[k]:.4f}   "
              f"{profil_h[k] - profil_e[k]:+.4f}")

    ecart_max = max(abs(profil_h[k] - profil_e[k]) for k in LAGS)
    print(f"\nécart maximal entre les deux profils : {ecart_max:.4f}")

    # La dissymétrie est la signature de la fenêtre : pour une grandeur en
    # ]06UTC-06UTC], la corrélation en k = +1 dépasse celle en k = -1.
    for nom, p in (("ETP Hargreaves", profil_h), ("ETP SIM2", profil_e)):
        print(f"{nom:16s} dissymétrie r(+1) - r(-1) = {p[1] - p[-1]:+.4f}")


if __name__ == "__main__":
    main()
