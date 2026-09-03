# Notes pour Claude Code

Trois documents se partagent le travail, et celui-ci ne répète aucun des deux
autres. [README.md](README.md) décrit **les données** pour qui veut s'en servir.
[INSTALL.md](INSTALL.md) décrit **l'exploitation** du service.
[chantier.md](chantier.md) porte **l'état du chantier** en cours. Ce fichier ne
contient que ce qui n'est ni dans l'un ni dans l'autre : les conventions, et les
faits mesurés qu'on risquerait de « corriger » par erreur.

## Contexte

Dépôt d'une famille : convention de nommage `get-data-<plateforme>-<jeu de
données>`. Voisins dans le dossier parent, `get-data-hubeau-onde`, le modèle de
référence, et `get-data-vigieau-secheresse`. Renommage prévu en
`get-data-meteofrance-sim2`.

Différence assumée : les voisins sont des téléchargeurs qu'on lance à la
demande. Celui-ci est un **service qui tourne en continu** et qui **republie**,
donc avec de l'état persistant sur le disque du serveur et sur le S3, et une
exigence d'idempotence que les autres n'ont pas. Les conventions d'écriture sont
communes, l'architecture d'exécution ne l'est pas.

## Interaction

Ne pas utiliser le widget de questions à choix multiples (`AskUserQuestion`).
Les arbitrages se posent en texte : les options, celle qui est recommandée, ce
qui les distingue, et la réponse arrive en prose. Le reproche porte sur le
format d'échange, pas sur la mise en forme : les tableaux et schémas ASCII sont
au contraire bienvenus.

## Conventions

- **Code et commentaires en anglais, messages affichés en français.** Les noms
  de variables climatiques restent ceux de Météo-France, pour rester traçables
  jusqu'à sa documentation.
- README, INSTALL, chantier, commits, en français, en prose.
- **Aucun tiret cadratin ni demi-cadratin.** Deux-points, virgule, parenthèses.
- Typographie française : guillemets `«  »`, espace avant `: ; ! ?`, milliers
  séparés par une espace, virgule décimale.
- Pas de superlatifs. **Les affirmations chiffrées sont des mesures**, jamais des
  estimations : ne pas en ajouter sans avoir vérifié, et marquer « à mesurer »
  ce qui ne l'a pas été. Les exemples de code du README ont tous été exécutés.
- En-tête SPDX en tête de chaque fichier Python.

## Environnement

Le venv est `.python_env/`, à activer avant toute commande. NCO est une
dépendance système, pas Python. `.env` porte `MODE` et `CONFIG_FILE`, qui
désigne le fichier de configuration à utiliser. Le reste est dans INSTALL.md.

Le bucket est en lecture publique mais le `ListObjects` anonyme est refusé :
pour savoir ce qui est publié sans les clés, passer par le catalogue STAC.

## Pièges à ne pas « corriger »

Tout ce qui suit est mesuré sur les fichiers réels. Les détails chiffrés sont
dans les messages de commit ; ici, seulement de quoi ne pas défaire le travail.

### La source

- **L'ETP a été recalculée en amont** selon Penman-Monteith FAO-56, sur toute la
  chronique depuis 1958. Toutes les autres colonnes sont identiques au 1e-9
  près : le schéma CSV, lui, n'a pas bougé.
- **Aucun nom de fichier source ne porte de date** depuis juillet 2026, et les
  identifiants de ressource ont tous changé. `analysis:checksum` n'est pas
  exploitable, il manque sur les gros fichiers. La détection de changement
  repose sur `last_modified` et la taille.
- **L'année en cours est révisée en profondeur.** 73 % des mailles de juillet
  2026 ont changé entre le 4 août et le 2 septembre. Aucune partie de la
  chronique n'est figée, même à quelques semaines.
- Le glissant et le fichier annuel sont **d'accord au bit près** sur leur
  recouvrement. La règle qui fait primer l'annuel est un départage prudent, pas
  une correction.
- **Le traitement parcourt toutes les sources, jamais le seul lot téléchargé.**
  Le cache peut être incomplet pour d'autres raisons qu'un téléchargement
  récent, un run interrompu ou un dossier vidé à la main, et restreindre au lot
  produirait une chronique trouée. La règle de saut par fichier rend le parcours
  complet gratuit : 6 ms pour 70 sources sur 26 variables.
- **`00_data-download` est un miroir exact** : ce que l'amont ne publie plus est
  supprimé au début de chaque téléchargement. Sans cela les fichiers orphelins
  s'accumulent à chaque recomposition, comme les 8,4 Go laissés par le découpage
  par décennie. La suppression n'a lieu qu'après le contrôle d'inventaire.
- Tout ce qui décrit la forme du dépôt amont vit dans `sources.py`, et nulle
  part ailleurs. `check_inventory()` bloque si elle change : produire une
  chronique tronquée en silence serait pire qu'un arrêt.

### L'outillage

- **`ncrcat -A` écrit un nom d'attribut à l'envers**, `eulaVlliF_` pour
  `_FillValue`, avec NCO 5.2.1. La concaténation simple ne le fait pas. Ne pas
  utiliser `-A`, et laisser `check.py` refuser les noms inversés.
- **`ncrcat` hérite du découpage interne de son premier fichier d'entrée**, et
  lui imposer un découpage avec `--cnk_dmn` ne rend pas la main. Le découpage se
  décide donc dans `convert.py`, sur les fichiers annuels.
- Le découpage est `128 x 16 x 16`. **C'est la tuile spatiale qui compte, pas la
  profondeur temporelle** : à tuiles de 16, une profondeur de 128 vaut une
  profondeur de 2048 sur les chroniques et rend les cartes onze fois plus
  rapides. La profondeur est une constante et non la longueur de l'année, pour
  que le résultat ne dépende pas de l'ordre des entrées.

### Le géoréférencement

Trois pièges indépendants, chacun suffisant à rendre le fichier inutilisable
dans un SIG. Ils ont tous été constatés avec `gdalinfo` et `terra`.

- **Les axes viennent de la grille de référence, jamais des données.** Une
  colonne du rectangle, à x = 68 000 m, ne porte aucun point ; la déduire des
  données la faisait disparaître et rendait l'axe x irrégulier, ce qui suffit à
  faire abandonner le calage à GDAL. D'où 143 colonnes et non 142. Cela garantit
  aussi que tous les fichiers annuels partagent la même grille, ce dont `ncrcat`
  a besoin.
- **Les coordonnées géographiques s'appellent `latitude` et `longitude`.** GDAL
  traite toute variable nommée `lat` ou `lon` comme un tableau de
  géolocalisation et abandonne alors la géotransformation ; et comme ces
  tableaux portent des NaN hors domaine, `gdalwarp -geoloc` échoue aussi.
- **`crs_wkt` et `spatial_ref` portent du WKT**, tiré de la base EPSG via
  pyproj. Ils valaient la chaîne `EPSG:27572`, que GDAL essaie de lire comme du
  WKT, d'où le `ERROR 1: missing [` et une couche sans système de coordonnées.

### La grille de référence

- La grille fait autorité dans `coordonnees_grille_safran_lambert-2-etendu.csv`,
  versionné sous `resources/safran-grille_<date>.csv`, et **jamais dans les
  shapefiles**. `SIM2.shp` n'a que 8 813 des 9 892 points, Corse absente, et
  `SHP_SIM_FRANCE.shp` en a 8 981 : ce sont des contours de la France, pas la
  grille de calcul. `script_create_grid.R` part donc du CSV.
- Contrôle croisé qui doit rester vrai : les 9 892 points du GeoPackage tombent
  tous dans une maille renseignée du NetCDF, et le NetCDF en compte exactement
  9 892. Les deux emprises coïncident, 56 000 à 1 200 000 en x et 1 613 000 à
  2 685 000 en y.

### Le catalogue

- Les items publiés avant la refonte étaient **tous invalides**, sur
  `'collection' is a required property`. Personne ne l'avait vu parce que STAC
  Browser est tolérant : ne pas se fier à son affichage, valider.
- Le catalogue racine est généré, mais les liens `child` qui ne viennent pas de
  ce dépôt sont conservés, pour qu'un jeu ajouté plus tard ne soit pas effacé.
- L'arborescence de `05_catalog/` reproduit celle du bucket sous `stac-data/`.

## Métadonnées : la ligne suivie

Prendre la standardisation qui ne coûte rien, s'arrêter là où elle toucherait au
contenu. Le projet redistribue la donnée de Météo-France dans un autre format,
il ne la retouche pas, et cela vaut aussi pour sa présentation.

Les noms CF sont **vérifiés contre la table officielle**, jamais écrits de
mémoire : la télécharger et l'interroger prend une minute. `units` porte la
forme udunits, `degC` et non `°C` ; c'est un changement d'écriture, pas d'unité,
et la forme d'origine reste dans le fichier de variables.

**Huit variables n'ont volontairement pas de `standard_name`** : celles en
millimètres, dont l'unité n'est pas convertible vers l'unité canonique CF en
kilogrammes par mètre carré, plus SWI et SSWI_10J qui n'ont pas d'équivalent.
Leur en donner un imposerait de changer l'étiquette d'unité. C'est un choix,
tranché avec Louis, pas un oubli.

Le sens des fenêtres d'agrégation n'est écrit dans aucune documentation
Météo-France ; il a été établi sur les données. Voir le README, qui le publie.

## Vérifications après modification

**Avant tout commit**, dans cet ordre. Les deux premières lignes existent parce
que deux imports manquants sont partis en production l'un après l'autre :
`import main` n'exécute pas `main()`, qui n'est appelée que sous `__main__`, et
lancer le script avec une seule option ne couvre que le chemin de cette option.

```bash
python -m pyflakes main.py safran_fairy/*.py verifier_reprise.py   # noms non définis
python verifier_reprise.py                                          # reprise et chaîne entière
```

`pyflakes` signale `get_ipython`, qui est normal, il n'existe que sous IPython.

```bash
python main.py --all --variables T          # la chaîne entière, sur une variable
stac-valid batch $(find 05_catalog -name '*.json')   # zéro invalide attendu
gdalinfo NETCDF:"04_data-output/T_*.nc":T   # Origin et Pixel Size renseignés
```

Et pour le fond :

`check.py` rend la liste des fichiers rejetés : **rien ne doit être publié si
elle n'est pas vide.** Il doit refuser
`04_data-output-prod/T_QUOT_SIM2_latest-19580801-20260802.nc`, conservé comme
cas de test négatif : sa chronique est dupliquée et son axe non monotone.

Repères mesurés : premier jour 1958-08-01, grille 134 x 143, 9 892 points non
NaN par pas de temps, une variable en float32 plus `crs`, `latitude` et
`longitude`.

## Licence

Le code est en GPL-3.0-or-later ; **les données SIM2 ne le sont pas** (Licence
Ouverte 2.0, Etalab, Météo-France). Ne pas laisser un texte suggérer le
contraire, ni dans le dépôt, ni dans le catalogue, ni dans les attributs NetCDF.
