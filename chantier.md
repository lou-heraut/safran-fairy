# Chantier en cours

Ce fichier porte l'état du travail de réparation et de remise à plat du
pipeline. Il est le point d'entrée quand on reprend le projet après une pause.
Ce qui est stable et qui n'a pas vocation à bouger va dans
[CLAUDE.md](CLAUDE.md) ; ce qui décrit la donnée pour un utilisateur va dans le
[README](README.md).

Ouvert le 3 septembre 2026.

## 1. Ce qui s'est passé

Le 31 juillet 2026, Météo-France a recomposé le jeu SIM2 sur data.gouv.fr :
découpage par année au lieu de par décennie, disparition des dates dans les
noms de fichiers, disparition du fichier « previous », et révision de l'ETP sur
toute la chronique. Le détail est dans CLAUDE.md, section « La source
Météo-France ».

Le pipeline ne sait pas lire ce format. Deux conséquences, toutes deux
constatées sur le S3 public.

**La production s'est arrêtée le 4 août 2026.** Aucun objet publié depuis. La
cause tient dans `merge.py`, à la ligne qui extrait la date de coupure du nom
du fichier glissant :

```python
cutoff_raw = var_new[0].stem.split('latest-')[1].split('-')[0]
```

Sur `T_QUOT_SIM2_latest.nc`, nouveau nom sans tiret, `split('latest-')` rend une
liste d'un seul élément et l'accès à l'indice 1 lève `IndexError`. À confirmer
dans le journal du service (`make service-logs-last-run`), mais la lecture du
code ne laisse pas d'autre issue.

**Le dernier fichier publié est corrompu, pour les 26 variables.** Mesuré sur
`T_QUOT_SIM2_latest-19580801-20260802.nc` (939 622 763 octets, soit exactement
le double de la taille attendue) :

```
49 645 pas de temps pour 24 839 dates uniques
axe time non monotone, une seule rupture, à l'indice 24 805
  [0     .. 24805]  1958-08-01 -> 2026-06-30   24 806 pas
  [24806 .. 49644]  1958-08-01 -> 2026-08-02   24 839 pas
```

Toute la chronique est présente deux fois. Explication compatible avec ces
chiffres, sans certitude faute de journal : dans `main.py`, `clean_local` sur
`OUTPUT_DIR` n'est appelé qu'**après** l'ensemble de `merge()`. Or
`merge_previous()` écrit son nouveau fichier dans `OUTPUT_DIR` avant que
`merge_latest()` n'y fasse son `glob("*previous*.nc")`. Le glob a donc ramené
deux générations de « previous », que `merge_by_type` a toutes les deux placées
dans `base_files = files[:-1]` et toutes les deux tronquées à la même date de
coupure. L'arithmétique tombe juste : 24 806 + 24 806 + 33 jours de glissant
= 49 645.

Ce que ce bug dit vraiment : **la logique de fusion reposait sur des `glob` dont
le résultat dépendait de l'ordre des opérations et de l'état du disque.** C'est
ce point-là qu'il faut supprimer, pas seulement le symptôme.

Ce que ce bug dit aussi : rien ne relisait le fichier produit avant de le
publier. Un contrôle de trois lignes sur la monotonie de l'axe temporel aurait
arrêté la publication.

## 2. La cible

Un seul fichier NetCDF par variable, couvrant toute la chronique, nommé avec sa
couverture temporelle :

```
T_QUOT_SIM2_19580801-20260901.nc
TINF_H_QUOT_SIM2_19580801-20260901.nc
...                                     26 fichiers, environ 490 Mo pièce
```

Le triptyque historical / previous / latest disparaît. Il reposait sur l'idée
qu'une partie de la chronique était figée, ce que le nouveau rythme de
publication du producteur contredit : les quatre dernières années sont
réécrites deux fois par mois.

Les dates restent dans le nom : l'utilisateur qui télécharge un fichier sait
sans l'ouvrir ce qu'il tient, et le DOI cite le dépôt de données et son
catalogue, pas un fichier individuel, donc rien ne dépend d'une URL stable.
`clean_s3` supprime l'ancienne version après le dépôt de la nouvelle, jamais
avant.

### L'architecture de construction

Le point clé : les fichiers annuels convertis sont la **seule** source de
vérité, et la sortie est une pure concaténation, sans état ni mutation.

