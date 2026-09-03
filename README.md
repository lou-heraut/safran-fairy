```
                                                    _ ,       
 ݁₊                            . ݁       ⊹₊         ,- -      ⊹ . ݁     ₊ 
 ____  ₊ ݁.._   ⟡ _____  ____      _     _   _    _||_    _    '             
/ ___|₊ ⊹ / \   |  ___||  _ \. ݁₊ / \ ⟡ | \ | |  ' ||    < \, \\ ,._-_ '\\/\\ 
\___ \   / _ \  | |_   | |_) |  / _ \  |  \| |    || ⊹  /-|| ||  || ₊. || ;' 
 ___) | / ___ \ |  _|  |  _ < ⊹/ ___ \ | |\  |    |,   (( || ||  ||    ||/   
|____/ /_/   \_\|_|  ݁ .|_| \_\/_/   \_\|_| \_|  _-/     \/\\ \\  \\,   |/  
SAFRAN Fairy                                     . ݁. ݁       ⊹ ₊.      (      
                                                                       -_-
```


**Les données SIM2 de Météo-France, une variable par fichier NetCDF, prêtes à
l'emploi.**

SIM2 est la réanalyse hydrométéorologique de Météo-France sur la France
métropolitaine : une grille de 8 km, 26 variables quotidiennes, du 1er août 1958
à avant-hier. Température, précipitations, évapotranspiration, humidité des sols,
manteau neigeux, drainage, ruissellement.

Météo-France la publie en CSV compressés découpés par année, toutes variables
mélangées, soit 9,4 Go à télécharger et une quarantaine de gigaoctets à
décompresser pour qui ne veut qu'une seule variable. Ce dépôt fait le travail
une fois pour toutes et publie **un fichier NetCDF par variable, couvrant toute
la chronique**, sur un stockage ouvert avec un catalogue STAC.

Les valeurs ne sont ni corrigées ni recalculées. Elles sont transposées.

## Sommaire

- [Accéder aux données](#accéder-aux-données)
- [À quoi ressemblent les données](#à-quoi-ressemblent-les-données)
- [Relire les données en Python](#relire-les-données-en-python)
- [Relire les données en R](#relire-les-données-en-r)
- [Ce qu'il faut savoir avant d'analyser](#ce-quil-faut-savoir-avant-danalyser)
- [Comment les fichiers sont fabriqués](#comment-les-fichiers-sont-fabriqués)
- [Citer](#citer)
- [Licence](#licence)
- [Liens](#liens)

---

## Accéder aux données

Le plus simple est de parcourir le catalogue, qui décrit chaque fichier, sa
couverture temporelle et son emprise :

<https://catalog.riverly-data-lake.inrae.fr>

Pour récupérer un fichier directement, l'adresse suit toujours la même forme :

```
https://s3-data.meso.umontpellier.fr/riverly-data-lake/data/safran-fairy/<VARIABLE>_QUOT_SIM2_<début>-<fin>.nc
```

```bash
# la température quotidienne, toute la chronique
curl -O https://s3-data.meso.umontpellier.fr/riverly-data-lake/data/safran-fairy/T_QUOT_SIM2_19580801-20260901.nc
```

Les dates du nom changent à chaque mise à jour. Pour un script qui doit rester
valide, mieux vaut demander l'adresse au catalogue plutôt que de la composer,
ce que montre la section Python plus bas.

## À quoi ressemblent les données

Un fichier par variable, nommé avec sa couverture réelle.

```
T_QUOT_SIM2_19580801-20260901.nc          température moyenne
PRENEI_QUOT_SIM2_19580801-20260901.nc     précipitations solides
...                                        26 fichiers, environ 9 Go au total
```

Le poids va de 90 Mo pour les précipitations solides, très souvent nulles donc
très compressibles, à 850 Mo pour l'indice de sécheresse des sols.

Chaque fichier contient un cube de trois dimensions.

```
dimension    taille    description
-----------------------------------------------------------------------
time         24 869    un pas par jour, du 1958-08-01 à avant-hier
y               134    Lambert II étendu, de 1 617 000 à 2 681 000 m
x               143    Lambert II étendu, de    60 000 à 1 196 000 m
```

La grille fait donc 143 sur 134, mais **le domaine SAFRAN n'est pas
rectangulaire** : seules 9 892 mailles portent des valeurs, les autres sont à
`NaN`. C'est normal, ce sont la mer et l'étranger.

Le système de coordonnées est le Lambert II étendu, EPSG:27572, déclaré dans le
fichier. Deux tableaux `latitude` et `longitude` sont fournis en plus, pour
situer un point sans avoir à reprojeter.

### Les 26 variables

| Variable | Description | Unité | Fenêtre d'agrégation |
|---|---|---|---|
| `PRENEI` | Précipitations solides | mm | ]06UTC-06UTC] |
| `PRELIQ` | Précipitations liquides | mm | ]06UTC-06UTC] |
| `T` | Température | °C | ]00UTC-00UTC] |
| `FF` | Vent | m/s | ]00UTC-00UTC] |
| `Q` | Humidité spécifique | g/kg | ]00UTC-00UTC] |
| `DLI` | Rayonnement atmosphérique | J/cm2 | ]00UTC-00UTC] |
| `SSI` | Rayonnement visible | J/cm2 | ]00UTC-00UTC] |
| `HU` | Humidité relative | % | ]00UTC-00UTC] |
| `EVAP` | Evapotranspiration totale | mm | ]06UTC-06UTC] |
| `ETP` | Evapotranspiration potentielle (Penman-Monteith FAO-56) | mm | ]06UTC-06UTC] |
| `PE` | Pluies efficaces | mm | ]06UTC-06UTC] |
| `SWI` | Indice d'humidité des sols | % | ]06UTC-06UTC] |
| `SSWI_10J` | Indice sécheresse de l'humidité des sols sur 10 jours | sans unité | - |
| `DRAINC` | Drainage | mm | ]06UTC-06UTC] |
| `RUNC` | Ruissellement | mm | ]06UTC-06UTC] |
| `RESR_NEIGE` | Equivalent en eau du manteau neigeux | mm | ]06UTC-06UTC] |
| `RESR_NEIGE6` | Equivalent en eau du manteau neigeux à 06 UTC | mm | 06UTC |
| `HTEURNEIGE` | Epaisseur du manteau neigeux | m | ]06UTC-06UTC] |
| `HTEURNEIGE6` | Epaisseur du manteau neigeux à 06 UTC | m | 06UTC |
| `HTEURNEIGEX` | Epaisseur du manteau neigeux horaire maximum | m | - |
| `SNOW_FRAC` | Fraction de maille recouverte par la neige | % | ]06UTC-06UTC] |
| `ECOULEMENT` | Ecoulement à la base du manteau neigeux | mm | ]06UTC-06UTC] |
| `WG_RACINE` | Contenu en eau liquide dans la couche racinaire à 06 UTC | m3/m3 | 06UTC |
| `WGI_RACINE` | Contenu en eau gelée dans la couche racinaire à 06 UTC | m3/m3 | 06UTC |
| `TINF_H` | Température minimale des 24 températures horaires | °C | ]18UTC-18UTC] |
| `TSUP_H` | Température maximale des 24 températures horaires | °C | ]06UTC-06UTC] |

