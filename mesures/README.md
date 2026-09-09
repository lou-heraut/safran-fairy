# Mesures

Le code derrière les chiffres que le dépôt affirme. Une affirmation chiffrée est
une mesure, et une mesure qu'on ne peut pas refaire n'en est plus tout à fait
une : ces scripts sont là pour qu'on puisse la refaire.

Ils se lancent depuis la racine du dépôt, dont les chemins sont relatifs.

| Script | Ce qu'il établit |
|---|---|
| `alignement.py` | Que l'ETP FAO Hargreaves porte le même jour que l'ETP de SIM2, sans décalage. C'est le `0,885 contre 0,572` de l'attribut `comment` du fichier Hargreaves. |
| `profils.py` | Que les deux ETP penchent de la même façon par rapport au jour civil, mesuré contre la température. C'est le `+0,072 contre +0,100` du commit `8a96753`. |

```bash
python mesures/alignement.py annexe-etp/ETP_Q_H0175_QUOT_SIM2_19700101-20241231.nc ETP_SIM2.nc
python mesures/profils.py    annexe-etp/ETP_Q_H0175_QUOT_SIM2_19700101-20241231.nc ETP_SIM2.nc T_SIM2.nc
```

Les fichiers SIM2 se récupèrent sur le bucket, le catalogue en donne l'adresse.

La place de ce dossier n'est pas tranchée : voir la phase 8 de
[chantier.md](../chantier.md).
