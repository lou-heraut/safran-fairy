#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Louis Héraut <louis.heraut@inrae.fr>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Sur quelle date l'ETP FAO Hargreaves s'aligne-t-elle, comparée à celle de SIM2.

La fenêtre d'agrégation quotidienne de l'ETP FAO Hargreaves n'est écrite dans
aucun document du producteur. Ce que l'on peut mesurer, c'est son alignement
avec l'ETP de SIM2, dont la fenêtre est établie : les deux sont la même
grandeur sur la même grille, issues de la même réanalyse, et ne diffèrent que
par le terme de rayonnement, réel pour l'une, estimé par Hargreaves pour l'autre.

Le cycle saisonnier est retiré avant de corréler : brut, il domine tout et un
décalage d'un jour se voit à peine. Sur les anomalies, il se voit.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

HARGREAVES = sys.argv[1]
SIM2 = sys.argv[2]
GRILLE = Path("resources/safran-grille_2026-09-03.csv")
LAGS = range(-2, 3)
N_POINTS = 30


def points_echantillon(n: int) -> list[tuple[int, int]]:
    """n mailles réparties dans le domaine, prises dans la grille de référence."""
    grid = pd.read_csv(GRILLE, sep=";", decimal=",")
    grid = grid.rename(columns={"LAMBX (hm)": "x", "LAMBY (hm)": "y"})
    grid["x"] *= 100
    grid["y"] *= 100
    pas = max(1, len(grid) // n)
    echantillon = grid.iloc[::pas][:n]
    return list(zip(echantillon["y"], echantillon["x"]))


def series(path: str, variable: str, points) -> pd.DataFrame:
    """Une colonne par maille, indexée par date."""
    with xr.open_dataset(path) as ds:
        y = xr.DataArray([p[0] for p in points], dims="point")
        x = xr.DataArray([p[1] for p in points], dims="point")
        extrait = ds[variable].sel(y=y, x=x).load()
    return pd.DataFrame(extrait.values, index=pd.DatetimeIndex(extrait.time.values))


def anomalies(df: pd.DataFrame) -> pd.DataFrame:
    """Retire le cycle saisonnier, jour de l'année par jour de l'année."""
    return df - df.groupby(df.index.dayofyear).transform("mean")


def main() -> None:
    points = points_echantillon(N_POINTS)
    print(f"{len(points)} mailles échantillonnées\n")

    hargreaves = series(HARGREAVES, "ETP_Q_H0175", points)
    sim2 = series(SIM2, "ETP", points)

    commun = hargreaves.index.intersection(sim2.index)
    hargreaves, sim2 = hargreaves.loc[commun], sim2.loc[commun]
    print(f"recouvrement : {commun[0].date()} à {commun[-1].date()}, "
          f"{len(commun)} jours\n")

    a = anomalies(hargreaves)
    b = anomalies(sim2)

    print("décalage k      corrélation des anomalies")
    print("            ETP_Q_H0175(J) contre ETP_SIM2(J+k)")
    print("-" * 52)
    resultats = {}
    for k in LAGS:
        gauche = a.iloc[max(0, -k): len(a) - max(0, k)].values
        droite = b.iloc[max(0, k): len(b) - max(0, -k)].values
        masque = np.isfinite(gauche) & np.isfinite(droite)
        r = np.corrcoef(gauche[masque], droite[masque])[0, 1]
        resultats[k] = r
        print(f"   {k:+d}              {r:.4f}"
              + ("   <-- maximum" if r == max(resultats.values()) else ""))

    meilleur = max(resultats, key=resultats.get)
    second = sorted(resultats.values())[-2]
    print(f"\nmaximum en k = {meilleur:+d}, écart au second : "
          f"{resultats[meilleur] - second:.4f}")

    # Contrôle croisé : la même mesure sur le niveau brut, pour montrer que le
    # cycle saisonnier rendrait le test aveugle.
    print("\nsur les valeurs brutes, pour comparaison :")
    for k in LAGS:
        gauche = hargreaves.iloc[max(0, -k): len(a) - max(0, k)].values
        droite = sim2.iloc[max(0, k): len(b) - max(0, -k)].values
        masque = np.isfinite(gauche) & np.isfinite(droite)
        r = np.corrcoef(gauche[masque], droite[masque])[0, 1]
        print(f"   {k:+d}              {r:.4f}")


if __name__ == "__main__":
    main()