Les unités sont écrites dans le fichier au format udunits, que les outils
savent analyser : `degC` plutôt que `°C`, `m s-1` plutôt que `m/s`. C'est la
même unité, écrite autrement.

## Relire les données en Python

```python
import xarray as xr

ds = xr.open_dataset("T_QUOT_SIM2_19580801-20260901.nc")

# une chronique en un point de grille
serie = ds.T.sel(x=852000, y=2065000)

# une moyenne sur une emprise, ce pour quoi les fichiers sont optimisés
bassin = ds.T.sel(x=slice(800000, 900000), y=slice(2000000, 2100000))
chronique = bassin.mean(dim=("x", "y"))

# une carte à une date
carte = ds.T.sel(time="2003-08-12")
```

Pour trouver l'adresse du fichier le plus récent sans la composer à la main :

```python
import requests

collection = "https://catalog.riverly-data-lake.inrae.fr/safran-fairy/collection.json"
liens = requests.get(collection).json()["links"]
item = next(l for l in liens if l["rel"] == "item" and "/T_SIM2" in l["href"])
url = requests.get(item["href"]).json()["assets"]["data"]["href"]
```

## Relire les données en R

Avec `terra`, qui lit le fichier comme une pile de rasters géoréférencés :

```r
library(terra)

r <- rast("T_QUOT_SIM2_19580801-20260901.nc")

# une carte à une date
plot(r[[16448]])

# une chronique en un point, en Lambert II étendu
extract(r, cbind(852000, 2065000))
```

Ou avec `ncdf4`, pour aller chercher une tranche précise sans tout charger :

```r
library(ncdf4)

nc <- nc_open("T_QUOT_SIM2_19580801-20260901.nc")

# les dimensions se présentent dans l'ordre x, y, time
x <- ncvar_get(nc, "x")
y <- ncvar_get(nc, "y")
serie <- ncvar_get(nc, "T",
                   start = c(which(x == 852000), which(y == 2065000), 1),
                   count = c(1, 1, -1))
temps <- as.Date(ncvar_get(nc, "time"), origin = "1970-01-01")
nc_close(nc)
```

## Ce qu'il faut savoir avant d'analyser

### Les variables n'ont pas toutes la même journée

C'est le piège principal, et il n'est écrit dans aucune documentation
Météo-France. Selon la variable, la valeur portée par une date ne couvre pas la
même fenêtre de 24 heures.