```
00_data-download/   QUOT_SIM2_1958.csv.gz … QUOT_SIM2_2026.csv.gz
                    QUOT_SIM2_latest.csv.gz
        |
        v  décompression, éphémère
01_data-raw/        QUOT_SIM2_<année>.csv
        |
        v  découpage par variable, éphémère
02_data-split/      <VAR>_QUOT_SIM2_<année>.parquet
        |
        v  conversion
03_data-convert/    <VAR>_QUOT_SIM2_<année>.nc      cache durable, 26 x 69
                    <VAR>_QUOT_SIM2_latest.nc       60 jours glissants
        |
        v  assemblage
04_data-output/     <VAR>_QUOT_SIM2_<début>-<fin>.nc
```

Règle d'assemblage, la même tous les jours :

```
sortie(VAR) = concat(année_1958, …, année_N)
              ++  latest[ jours strictement postérieurs à fin(année_N) ]
```

Le fichier annuel gagne toujours sur le glissant en cas de recouvrement, parce
qu'il est consolidé. Quand le producteur rafraîchit une année, les jours
provisoires apportés par le glissant sont remplacés d'eux-mêmes par les valeurs
consolidées, sans traitement particulier. Au passage du 1er janvier, le
glissant fournit naturellement le début de l'année nouvelle tant que son
fichier annuel n'existe pas.

Aucun `glob` ne décide de quoi que ce soit : la liste des fichiers annuels est
construite à partir de l'inventaire des ressources, pas de l'état du disque.

### Ce que ça coûte

Le fichier glissant change tous les jours, donc les 26 sorties sont
reconstruites et redéposées tous les jours, soit environ 12,7 Go d'envoi
quotidien. Ce n'est pas une régression : l'ancienne stratégie redéposait déjà
26 fichiers « latest » complets chaque jour.

Optimisation possible si le temps de reconstruction se révèle gênant : mettre
en cache la concaténation des seules années, qui ne change que deux fois par
mois, et n'ajouter que la queue glissante chaque jour. À décider après mesure,
pas avant : ça réintroduit un artefact dérivé, donc une occasion de
désynchronisation.

## 3. Le plan

### Phase 0, arrêter l'hémorragie

Côté production, hors du dépôt.

- [x] Arrêter le timer : fait par Louis avant l'ouverture du chantier.
- [x] Supprimer du S3 les 26 `*_latest-*.nc` corrompus et les 26 items STAC
      qui les décrivent. Fait le 3 septembre 2026 : 132 objets supprimés sur
      264, dont 80 orphelins à clé préfixée d'un slash, résidus du catalogue de
      mars. Les `previous` et `historical` restent en ligne jusqu'à la
      republication : ils sont sains, seule leur ETP est périmée.
- [x] Régénérer le catalogue STAC pour qu'il ne pointe plus dans le vide.
      Vérifié : les items `latest` rendent 404, les collections ne listent plus
      que `historical` et `previous`, l'étendue temporelle est à jour.

### Phase 1, réécrire le pipeline

Modules, en partant de l'existant :

| Fichier | Action |
|---|---|
| `sources.py` | ✅ **nouveau**. Toute la connaissance du dépôt data.gouv, plus un `check_inventory()` qui refuse de continuer si l'amont ne ressemble plus à ce qui est attendu. |
| `download.py` | ✅ état par `(last_modified, taille)`, écriture en `.part` renommé une fois complet, rend des `Resource` typées. |
| `decompress.py` | ✅ inchangé, import mort retiré. |
| `split.py` | ✅ filtre `variables`, et `usecols` qui évite de parser les 25 colonnes inutiles. |
| `convert.py` | ✅ adapté à la sortie à plat de `split`, métadonnée ETP corrigée. |
| `merge.py` -> `build.py` | ✅ **réécrit**. Une seule règle d'assemblage, un seul `ncrcat` simple, jamais `-A`. |
| `check.py` | ✅ **nouveau**. Validé sur les fichiers corrompus et sains de la prod. |
| `clean.py` | ✅ réécrit, groupé par variable, suppression après dépôt réussi. `clean_dataverse` supprimé. |
| `tools.py` | ✅ `parse_filename` accepte les deux nommages pendant la transition, `build_filename` ajouté. |
| `generate_ui.py` -> `catalog.py` | ⏳ renommage et refonte reportés en phase 4. Correction ponctuelle faite pour qu'un fichier sans jeton de version produise un item valide. |
| `upload_s3.py` -> `s3.py` | ⏳ renommage reporté en phase 5. |
| `main.py` | ✅ orchestration linéaire, `--variables`, et `check` bloquant avant tout envoi. |

