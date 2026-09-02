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
- [ ] `python main.py --download` sur les 9,44 Go, puis dérouler la chaîne
      complète avec `--variables TINF_H`
- [ ] `check.py` passe sur la sortie
- [ ] comparer à `04_data-output-prod/T_QUOT_SIM2_latest-19580801-20260802.nc`
      sur la période commune, après déduplication de sa partie corrompue. Les
      valeurs doivent être identiques, ETP mise à part. Faire la comparaison
      sur `T` si on veut réutiliser directement ce fichier de référence.
- [ ] noter au passage les temps de chaque étape, sans en faire un préalable :
      sur une seule variable le volume reste modeste, on verra sur le coup

### Phase 3, remettre la production en route

- [ ] rebuild complet des 26 variables sur le serveur
- [ ] `check.py` sur les 26 sorties
- [ ] vider `data/safran-fairy/` et `stac-data/safran-fairy/` sur le S3, puis
      republier
- [ ] relancer le timer, surveiller trois exécutions quotidiennes

### Phase 4, le catalogue STAC

Repris tel quel pour l'instant, refondu ensuite. Les manques relevés :

- pas de `stac_extensions` déclarée, donc les champs ajoutés sont invisibles
  aux clients
- pas d'extension `datacube` : c'est le manque principal pour de la donnée
  grillée, `cube:dimensions` est ce qui permet de savoir ce qu'un fichier
  contient sans le télécharger
- pas d'extension `projection` : EPSG:27572, forme 134 x 142, transformation
- `unite`, `periode_agregation` et `doi` en champs libres, à remplacer par
  l'extension `scientific` et les conventions CF
- pas de `file:size` ni `file:checksum`
- pas de `created` ni `updated`
- `stac_version` 1.0.0, à passer en 1.1.0
- catalogue racine déposé à la main, à générer
- 26 sous-collections d'un item chacune une fois passé à un fichier par
  variable : une collection unique de 26 items serait plus lisible

### Phase 5, hygiène du dépôt

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
