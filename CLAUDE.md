# Notes pour Claude Code

Le [README](README.md) documente le projet, mais **il décrit encore l'ancienne
stratégie à trois fichiers et l'ancien format source** : il est à refondre, et
tant que ce n'est pas fait il ne fait pas foi sur la partie « Stratégie de mise
à jour » et « Structure des données ». L'état du chantier en cours vit dans
[chantier.md](chantier.md). Ce fichier ne contient que ce qui n'est ni dans
l'un ni dans l'autre.

## Contexte

Dépôt d'une famille : convention de nommage `get-data-<plateforme>-<jeu de
données>`. Voisins dans le dossier parent : `get-data-hubeau-onde` (le modèle
de référence, le plus abouti) et `get-data-vigieau-secheresse`. Renommage de ce
dépôt prévu en `get-data-meteofrance-sim2`, voir chantier.md phase 5.

Différence assumée avec les deux voisins : eux sont des téléchargeurs qu'on
lance à la demande et qui produisent un jeu de tables local. Celui-ci est un
**service qui tourne en continu** (timer systemd quotidien) et qui **republie**
sur un stockage objet public avec un catalogue STAC. Il a donc de l'état
persistant à deux endroits, sur le disque du serveur et sur le S3, et une
notion d'idempotence que les autres n'ont pas. Les conventions d'écriture et de
structure sont communes ; l'architecture d'exécution ne l'est pas.

État : **cassé en production depuis le 4 août 2026**, chantier de réparation en
cours. Ce n'est pas un dépôt stabilisé, contrairement aux deux voisins.

## Ce que fait le projet

Météo-France publie la réanalyse SIM2 (SAFRAN-ISBA-MODCOU, France
métropolitaine, grille de 8 km, depuis le 1er août 1958) sous forme de gros CSV
compressés où toutes les variables sont mélangées dans les mêmes fichiers,
découpés par tranches temporelles. Ce format est difficilement exploitable.

Le pipeline le retourne : il produit **un NetCDF par variable climatique**,
couvrant toute la chronique, et le publie sur un bucket S3 public avec un
catalogue STAC. C'est le seul objet de ce dépôt. La donnée n'est ni corrigée ni
recalculée, seulement transposée.

## Interaction

Ne pas utiliser le widget de questions à choix multiples (outil
`AskUserQuestion`, les options cliquables). Les arbitrages se posent en texte
dans la réponse : les options, celle qui est recommandée, ce qui les distingue,
puis la réponse arrive en prose. Le reproche ne porte pas sur la mise en forme
mais sur le format d'échange : réponses figées alors qu'aucune n'est forcément
la bonne, et impossibilité de tout avoir sous les yeux. Les tableaux, schémas
et maquettes ASCII sont au contraire bienvenus, directement dans le texte.

## Conventions

- **Code et commentaires en anglais, messages affichés en français.** Les noms
  de variables climatiques restent ceux de Météo-France (`TINF_H`, `PRELIQ`,
  `SSWI_10J`) : les renommer casserait la traçabilité avec la documentation
  SIM2 et avec les fichiers déjà publiés.
- README, chantier.md, commits, AUTHORS.md en français, en prose (pas de
  listes à puces télégraphiques).

### Rédaction

- **Aucun tiret cadratin ni demi-cadratin** dans les textes. Deux-points,
  virgule, parenthèses ou point font le travail.
- Typographie française : guillemets `«  »`, espace avant `: ; ! ?`, nombres
  groupés par milliers avec une espace (`9 892`), virgule décimale (`9,44 Go`).
- Pas de superlatifs ni de formules d'annonce. Les affirmations chiffrées sont
  des mesures, pas des estimations : ne pas en ajouter sans avoir vérifié, et
  marquer explicitement « à mesurer » ce qui ne l'a pas été.
- En-tête SPDX en tête de chaque fichier Python :
  `# SPDX-FileCopyrightText: 2026 Louis Héraut <louis.heraut@inrae.fr>` puis
  `# SPDX-License-Identifier: GPL-3.0-or-later`.
  Ce n'est pas encore fait sur les fichiers existants, voir chantier.md phase 5.

## Environnement