Supprimés : `merge.py`, `upload.py`, `update_dataverse.py`, `gif.py`,
`data-access.html` et `data-access_old.html`. `__pycache__/` et
`04_data-output-prod/` ajoutés au `.gitignore`.

Reste en dette sur `generate_ui.py` : il contient encore une grande fonction
commentée, `generate_index` qui ne sert plus, et des tirets cadratins dans les
chaînes affichées. Tout part à la refonte de la phase 4.

Contenu de `check.py`, les contrôles qui auraient arrêté le 4 août :

- [x] axe temporel strictement croissant, sans doublon
- [x] pas de trou : tous les écarts valent exactement un jour
- [x] premier jour égal à 1958-08-01
- [x] dernier jour cohérent avec ce que le nom du fichier annonce
- [x] grille 134 x 142. La grille n'est **pas** régulière, `x` a des pas de
      8 000 et de 16 000 m : seule la croissance stricte est exigée.
- [x] la variable attendue est présente, en `float32`, avec `long_name`,
      `units` et `grid_mapping`, et la variable `crs` est là
- [x] nombre de points non NaN égal à 9 892 au dernier pas de temps, et jamais
      supérieur ailleurs. Pas d'égalité exigée aux premiers pas : `SSWI_10J`
      est vide au début de la chronique, par construction.
- [x] aucun nom d'attribut inversé, voir le piège `ncrcat -A` dans CLAUDE.md
- [x] échec bloquant : `check()` rend la liste des fichiers rejetés, l'appelant
      ne publie rien si elle n'est pas vide

### Phase 2, valider sur une variable

Le téléchargement des 9,44 Go est incompressible, mais la suite peut ne porter
que sur une variable, ce qui divise le reste par 26.

- [x] chaîne validée sur une année réelle au nouveau format : `QUOT_SIM2_1958`
      téléchargé, décompressé, découpé sur `TINF_H` seul, converti, assemblé et
      contrôlé en 4 s. La sortie est **strictement identique** à celle de
      l'ancien pipeline sur 1958 : mêmes dates, mêmes coordonnées, mêmes
      valeurs, mêmes attributs.
- [x] `main.py --download` : 83 ressources, 9,44 Go de données, aucun échec.
- [x] chaîne complète sur `T`, de 1958 à 2026 : sortie
      `T_QUOT_SIM2_19580801-20260901.nc`, 470 Mo, acceptée par `check.py`.
      Le glissant a été converti puis n'a rien apporté, le fichier annuel 2026
      atteignant déjà le 1er septembre : comportement conforme à la règle.
- [ ] `check.py` passe sur la sortie
- [x] comparaison à `04_data-output-prod/T_QUOT_SIM2_latest-19580801-20260802.nc`,
      partie dupliquée écartée :

      1958-08-01 -> 2026-06-30   24 806 jours   0 maille différente
      2026-07-01 -> 2026-07-31        31 jours   73 % des mailles, max 3,5 °C
      2026-08-01                                 0 maille différente
      2026-08-02                                 300 mailles, max 0,2 °C

      Soit 68 années reproduites à l'identique, et un écart circonscrit à
      juillet 2026 qui n'est pas un défaut de la chaîne mais une révision
      amont : pas de décalage temporel, et les 9 892 points du 15 juillet 2026
      confrontés un par un au CSV brut donnent un écart maximum de 1e-6, soit
      l'arrondi float32.
- [x] temps mesurés sur une variable, machine locale, 3 septembre 2026 :

      décompression   2 min 58   70 fichiers, 35,15 Go écrits
      découpage       4 min 43   70 fichiers,  0,35 Go
      conversion      2 min 27   70 fichiers,  0,47 Go
      assemblage      0 min 42    1 fichier,   0,47 Go
      total          10 min 50

      Le découpage domine. Pour les 26 variables il ne sera pas 26 fois plus
      long, la lecture du CSV étant faite une seule fois, mais c'est là qu'il
      faudra regarder si le rebuild complet traîne.

### Phase 3, remettre la production en route

- [ ] rebuild complet des 26 variables sur le serveur
- [ ] `check.py` sur les 26 sorties
- [ ] vider `data/safran-fairy/` et `stac-data/safran-fairy/` sur le S3, puis
      republier
- [ ] relancer le timer, surveiller trois exécutions quotidiennes

### Phase 4, le fichier lui-même

C'est la phase au plus fort effet pour les utilisateurs, et elle a été chiffrée.

