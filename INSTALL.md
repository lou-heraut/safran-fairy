# Installation et exploitation

Ce fichier s'adresse à qui fait tourner le service. Pour se servir des données
publiées, voir le [README](README.md).

## Prérequis

```bash
sudo apt install python3 python3-venv nco git
```

**NCO n'est pas optionnel.** Le pipeline appelle `ncrcat` pour assembler les
chroniques ; ni xarray ni netCDF4 ne le remplacent à ce volume. Sans lui, tout
fonctionne jusqu'à l'assemblage, qui échoue.

## Ce que ça consomme

Sur le disque, une fois le régime établi :

```
00_data-download    9,4 Go    les CSV sources, pour rejouer sans réseau
03_data-convert      12 Go    un NetCDF par variable et par année
04_data-output        9 Go    les 26 fichiers publiés
                    ------
                     31 Go    plus moins de 1 Go de transitoire
```

Prévoir 50 Go pour être tranquille. Les dossiers `01_data-raw` et
`02_data-split` restent vides entre deux fichiers : la chaîne décompresse,
découpe, convertit, puis efface, ce qui évite de faire cohabiter 44 Go
d'intermédiaires morts.

Le réseau : 9,4 Go au premier run, puis une vingtaine de mégaoctets par jour, et
137 Mo par année révisée deux fois par mois.

Le dossier des sources est tenu comme un miroir exact du dépôt distant : les
fichiers que Météo-France ne publie plus sont supprimés au début de chaque
téléchargement, ce qui évite qu'ils s'accumulent à la prochaine recomposition.

## Installation

```bash
sudo git clone https://github.com/lou-heraut/safran-fairy.git /opt/safran-fairy
cd /opt/safran-fairy
sudo make install
```

### Configuration

Deux fichiers, l'un pour les secrets, l'autre pour le reste.

```bash
sudo cp env.dist .env          # MODE, CONFIG_FILE, clés S3
sudo cp config.json.dist config-prod.json
```

`.env` désigne le fichier de configuration à utiliser, ce qui permet de garder
des chemins de développement et des chemins de production côte à côte :

```bash
MODE=prod
CONFIG_FILE=config-prod.json
S3_ACCESS_KEY=...
S3_SECRET_KEY=...
```

Dans `config-prod.json`, faire pointer les dossiers vers `/var/lib` :

```json
"STATE_FILE":   "/var/lib/safran-fairy/download_state.json",
"DOWNLOAD_DIR": "/var/lib/safran-fairy/00_data-download",
"RAW_DIR":      "/var/lib/safran-fairy/01_data-raw",
"SPLIT_DIR":    "/var/lib/safran-fairy/02_data-split",
"CONVERT_DIR":  "/var/lib/safran-fairy/03_data-convert",
"OUTPUT_DIR":   "/var/lib/safran-fairy/04_data-output",
"CATALOG_DIR":  "/var/lib/safran-fairy/05_catalog"
```

### Bucket et service

```bash
make run-setup          # policy de lecture publique et CORS, une seule fois
sudo make install-service
```

`install-service` crée l'utilisateur système, les dossiers avec les bons droits,
installe le timer et le démarre. L'exécution est quotidienne à 02:00 UTC.

## Lancer

```bash
make run-all            # la chaîne complète, publication comprise
make run-process        # télécharge et traite, sans rien publier
make run-as-service     # comme le ferait systemd
```

`run-process` est celle à utiliser quand on veut regarder le résultat avant de
le mettre en ligne, typiquement après une mise à jour qui change le contenu des
fichiers produits.

Chaque étape s'exécute aussi seule, pour reprendre ou déboguer :

```bash
make run-download run-decompress run-split run-convert run-build
make run-check          # contrôle sans rien publier
make run-upload run-ui
make run-clean          # purge les versions périmées, local et S3
```

`VARIABLES` restreint le traitement et divise le coût d'un essai par 26 :

```bash
make run-process VARIABLES="T TINF_H"
```

## Reprendre un run interrompu

Relancer la même commande suffit. La chaîne saute ce qui est déjà fait :

- un fichier source déjà téléchargé et inchangé n'est pas retéléchargé ;
- une année déjà convertie, et plus récente que son CSV, n'est pas reconvertie ;
- une sortie déjà assemblée, et plus récente que toutes ses entrées, n'est pas
  réassemblée ;
- un fichier déjà en ligne à l'identique n'est pas renvoyé.

Si une conversion a échoué, le CSV et les Parquet du fichier fautif sont laissés
en place dans `01_data-raw` et `02_data-split`, exprès, pour qu'on puisse
regarder ce qui s'est passé.

## Surveiller

```bash
make service-status             # statut du timer et prochaines exécutions
make service-logs               # journal en temps réel
make service-logs-last-run      # dernière exécution
make data-stats                 # volumes et date de la dernière sortie
```

Le service écrit dans le journal systemd, pas dans un fichier : `journalctl -u
safran-sync.service` est le point d'entrée, et il n'y a pas de logrotate à
configurer.

Un run qui se termine bien affiche le nombre de fichiers assemblés, contrôlés et
envoyés. **Rien n'est publié si le contrôle rejette un fichier** : le processus
s'arrête avec un code non nul, ce que systemd remonte.

## Dépannage

**L'assemblage échoue avec « échec de ncrcat ».** NCO n'est pas installé, ou les
fichiers annuels n'ont pas tous la même grille. Le second cas ne devrait plus se
produire, la grille venant de la référence et non des données.

**Le téléchargement s'arrête sur « l'inventaire amont ne correspond plus au
format attendu ».** Météo-France a changé la forme de son dépôt. C'est
volontairement bloquant : produire une chronique tronquée en silence serait pire.
Tout ce qui décrit le dépôt amont est dans `safran_fairy/sources.py`.

**Le contrôle rejette un fichier.** Le message dit quoi : doublons dans l'axe
temporel, trou dans la chronique, grille inattendue, métadonnée manquante. Le
fichier reste sur le disque, rien n'est publié.

**Reconstruire entièrement.** Supprimer `03_data-convert` force la reconversion
depuis les CSV déjà téléchargés, sans repasser par le réseau. Supprimer aussi
`00_data-download` repart de zéro, 9,4 Go de téléchargement.

## Mettre à jour

```bash
cd /opt/safran-fairy
sudo git pull
sudo .python_env/bin/python -m pip install --upgrade -r requirements.txt
```

`config-prod.json` n'est pas versionné, donc `git pull` ne le met pas à jour :
une clé ajoutée au code n'y arrive pas toute seule. Le pipeline refuse de
démarrer et dit laquelle manque, mais autant vérifier avant :

```bash
diff <(python3 -c "import json;print('\n'.join(sorted(json.load(open('config.json.dist')))))") \
     <(python3 -c "import json;print('\n'.join(sorted(json.load(open('config-prod.json')))))")
```

Vérifier aussi que `METADATA_VARIABLES_FILE` et `METADATA_GRID_FILE` désignent
des fichiers qui existent dans `resources/` : ils sont datés et changent de nom
quand leur contenu change.

Une modification qui change le contenu des fichiers produits, comme le découpage
interne ou les métadonnées, demande de reconstruire : supprimer
`03_data-convert` puis relancer.