Debian/Ubuntu bloque `pip install` en système (PEP 668). Le venv du projet est
`.python_env/`, à activer avant toute commande :

```bash
source .python_env/bin/activate
```

Dépendance système hors Python : **NCO** (`sudo apt install nco`). Le pipeline
appelle `ncrcat` en sous-processus pour concaténer les NetCDF ; ni xarray ni
netCDF4 ne le remplacent à ce volume.

La configuration est scindée en deux : `config.json` (chemins, URL, bucket,
versionné sous forme de `config.json.dist`) et `.env` (secrets et `MODE`,
jamais versionné, gabarit dans `env.dist`). `MODE=prod` est ce qui autorise
`main.py` à exécuter `main()` ; en `MODE=dev` le script se charge sans rien
lancer, pour être piloté depuis un REPL.

Tous les dossiers de données sont ignorés par git et se régénèrent.

## Le service en production

```
/opt/safran-fairy/            le dépôt cloné
/var/lib/safran-fairy/        les données (00_ à 05_) et download_state.json
utilisateur safran-fairy      compte système, sans shell
safran-sync.timer             OnCalendar=*-*-* 02:00:00, Persistent=true
safran-sync.service           ExecStart .python_env/bin/python main.py --all
```

Le bucket est `riverly-data-lake` sur `https://s3-data.meso.umontpellier.fr`,
avec deux préfixes : `data/safran-fairy/` pour les NetCDF et
`stac-data/safran-fairy/` pour le catalogue. Le catalogue racine
`stac-data/catalog.json` n'est **pas** généré par le pipeline, il a été déposé à
la main et le code se contente d'y faire référence.

Le bucket est en lecture publique par policy, mais le `ListObjects` anonyme est
refusé : pour savoir ce qui est publié sans les clés, passer par le catalogue
STAC, pas par une requête de listage.

## La source Météo-France, telle qu'elle est depuis le 31 juillet 2026

Jeu `6569b27598256cc583c917a7` sur data.gouv.fr, 83 ressources, dont :

- **69 fichiers annuels** `QUOT_SIM2_<année>.csv.gz`, de 1958 à 2026, servis
  depuis `https://meteofrance.s3.sbg.io.cloud.ovh.net/data/REF_CC/SIM/`.
  9,44 Go au total en compressé (somme des `check:headers:content-length`),
  environ 4,5 fois plus décompressés.
- **un fichier glissant** `QUOT_SIM2_latest.csv.gz`, les 60 derniers jours,
  actualisé quotidiennement. Mesuré le 2 septembre 2026 : du 2026-07-04 au
  2026-09-01.
- les documents et les shapefiles de la grille.

Rythme annoncé par le producteur : actualisation bimensuelle des quatre
dernières années, quotidienne pour les 60 jours glissants. Observé le
2 septembre 2026 : les fichiers 2023, 2024, 2025 et 2026 portent tous un
`last_modified` du jour, les autres celui du 31 juillet 2026.

**Les fichiers annuels récents sont donc réécrits, y compris pour des années
révolues.** Toute logique qui suppose qu'une année passée est figée est fausse.

Format du CSV : séparateur `;`, 29 colonnes, `LAMBX;LAMBY;DATE` puis les
26 variables, `DATE` en `AAAAMMJJ`, `LAMBX` et `LAMBY` en hectomètres en
Lambert II étendu (EPSG:27572). 9 892 points de grille, qui se rangent dans une
grille 134 x 142 avec des NaN hors du domaine.

## Pièges à ne pas « corriger »

Ces constats sont mesurés sur les fichiers réels, pas déduits de la
documentation.

- **L'ETP a été révisée sur toute la chronique.** Comparaison ancien contre
  nouveau fichier 1958, sur 399 lignes communes : 350 lignes diffèrent sur
  `ETP`, écart maximum 1,1 mm, et **toutes les autres colonnes sont identiques
  au 1e-9 près**. La documentation confirme le passage à « formule de
  Penman-Monteith FAO-56 ». L'ETP actuellement publiée sur le S3 est donc
  périmée, et `resources/safran-variables_2026-02-19.csv` porte encore
  l'ancienne définition.