**Le découpage interne du NetCDF est le pire possible pour l'usage dominant.**
Un NetCDF range son tableau en pavés compressés indépendamment : lire une valeur
impose de décompresser tout le pavé qui la contient. Les pavés valent ici
`[1, 134, 142]`, soit une carte complète par jour, si bien qu'extraire la
chronique d'un point oblige à décompresser les 24 869 pavés, c'est-à-dire tout
le fichier, pour 99 Ko utiles.

Quatre découpages alternatifs produits avec `ncks --cnk_dmn` et mesurés sur des
emprises réalistes, un bassin de 5 x 5 points faisant 40 km de côté et un de
20 x 20 en faisant 160 :

    découpage         taille   1 point  bassin 5x5  bassin 20x20   France   1 carte
    ------------------------------------------------------------------------------
    1 x 134 x 142     470 Mo    8,79 s      8,70 s        8,74 s   10,55 s    0,01 s
    365 x 32 x 32     425 Mo    0,68 s      0,60 s        2,35 s   11,85 s    0,15 s
    2048 x 16 x 16    406 Mo    0,24 s      0,17 s        0,66 s   10,92 s    0,67 s
    4096 x 12 x 12    403 Mo    0,17 s      0,20 s        0,58 s   10,99 s    1,24 s
    24869 x 8 x 8     394 Mo    0,12 s      0,10 s        0,56 s   10,92 s    7,17 s

Le cache disque était chaud pour tous, ce qui minore l'avantage des bons
découpages plutôt qu'il ne l'exagère. Les fichiers rechunkés sont en prime plus
petits, jusqu'à 16 %, les valeurs voisines dans le temps se comprimant mieux
que les valeurs voisines dans l'espace : ce n'est pas un arbitrage vitesse
contre taille, on gagne des deux côtés.

- [x] **`128 x 16 x 16` adopté**, posé dans `convert.py` et hérité tel quel par
      le fichier assemblé, `ncrcat` reprenant le découpage de sa première
      entrée. C'est la **tuile spatiale qui compte, pas la profondeur
      temporelle** : à tuiles de 16 x 16, une profondeur de 128 donne les mêmes
      temps sur les chroniques et les bassins qu'une profondeur de 2048, et
      rend les cartes onze fois plus rapides.

          découpage         taille   1 point  bassin 5x5  bassin 20x20   1 carte
          ---------------------------------------------------------------------
          1 x 134 x 142     470 Mo    8,85 s      8,70 s        8,75 s    0,01 s
          128 x 16 x 16     422 Mo    0,24 s      0,17 s        0,68 s    0,06 s
          2048 x 16 x 16    406 Mo    0,24 s      0,17 s        0,66 s    0,66 s

      La profondeur est une constante et non la longueur de l'année, pour que
      le découpage du fichier final ne dépende pas de l'ordre des entrées.
      Forcer le découpage sur `ncrcat` avec `--cnk_dmn` a été essayé : il n'a
      pas rendu la main en deux minutes sur trois fichiers, piste abandonnée.
- [ ] ne pas chercher à optimiser la moyenne sur la France entière : elle lit
      forcément tout le fichier, environ 11 s quel que soit le découpage.

**Le fichier n'était pas géoréférencé pour un SIG**, et deux causes
indépendantes s'y ajoutaient. Mesuré avec `gdalinfo`, qui lisait les coins en
coordonnées pixel, de (0,0) à (142,134), au lieu de coordonnées projetées.

D'abord une colonne manquante. La grille SAFRAN comporte une colonne, à
x = 68 000 m, qui ne porte aucun point ; la construire depuis les données la
faisait disparaître, rendant l'axe x irrégulier avec un pas de 16 km à cet
endroit. Les axes sont désormais tirés de la grille de référence, ce qui donne
143 colonnes au lieu de 142, pour 0,7 % de mailles vides en plus, et garantit
au passage que tous les fichiers annuels partagent la même grille.

Ensuite, et c'est une régression que l'ajout des coordonnées géographiques avait
introduite le jour même, le pilote netCDF de GDAL traite toute variable nommée
`lat` ou `lon` comme un tableau de géolocalisation et abandonne alors la
géotransformation. Comme ces tableaux portent des NaN hors domaine,
`gdalwarp -geoloc` échouait aussi : on perdait le calage sans rien gagner.
Renommées `latitude` et `longitude`, elles restent lisibles et GDAL cale
correctement. Les deux formes ont été essayées avant de conclure.

    gdalinfo sur le fichier produit
      Size is 143, 134
      Origin = (56000, 2685000)
      Pixel Size = (8000, -8000)