| Fenêtre | Variables | Ce que couvre la date J |
|---|---|---|
| `]00UTC-00UTC]` | `T`, `FF`, `Q`, `DLI`, `SSI`, `HU` | le jour civil J |
| `]06UTC-06UTC]` | précipitations, bilan hydrique, neige, `TSUP_H` | de J 06 UTC à J+1 06 UTC |
| `]18UTC-18UTC]` | `TINF_H` | de J-1 18 UTC à J 18 UTC |
| `06UTC` | `RESR_NEIGE6`, `HTEURNEIGE6`, `WG_RACINE`, `WGI_RACINE` | l'instant J 06 UTC |

Concrètement, la température minimale du jour J couvre la nuit qui **précède**
la journée, la maximale couvre l'après-midi qui la **suit**. C'est la convention
météorologique française. Cumuler des précipitations et des températures sur la
même date revient donc à additionner des fenêtres décalées de six heures.

Ces bornes sont écrites dans les fichiers, en `time_bnds`, donc lisibles par un
programme. Le sens de chaque fenêtre a été établi sur les données elles-mêmes,
la documentation ne le précisant pas.

### Les dernières semaines ne sont pas définitives

Météo-France révise les quatre dernières années deux fois par mois. Ce ne sont
pas des retouches marginales : entre le 4 août et le 2 septembre 2026, 73 % des
mailles de juillet 2026 ont changé sur la température, jusqu'à 3,5 °C.

Un fichier téléchargé aujourd'hui est donc juste, mais sa fin bougera. Pour un
travail reproductible, notez la date de téléchargement et la couverture indiquée
dans le nom du fichier.

### L'évapotranspiration a changé de formule

`ETP` est désormais calculée selon Penman-Monteith FAO-56, et Météo-France a
recalculé toute la chronique depuis 1958. Les valeurs diffèrent de l'ancienne
version sur la quasi-totalité des jours. **Si vous avez téléchargé de l'ETP SIM2
avant l'été 2026, elle est périmée.** Les 25 autres variables sont inchangées.

### Une chronique est rapide, la France entière ne l'est pas

Les fichiers sont découpés en interne pour l'usage dominant, l'extraction de
chroniques sur un point ou un bassin.

```
moyenne sur un bassin de 40 km      0,17 s
moyenne sur un bassin de 160 km     0,66 s
une carte à une date                0,06 s
moyenne sur la France entière         11 s
```

Le dernier cas lit forcément tout le fichier, aucun découpage n'y change rien.
Si vous enchaînez ce genre de calcul, chargez une fois et réutilisez.

## Comment les fichiers sont fabriqués

```
data.gouv.fr  ->  décompression  ->  découpage par variable  ->  NetCDF annuel
                                                                      |
                          fichier publié  <-  assemblage de la chronique
```

Le cache annuel est la seule source de vérité : la chronique publiée en est une
concaténation, prolongée par la fenêtre glissante de 60 jours pour les jours que
les fichiers annuels ne couvrent pas encore. Rien n'est publié sans qu'un
contrôle structurel ait accepté le fichier : axe temporel strictement croissant,
sans doublon ni trou, grille et métadonnées conformes.

L'installation et l'exploitation du service sont décrites dans
[INSTALL.md](INSTALL.md).

```
safran_fairy/sources.py      ce que publie data.gouv.fr, et rien d'autre
safran_fairy/download.py     miroir local, incrémental
safran_fairy/split.py        découpage des CSV par variable
safran_fairy/convert.py      écriture des NetCDF et des métadonnées
safran_fairy/build.py        assemblage de la chronique
safran_fairy/check.py        contrôle bloquant avant publication
safran_fairy/catalog.py      catalogue STAC
safran_fairy/upload_s3.py    publication
```

Le code et ses commentaires sont en anglais, les messages affichés en français.
Les noms de variables restent ceux de Météo-France, pour rester traçables
jusqu'à sa documentation.

## Citer

Deux choses distinctes sont à citer. **Les données**, qui ne sont pas produites
ici :

> Météo-France. Données changement climatique SIM quotidienne
> (SAFRAN-ISBA-MODCOU). <https://doi.org/10.57745/BAZ12C>

**Et ce dépôt**, si sa mise en forme vous a servi. Les métadonnées sont dans
[CITATION.cff](CITATION.cff), que GitHub affiche via le bouton
« Cite this repository ».

## Licence

**Le code de ce dépôt** est sous licence GNU General Public License v3.0 ou
ultérieure (`GPL-3.0-or-later`). Le texte complet est dans [LICENSE](LICENSE).

**Les données SIM2 ne sont pas couvertes par cette licence.** Elles sont
produites par Météo-France et restent sous Licence Ouverte / Open Licence 2.0
(Etalab). Voir [AUTHORS.md](AUTHORS.md).

## Liens

- Le jeu de données source :
  <https://www.data.gouv.fr/datasets/6569b27598256cc583c917a7>
- Le catalogue de ce dépôt : <https://catalog.riverly-data-lake.inrae.fr>
- Le modèle SIM :
  <https://www.umr-cnrm.fr/spip.php?article1092>
- Le projet Explore2, qui a motivé la mise à disposition :
  <https://entrepot.recherche.data.gouv.fr/dataverse/explore2>