- **Le schéma CSV, lui, n'a pas bougé** : mêmes colonnes, même ordre, même
  grille. `split.py` et `convert.py` n'ont pas à changer sur le fond.
- Le nom de fichier ne porte plus aucune date. Toute la logique qui lisait la
  couverture temporelle dans le nom du fichier source est morte.
- Les identifiants de ressource data.gouv ont tous changé, sauf ceux des
  documents. `download_state.json` d'avant le 31 juillet 2026 est caduc.
- `analysis:checksum` n'est pas exploitable comme détecteur de changement : il
  est absent des ressources volumineuses, que data.gouv marque
  `analysis:error: File too large to download`. Rester sur `last_modified`,
  éventuellement complété par `check:headers:content-length`.
- Le fichier glissant et le fichier de l'année en cours se recouvrent. Sur ce
  recouvrement ils sont **d'accord au bit près** : mesuré le 3 septembre 2026
  sur `T`, 60 jours communs, aucune maille différente. La règle « l'annuel
  l'emporte » est donc un départage prudent et non une correction ; elle sert
  surtout à ce que le glissant ne fasse que prolonger au-delà du dernier jour
  des fichiers annuels.
- **L'année en cours est révisée en amont, et pas qu'à la marge.** Les valeurs
  de `T` de juillet 2026 ont changé entre le 4 août et le 2 septembre 2026 :
  73 % des mailles concernées, écart moyen 0,11 °C, maximum 3,5 °C, sans
  décalage temporel (testé à plus ou moins deux jours). C'est le
  rafraîchissement bimensuel à l'œuvre. Aucune partie de la chronique ne peut
  être considérée comme figée, y compris à quelques semaines.
- `ncrcat -h -A sortie.nc entree.nc sortie.nc` ne duplique pas le contenu de
  `sortie.nc`, vérifié sur un cas réduit. Ce n'est pas la cause de la
  corruption du 4 août, voir chantier.md.
- **`ncrcat -A` écrit un nom d'attribut à l'envers.** Avec NCO 5.2.1, le mode
  append fait apparaître sur la variable un attribut nommé `eulaVlliF_`, soit
  `_FillValue` retourné caractère par caractère. La concaténation simple
  `ncrcat -O` ne le fait pas. Reproduit en quatre commandes sur un extrait de
  quinze jours. C'est pour cette raison que tous les fichiers `latest` publiés
  le portent et qu'aucun `previous` ni `historical` ne le porte. Ne pas
  utiliser `-A` dans la chaîne de construction, et laisser `check.py` refuser
  les fichiers qui présentent un nom d'attribut inversé.
- La grille de sortie est 134 x 142 pour 9 892 points réels. Les cases vides
  ne sont pas une erreur de conversion, le domaine SAFRAN n'est pas rectangulaire.

## Vérifications après modification

`safran_fairy/check.py` contrôle la structure des NetCDF produits et rend la
liste des fichiers rejetés. **Rien ne doit être publié si elle n'est pas
vide.** C'est ce qui a manqué le 4 août.

```python
from safran_fairy import check
failed = check(OUTPUT_DIR="04_data-output")
```

Cas de référence pour valider le contrôle lui-même : il doit rejeter
`04_data-output-prod/T_QUOT_SIM2_latest-19580801-20260802.nc` (chronique
dupliquée, axe non monotone) et accepter les `previous` et `historical` publiés
sur le S3, qui sont sains.

Repères mesurés, à retrouver après le rebuild : premier jour 1958-08-01,
9 892 points non NaN par pas de temps, grille 134 x 142, une variable plus la
variable `crs`, encodage `float32` compressé zlib niveau 4.

Fichier de référence conservé hors git : `04_data-output-prod/`, le dernier
produit par la production. Il est **corrompu** (voir chantier.md) : il sert à
comparer les valeurs sur la période commune, pas à valider une structure.

## Licence

Le code est en GPL-3.0-or-later ; **les données SIM2 ne le sont pas** (Licence
Ouverte / Open Licence 2.0, Etalab, Météo-France). Ne pas laisser un texte
suggérer le contraire, ni sur le dépôt, ni dans le catalogue STAC, ni dans les
attributs NetCDF.