**Les conventions CF ne sont pas déclarées.** Le fichier ne porte ni
`Conventions`, ni `standard_name`, ni `title`, ni `history`, ni `references`.
C'est le point d'interopérabilité le plus simple à corriger et le plus rentable :
sans `Conventions = "CF-1.10"` et sans `standard_name`, aucun outil générique ne
sait que `T` est une température de l'air.

- [x] `Conventions`, `title`, `history` et `references` posés en attributs
      globaux, `institution` et `source` y étaient déjà.
- [x] `standard_name` et `cell_methods` par variable, dans trois colonnes
      ajoutées à `resources/safran-variables_2026-09-03.csv`. Les noms ont été
      **vérifiés contre la table CF officielle**, version 94 du 9 juin 2026,
      téléchargée et interrogée, pas écrits de mémoire. 18 variables sur 26 en
      reçoivent un.
- [x] `units` porte désormais la forme udunits, que CF exige : `degC` et non
      `°C`, qui n'est pas analysable. Le libellé français reste dans
      `long_name` et la forme d'origine dans la colonne `unite` du CSV.
- [x] provenance rétablie sur le fichier assemblé : `ncrcat` héritant des
      attributs de sa première entrée, le fichier publié annonçait venir du
      seul Parquet de 1958. `build.py` réécrit `history` et `source_files`.
- [ ] contrôler le résultat avec `cfchecker` et ajouter ce contrôle à `check.py`

#### Questions laissées ouvertes sur les métadonnées

La ligne suivie est de prendre la standardisation qui ne coûte rien et de
s'arrêter là où elle toucherait au contenu. Ces trois points la franchissent
ou s'en approchent, ils attendent donc une décision.

**Les 8 variables sans `standard_name`.** ETP, EVAP, PE, DRAINC, RUNC et
ECOULEMENT sont en millimètres ; l'unité canonique CF des grandeurs
correspondantes est le kilogramme par mètre carré. Physiquement c'est la même
chose pour de l'eau, 1 mm de lame valant 1 kg m-2, mais pour un vérificateur
`mm` est une longueur et `kg m-2` une masse par surface : il refuse
l'association. Leur donner un nom CF imposerait donc d'écrire
`units = "kg m-2"` là où l'utilisateur attend des millimètres. Aucune valeur ne
changerait, seulement l'étiquette. **Décision du 3 septembre 2026 : on garde
les millimètres**, la réserve de Louis étant qu'on redistribue la donnée de
Météo-France sans en retoucher la présentation. SWI et SSWI_10J n'ont de toute
façon aucun équivalent dans le vocabulaire. À rouvrir seulement si un
utilisateur en exprime le besoin.

**Les coordonnées géographiques.** Le fichier est en Lambert II étendu, donc
situer un point demande de savoir reprojeter. CF prévoit d'ajouter deux
tableaux auxiliaires de latitude et de longitude, en plus et sans rien enlever,
déclarés par un attribut `coordinates`. Météo-France les fournit déjà dans
`coordonnees_grille_safran_lambert-2-etendu.csv`, il n'y a donc aucun calcul à
faire ni aucune approximation à introduire. Coût : environ 300 Ko sur un
fichier de 422 Mo. Bénéfice : extraire un point depuis des coordonnées GPS
devient direct. **Proposé, non fait.**

**Les bornes de temps.** Une valeur quotidienne SAFRAN couvre une fenêtre
précise, `]06UTC-06UTC]` ou `]18UTC-18UTC]` selon la variable. Cette
information vit aujourd'hui dans un attribut en texte libre,
`aggregation_period`, que seul un humain lit. CF a `time_bnds` pour ça, qui
donne le début et la fin de chaque intervalle et rend la fenêtre exploitable
par une machine. L'information vient de la documentation Météo-France, elle
n'est pas inventée. **Proposé, non fait.**

### Phase 5, le catalogue STAC

Refondu. Le point de départ n'était pas seulement pauvre, il était **invalide** :
`stac-valid` refusait tous les items sur `'collection' is a required property`,
un item portant un lien vers sa collection devant aussi porter son identifiant
en champ racine. Les 52 items en ligne l'étaient depuis l'origine. Personne ne
l'avait vu parce que STAC Browser est tolérant.

- [x] structure aplatie : une collection, un item par fichier. Les 26 sous
      collections d'un item chacune ne servaient plus rien une fois passé à un
      fichier par variable.
- [x] `stac_version` 1.1.0 et `stac_extensions` déclarées, sans quoi rien de ce
      qu'on ajoute n'est interprétable par un client.
- [x] `datacube` : `cube:dimensions` et `cube:variables` donnent la forme et
      l'étendue du cube, le pas de temps et les unités, sans télécharger 420 Mo.
- [x] `projection` : `proj:code`, `proj:shape`, `proj:bbox`.
- [x] `file` : `file:size`, et `file:checksum` en multihash SHA-256 calculé sur
      la copie locale quand elle correspond au bucket à l'octet près. Vérifié
      contre un `sha256sum` indépendant.
- [x] `scientific` : `sci:doi` et `sci:citation` remplacent le champ libre.
- [x] `processing` : logiciel, date et filiation, la traçabilité qui manquait.
- [x] `created` et `updated`, `providers`, `summaries`, `item_assets`.
- [x] licence : `"other"` plus un lien, `etalab-2.0` n'étant pas un identifiant
      SPDX et STAC n'acceptant que ceux-là ou `"other"`.
- [x] validation dans le pipeline : `stac-valid batch` passe sur 53 fichiers
      sur 53, extensions comprises. `stac_valid` est en dépendance facultative.
- [x] le catalogue racine n'est **pas** regénéré, il est partagé avec les autres
      jeux du data lake et l'écrire d'ici effacerait leurs liens. Le code
      vérifie qu'il référence bien la collection et prévient sinon.
- [x] les objets de catalogue devenus obsolètes sont retirés du bucket à la
      publication, sans quoi l'ancienne arborescence par variable laisserait 78
      objets orphelins.

- [ ] **non publié**. La nouvelle structure déplace les items de
      `<VAR>/items/X.json` vers `items/X.json` : autant que ce changement d'URL
      arrive une seule fois, à la republication de la phase 3, plutôt que deux.
- [ ] une fois `file:checksum` en ligne, faire reposer la décision d'envoi sur
      l'empreinte plutôt que sur la taille, ce qui lève la limite notée en
      phase 6.
- [ ] vérifier le rendu dans l'instance STAC Browser de
      `catalog.riverly-data-lake.inrae.fr`.

### Phase 6, efficacité et empreinte

Empreinte mesurée sur une variable, extrapolée à 26 pour ce qui varie :

    dossier            une variable    26 variables   rôle
    ---------------------------------------------------------------------
    00_data-download        9,44 Go         9,44 Go   permet de rejouer
                                                      sans réseau
    01_data-raw            35,15 Go        35,15 Go   inutile après le
                                                      découpage
    02_data-split           0,35 Go        ~9 Go      inutile après la
                                                      conversion
    03_data-convert         0,47 Go       ~12 Go      cache annuel, utile
    04_data-output          0,47 Go       ~12,7 Go    publié

Soit un pic de plus de 78 Go pendant un rebuild complet, dont 44 Go d'artefacts
morts dès l'étape suivante.

- [x] **traitement fichier par fichier**, dans `process_sources()` de
      `main.py` : décompresser, découper, convertir, puis supprimer le CSV et
      les Parquet. Vérifié sur trois années réelles, `01_data-raw` et
      `02_data-split` finissent vides et seul le cache annuel subsiste. Deux
      garanties tenues par construction : la suppression n'a lieu qu'**après**
      une conversion réussie, donc un échec laisse le CSV en place pour qu'on
      puisse regarder, ce qui a été vérifié en provoquant l'échec ; et une
      reprise saute les sources dont tous les NetCDF annuels existent déjà et
      sont plus récents que le `.csv.gz`. Les étapes lancées séparément gardent
      leur comportement d'origine, pour déboguer.
- [x] **ne pas reconstruire une sortie déjà à jour**, dans `_up_to_date()` de
      `build.py`. La règle naïve, comparer le nom cible, aurait été **fausse** :
      le nom ne porte que les dates extrêmes, or Météo-France révise l'année en
      cours sans en déplacer la date de fin, ce qui a changé 73 % des mailles de
      juillet 2026. La condition qui tranche est donc la fraîcheur : on saute
      seulement si aucune entrée n'est plus récente que la sortie. Un fichier
      annuel rafraîchi est réécrit, donc plus récent, donc on reconstruit.
      Vérifié dans les trois cas, premier passage, relance à vide, et relance
      après modification d'une entrée.
- [x] la décision d'**envoyer** se prend en comparant au bucket, dans
      `to_upload()`, et non au fait qu'on vienne de reconstruire : l'assemblage
      sautant désormais ce qui est à jour, un envoi ayant échoué la veille ne
      serait autrement jamais rattrapé. Vérifié sur trois cas contre le bucket
      réel, fichier absent, fichier présent de taille différente, fichier
      présent et identique. La purge des versions périmées tourne même quand
      rien n'a été envoyé.
- [ ] la comparaison porte sur la présence et la taille. L'ETag ne peut pas
      servir, boto3 envoyant ces fichiers en plusieurs parties, auquel cas il
      n'est plus la somme MD5 du contenu. Deux contenus de taille rigoureusement
      identique passeraient donc au travers : hautement improbable sur des
      NetCDF compressés de centaines de mégaoctets, mais ce n'est pas une
      preuve. **La comparaison deviendra exacte quand le catalogue portera
      `file:checksum`**, qui est déjà au programme de la phase 5.
- [ ] mesurer le rebuild complet des 26 variables. Le découpage domine, 4 min 43
      sur une variable, mais le CSV n'est lu qu'une fois : le facteur ne sera
      pas 26. Chiffre à établir, pas à supposer.
- [ ] envisager de ne garder dans `01_data-raw` aucun fichier entre deux runs,
      ce que la boucle par fichier fait naturellement.

### Phase 7, code, sorties et documentation

- [ ] **README à refondre.** Il décrit encore la stratégie à trois fichiers, le
      découpage par décennie, `make run-merge`, `merge.py`, `upload.py`, un
      `resources/safran_variables.csv` qui n'a jamais porté ce nom, et une URL
      de catalogue sur l'ancien bucket `safran-fairy-data`. Sur le modèle des
      dépôts voisins : ce que sont les données, les pièges d'analyse, les choix
      techniques, comment relire en Python et en R.
- [ ] **INSTALL.md** mentionne `INDEX_PATH`, clé supprimée.
- [ ] **Sorties du pipeline.** Elles sont lisibles mais bavardes et sans
      horodatage, ce qui rend le journal systemd difficile à exploiter après
      coup : impossible de savoir combien de temps a pris une étape sans
      recouper les dates de fichiers, ce que j'ai dû faire pour mesurer.
      Passer à `logging` avec un horodatage, garder les messages en français,
      et réserver les bannières `art` au mode interactif.
- [ ] **Un résumé final chiffré** en fin de run : combien de fichiers, quel
      volume, quelles variables, combien de temps, ce qui a été publié. C'est
      ce qui manque pour surveiller le service sans lire tout le journal.
- [ ] `pyproject.toml`, `CITATION.cff`, `AUTHORS.md`, version unique de vérité,
      renommage du dépôt : voir la phase suivante.

### Phase 8, hygiène du dépôt

- [ ] renommer le dépôt en `get-data-meteofrance-sim2`, le paquet Python en
      `sim2/`, le script d'entrée en `sync_sim2.py`. « SAFRAN Fairy » reste le
      nom d'usage du service : bannière, préfixe S3 `safran-fairy`,
      identifiants STAC, qui ne changent pas.
- [ ] `pyproject.toml` à la place de `requirements.txt`, avec `SCRIPT_VERSION`
      comme version unique de vérité dans `sim2/schema.py`
- [ ] `CITATION.cff` et `AUTHORS.md`, sur le modèle des voisins, avec la
      citation des données SIM2 distincte de celle du code
- [ ] en-têtes SPDX sur tous les fichiers Python
- [ ] README refondu : la stratégie à trois fichiers n'existe plus, la section
      « Structure des données » et l'architecture sont à réécrire
- [ ] purger les fichiers de sauvegarde `*~` du dossier de travail (ils sont
      déjà ignorés par git, mais ils encombrent)

### Décidé après mesure

- `decompress()` traite tous les fichiers d'un coup, ce qui fait cohabiter
  environ 42 Go de CSV dans `01_data-raw/`. Le transformer en boucle par
  fichier, décompresser puis découper puis supprimer, tient en une dizaine de
  lignes dans `main.py`. À faire seulement si l'empreinte réelle gêne : la
  chaîne linéaire est plus facile à reprendre là où elle s'est arrêtée.

## 4. Points ouverts

- Le renommage du paquet Python en `sim2/` est cohérent avec `onde/` et
  `vigieau/` chez les voisins, mais fait disparaître `safran_fairy` du code
  alors que `safran-fairy` reste dans les URL publiques. À trancher, sans
  urgence, en phase 5.
- ~~Faut-il conserver `03_data-convert/` en production ?~~ Tranché : oui. Le
  serveur a la place, et sans ce cache le rafraîchissement bimensuel d'une
  seule année imposerait de retélécharger et de reconvertir les 69 années.
- La grille de référence `resources/grid-SIM.gpkg` a été produite depuis
  `SIM2.shp`, que le producteur a republié le 4 août 2026 sous un nouveau nom.
  À vérifier avant de s'en servir dans `check.py`.

## 5. Journal

**2026-09-03, état des lieux.** Audit demandé sur le catalogue, l'efficacité,
le code et la documentation, consigné en phases 4 à 8 ci-dessus. Deux mesures
en ressortent, toutes deux inattendues et toutes deux chiffrées. Le découpage
interne des NetCDF publiés est le pire possible pour l'usage dominant :
extraire la chronique d'un point coûte 8,81 s et la décompression du fichier
entier, contre 0,68 s avec un découpage `365 x 32 x 32` qui donne en prime un
fichier 45 Mo plus léger. Et les fichiers ne déclarent pas les conventions CF,
ce qui est le point d'interopérabilité le moins cher à corriger.

Soldé au passage une dette que ma réécriture avait créée : quatre cibles du
Makefile appelaient des options disparues, dont `run-all`. Le drapeau `--clean`
est rétabli dans `main.py` comme opération de maintenance, hors de `--all`.

**2026-09-03, fin de session.** Phase 0 terminée : purge du S3 passée, 132
objets supprimés sur 264, catalogue STAC régénéré et vérifié, plus aucune
référence pendante. Phase 1 écrite dans sa quasi-totalité : `sources.py`,
`download.py`, `build.py`, `check.py`, `clean.py`, `tools.py`, `split.py` et
`main.py`. Modules morts supprimés. Métadonnée ETP passée en FAO-56, le fichier
de variables est devenu `safran-variables_2026-09-03.csv` et `config.json` suit.

Validation de bout en bout sur une année réelle au nouveau format : `TINF_H`
pour 1958, téléchargé, décompressé, découpé, converti, assemblé et contrôlé en
4 s, pour une sortie **strictement identique** à celle de l'ancien pipeline.
La règle d'assemblage est testée séparément sur un cas fabriqué où le fichier
annuel est volontairement en retard : le glissant n'apporte que les jours qui
manquent, sans écraser l'annuel, et la relance est idempotente.

Reste à faire avant la phase 3 : le téléchargement des 9,44 Go et le déroulé
complet sur une variable.

**2026-09-03, suite.** Racine du dépôt nettoyée, 23 sauvegardes Emacs
supprimées, `.gitignore` complété. Inventaire du S3 : 264 objets, 37,70 Go,
dont 80 orphelins à clé préfixée d'un slash, résidus du catalogue de mars,
injoignables autrement que par une URL à double slash et référencés nulle part.
Corruption confirmée sur les 26 variables : ratio de taille de 1,999 entre
`latest` et `previous` partout, et vérification directe en ouvrant `T` et
`PRENEI`, même signature exactement (49 645 pas pour 24 839 dates, une rupture
au 2026-06-30). Les `previous` et `historical` sont sains, contrôlés de la même
façon. Script de purge ciblée écrit et passé en simulation : 132 objets à
supprimer sur 264. **L'exécution a été refusée par le garde-fou du mode auto,
elle reste à lancer à la main.**

Écrit et validé : `check.py`, qui rejette les deux fichiers de prod corrompus
avec le bon diagnostic et accepte les deux fichiers sains ; `sources.py`, qui
lit correctement l'inventaire amont en direct (69 années de 1958 à 2026, un
glissant, aucune anomalie) ; `tools.py` réécrit, dont `parse_filename` accepte
maintenant les deux nommages le temps de la transition. Trouvé au passage le
bug `ncrcat -A` qui écrit `_FillValue` à l'envers, consigné dans CLAUDE.md.

**2026-09-03.** Exploration du dépôt et de la source. Diagnostic posé : format
source recomposé, production arrêtée depuis le 4 août, fichiers publiés
corrompus, ETP révisée en amont. Cible arrêtée à un fichier par variable avec
dates dans le nom. Rédaction de CLAUDE.md et de ce fichier. Timer de production
arrêté par Louis, cache annuel confirmé, place disque du serveur non
contraignante. Rien n'est encore modifié dans le code.
