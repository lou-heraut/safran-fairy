# Chantier

Où en est la réparation du pipeline, et ce qu'il reste à faire. Les faits
durables sont dans [CLAUDE.md](CLAUDE.md), les détails chiffrés de chaque
décision dans les messages de commit.

Ouvert le 3 septembre 2026.

## Ce qui s'est passé

Le 31 juillet 2026, Météo-France a recomposé le jeu SIM2 : découpage par année
au lieu de par décennie, disparition des dates dans les noms de fichiers,
disparition du fichier « previous », et recalcul de l'ETP sur toute la
chronique. Le pipeline ne savait pas lire ce format.

Deux conséquences. La production s'est **arrêtée le 4 août**, sur une ligne qui
lisait la date de coupure dans le nom du fichier glissant. Et le dernier lot
publié était **corrompu pour les 26 variables**, chaque fichier contenant la
chronique en double.

La cause profonde n'était pas cette ligne : la fusion reposait sur des `glob`
dont le résultat dépendait de l'ordre des opérations et de l'état du disque. Et
rien ne relisait un fichier avant de le publier. C'est ce que la réécriture
corrige, plus que le symptôme.

## Où on en est

La production est reconstruite et publiée. Les 26 fichiers en ligne couvrent
1958-08-01 à 2026-09-08, le bucket ne contient plus qu'eux, et le catalogue est
valide. Reste à republier ce catalogue avec l'emprise corrigée, et à surveiller
les premières exécutions automatiques.

```
phase 0   S3 assaini            fait, plus aucun fichier hérité
phase 1   pipeline réécrit      fait
phase 2   validé sur T          fait, identique à la prod sur 24 806 jours
phase 3   rebuild et prod       fait, sauf la surveillance
phase 4   fichier NetCDF        fait
phase 5   catalogue STAC        publié, à republier avec l'emprise corrigée
phase 6   flux et empreinte     fait
phase 7   documentation         fait
phase 8   hygiène du dépôt      partiellement fait
```

La cible est **un fichier NetCDF par variable**, couvrant toute la chronique,
nommé avec sa couverture. Le triptyque historical, previous, latest reposait sur
l'idée qu'une partie du passé était figée, ce que le rythme de publication du
producteur contredit.

Les fichiers annuels convertis sont la seule source de vérité, et la sortie une
pure concaténation, sans état ni mutation :

```
sortie(VAR) = concat(année_1958, …, année_N)
              ++ glissant[ jours strictement postérieurs à fin(année_N) ]
```

Aucun `glob` ne décide plus de rien.

## Ce qui reste

### Phase 3, remettre la production en route

- [x] rebuild complet des 26 variables sur le serveur, le 9 septembre.
- [x] vider `data/safran-fairy/` et `stac-data/` des `historical` et `previous`
      hérités. 52 objets et 18,4 Go retirés du premier, les 78 objets de
      l'ancienne arborescence du second partant avec la publication du nouveau
      catalogue.
- [x] publier le catalogue refondu.
- [x] republier le catalogue avec l'emprise corrigée, fait le 9 septembre à
      15:08. Les 26 items portent l'emprise qui couvre les 9 892 points.
- [ ] surveiller trois exécutions automatiques. Le timer est actif, la première
      est celle de la nuit du 9 au 10 septembre.
- [ ] reporter dans INSTALL.md les mesures du 9 septembre, à la place des
      estimations faites sur une variable.
- [ ] **reconstruire et republier `ETP`, qui porte un `time_bnds` de trop.** La
      fiche de variables lui donnait `]06UTC-06UTC]` et `6:30` par analogie avec
      `EVAP` et `PE` ; c'est retiré depuis le 9 septembre, le pourquoi est dans
      CLAUDE.md. Le fichier en ligne, lui, porte encore ces bornes : elles
      s'écrivent dans `create_netcdf()`, donc au niveau des fichiers annuels, et
      changer la fiche ne suffit pas. Il faut repasser la chaîne sur cette seule
      variable, `--variables ETP`, réassembler, contrôler et republier 273 Mo.
      Le catalogue suit.

### Le dépôt Dataverse, DOI 10.57745/BAZ12C

La fiche décrit encore le jeu d'avant la refonte. Elle est publique et porte le
DOI que le catalogue cite, donc elle prime sur le reste pour qui arrive par là.

- [ ] **la grille déposée n'est pas la bonne.** `grid-SIM.gpkg` en ligne a
      8 813 points, le compte de `SIM2.shp`, Corse absente ; son emprise
      s'arrête à 1 028 000 en x et commence à 1 705 000 en y. Celle du dépôt,
      reconstruite depuis le CSV le 3 septembre, en a 9 892, de 60 000 à
      1 196 000 et de 1 617 000 à 2 681 000. À redéposer.
- [ ] **« Détails des fichiers » décrit le triptyque**, trois fichiers par
      variable, `historical`, `previous` et `latest`. Ces fichiers ont été
      retirés du bucket le 9 septembre. À remplacer par le fichier unique nommé
      avec sa couverture.
- [ ] le lien vers le code source pointe sur `github.com/louis-heraut`, qui
      redirige en 301 vers `lou-heraut`. À écrire directement.
- [ ] `data-access.html` annonce l'URL du catalogue comme lisible « par les
      utilisateurs humains et machines », alors que
      `catalog.riverly-data-lake.inrae.fr` sert l'interface de navigation et
      non du JSON. Même correction que celle faite au README.
- [x] le PDF de description des variables référencé par la fiche est bien la
      documentation à jour, malgré le changement des identifiants de ressource
      en juillet.

### Phase 8, hygiène du dépôt

- [ ] renommer le dépôt en `get-data-meteofrance-sim2`, le paquet en `sim2/`, le
      script d'entrée en `sync_sim2.py`. « SAFRAN Fairy » reste le nom d'usage
      du service, y compris dans le préfixe S3 et les identifiants STAC.
- [ ] `pyproject.toml` à la place de `requirements.txt`, avec `SCRIPT_VERSION`
      comme version unique de vérité, propagée à `CITATION.cff`.
- [ ] **trancher la place des scripts de mesure, et celle de l'annexe.**
      `mesures/` a été créé le 9 septembre pour ne pas perdre `alignement.py` et
      `profils.py`, qui fondent les chiffres que l'attribut `comment` du fichier
      Hargreaves et le commit `8a96753` citent. La disposition, elle, reste à
      décider.

      Ce qui est vérifié : les deux voisins mettent leur point d'entrée à la
      racine, `download_onde.py` et `download_vigieau.py`, avec un seul dossier
      de paquet, un `pyproject.toml`, et ni `scripts/` ni `tools/`.
      `etp_hargreaves.py` à la racine est donc conforme à la famille, et
      `verifier_reprise.py` a son analogue exact dans `verifier_vigieau.py`.

      Ce qui n'a pas de convention, c'est une troisième nature de fichier : du
      code lancé une seule fois, que personne ne relance, mais qui fonde une
      affirmation publiée. D'où `mesures/`, qui est une proposition et pas une
      décision. `script_create_grid.R` est laissé à la racine à dessein : c'est
      un utilitaire qui fabrique `resources/grid-SIM.gpkg`, pas une mesure.

      Si la disposition est retenue, restent à faire : fondre `alignement.py` et
      `profils.py`, qui répondent à une seule question, celle de la fenêtre de
      l'ETP ; et, avec le renommage déjà prévu de `main.py` en `sync_sim2.py`,
      renommer `etp_hargreaves.py` en `sync_etp_hargreaves.py`. La racine prend
      alors une forme qui se lit sans ouvrir un fichier, deux `sync_*` et un
      `verifier_*`.
- [x] **affichages refondus.** Ils supposaient que chaque étape ne tournait
      qu'une fois : depuis la boucle, `tprint` était appelé 210 fois et chaque
      `RÉSUMÉ` portait sur un seul fichier. La phase de traitement passe de
      10 010 lignes à 78, soit 128 fois moins, sans rien perdre.

      `safran_fairy/report.py` porte la règle : une bannière par phase réelle,
      **une ligne horodatée par unité** dans une boucle, un bilan calculé sur
      l'ensemble. Les trois modules de la boucle acceptent `verbose=False` et se
      taisent quand `process` rend compte à leur place. Chaque ligne porte
      l'heure, ce qui manquait pour savoir en relisant un journal quelle étape a
      coûté du temps, et les durées sont mesurées et affichées.

      La progression du téléchargement teste `isatty()` : animée sur un
      terminal, une ligne par fichier dans un journal, ce qui supprime les
      retours chariot empilés.

      Retiré au passage : le bloc de 97 lignes commentées de `upload_s3.py`, et
      l'annonce `142x134 points de grille` que la ligne suivante corrigeait.

### Améliorations identifiées, non engagées

- [ ] faire reposer la décision d'envoi sur `file:checksum` plutôt que sur la
      taille, une fois le catalogue publié. La comparaison actuelle laisserait
      passer deux contenus de taille rigoureusement identique, ce qui est
      hautement improbable mais n'est pas une preuve.
- [ ] `cfchecker` sur les fichiers produits, et ce contrôle dans `check.py`.
- [x] vérifier le rendu dans l'instance STAC Browser de
      `catalog.riverly-data-lake.inrae.fr`. C'est ce coup d'œil qui a trouvé
      l'emprise fausse.
- [x] **contrôler le catalogue avant de le publier.** `check.check_catalog()`
      applique les sept points listés plus bas et `main.py --ui` s'arrête si
      un document est rejeté. Éprouvé sur le catalogue publié, accepté, et sur
      sept défauts fabriqués, tous attrapés, dont les deux qui étaient
      réellement passés en ligne.
- [ ] refuser à la publication un fichier dont la variable n'est pas déclarée
      dans le fichier de métadonnées. `parse_filename` reconnaît
      `ETP_Q_H0175_QUOT_SIM2_…` comme une sortie valide : un fichier de la
      production annexe déposé dans `04_data-output` partirait sur le S3 et
      dans le catalogue. Rien ne l'y met aujourd'hui, mais rien ne l'empêche.

## Ce qu'un contrôle du catalogue devrait vérifier

Le pendant de `check.py` pour le catalogue, qui n'existe pas. Les quatre
premiers points viennent chacun d'un défaut constaté, les autres du même
raisonnement appliqué à ce qui n'est pas encore arrivé. Une maquette de ce
contrôle a été passée sur le catalogue en ligne le 9 septembre : 26 items, zéro
anomalie.

1. **Les documents sont valides.** Tous les items publiés avant la refonte
   étaient invalides sur `'collection' is a required property`, des mois durant,
   sans que personne le voie : STAC Browser est tolérant. La validation se fait
   aujourd'hui à la main, elle devrait précéder toute publication.
2. **L'emprise couvre la grille.** Que la bbox de chaque item contienne les
   9 892 points du fichier de référence. C'est ce qui manquait le 9 septembre.
3. **Une variable déclarée par item, et tous les items attendus.** Un envoi
   qui échoue donnerait un catalogue de 23 items sans que rien ne le dise, et
   une variable étrangère au jeu s'y glisserait sans être vue.
4. **Les assets répondent et font la taille annoncée.** Une requête HEAD par
   item, 26 en tout : c'est ce qui distingue un catalogue juste d'un catalogue
   qui décrit des fichiers absents.
5. **Chaque asset porte son empreinte.** Le `file:checksum` n'est calculé que
   si la copie locale correspond à l'octet près ; sans contrôle, son absence
   passe inaperçue.
6. **Les liens `child` étrangers survivent.** Le catalogue racine conserve
   ceux qui ne viennent pas de ce dépôt, et rien ne vérifie qu'ils sont encore
   là après régénération.
7. **La licence déclarée est celle des données.** Licence Ouverte 2.0 d'Etalab,
   jamais celle du code.

## Production annexe, l'ETP FAO Hargreaves

Faite le 9 septembre. Météo-France publie, à côté de SIM2, une ETP calculée par
la formule FAO dont le terme de rayonnement est estimé par Hargreaves à
coefficient 0,175, destinée aux comparaisons avec les projections DRIAS,
Explore2 et TRACC. Même grille SAFRAN, même schéma CSV, 1970 à 2024.

`etp_hargreaves.py` en fait un NetCDF au format du pipeline, dans `annexe-etp/`.
**Rien n'est publié**, ni sur le S3 ni dans le catalogue, et le service ne voit
rien de ce que ce script écrit : son jeu de données, son dossier, sa fiche de
métadonnées, `resources/etp-hargreaves-variables_2026-09-09.csv`. Le
format n'y est pas réécrit, il vient de `convert.create_netcdf()` et le contrôle
de `check.check_file()`, le code même qui garde ce qui part en ligne.

Une seule chose a bougé dans le pipeline : `_check_time()` et `check_file()`
acceptent un `first_day` qui vaut par défaut le 1958-08-01. L'assertion est
déplacée, pas relâchée, et `verifier_reprise.py` passe inchangé.

```
sortie   ETP_Q_H0175_QUOT_SIM2_19700101-20241231.nc, 587,1 Mo
          20 089 pas, 1970-01-01 à 2024-12-31, sans trou ni doublon
          134 x 143, 9 892 points renseignés, contrôle sain
sources  921,0 Mo, 6 décennies, 5,2 Go décompressés
durées   conversion 25 s par décennie, assemblage 7 min 05, 9 min 07 en tout
          pour un passage où une décennie était déjà convertie
mémoire  4,3 Go au pic, sur une décennie de 36,1 M lignes
```

**Le piège : cinq des six sources sont des archives ZIP** portant l'extension
`.csv.gz`, seule 2020-2024 est un vrai gzip. Constaté sur les octets d'en-tête,
`PK\x03\x04` contre `\x1f\x8b`. L'outil `gzip` du système lit un ZIP à membre
unique sans rien dire, le module `gzip` de Python refuse par « Not a gzipped
file » : le piège est donc invisible en ligne de commande. `extract()` lit
l'en-tête plutôt que le nom.

## Questions ouvertes

**Les huit variables sans `standard_name`.** Tranché le 3 septembre : on garde
les millimètres, le projet redistribuant la donnée sans en retoucher la
présentation. À rouvrir seulement si un utilisateur en exprime le besoin.

**Le nom du paquet Python.** `sim2/` serait cohérent avec `onde/` et `vigieau/`
chez les voisins, mais fait disparaître `safran_fairy` du code alors que
`safran-fairy` reste dans les URL publiques. Sans urgence.

## Journal

**2026-09-09, la production est en ligne.** Le rebuild complet est passé, 26
variables assemblées en 2 h 10, contrôlées sans rejet et publiées. Quatre
défauts ont été trouvés en le faisant, tous corrigés le jour même.

Le catalogue plantait après la publication des données, sur une comparaison
entre `None` et une chaîne : le tri supposait qu'un seul nommage était en ligne
alors que le code annonce le contraire deux lignes plus haut. C'était le premier
run à publier le nommage cible à côté des hérités.

L'emprise du catalogue était celle de la France continentale, sans la Corse ni
l'est du domaine, sous un commentaire affirmant qu'elle venait de la grille de
référence. Repérée à l'œil sur la carte de STAC Browser, pas par un contrôle.
Rien ne vérifie l'emprise publiée, c'est une lacune de `check.py`.

Le journal du service n'arrivait qu'à la fin du run : sous systemd la sortie de
Python part par blocs, et pendant deux heures rien ne disait si le run
travaillait ou s'il était mort. Les horodatages posés par `report.py` ne
servaient à rien.

Un assemblage interrompu laissait derrière lui des fichiers que personne ne
ramassait, et dont un seul suffit à bloquer un contrôle du dossier entier.

Ce qui a bien marché : la reprise. Un run coupé par une déconnexion, relancé
tel quel, a repris sans rien refaire d'inutile, 69 sources sur 70 sautées en
onze secondes.

**2026-09-03, deux imports manquants en production.** Une modification par
substitution de texte peut échouer sans rien dire quand son ancre a bougé :
c'est arrivé deux fois de suite, sur `report` puis sur `process`, chacun
découvert en production. La leçon tient en deux points, tous deux consignés dans
CLAUDE.md. Une substitution doit vérifier qu'elle a bien eu lieu. Et la
vérification doit être statique et couvrir tout le fichier, `pyflakes` voyant
d'un coup ce qu'une exécution ne montre que sur le chemin qu'elle emprunte.
`verifier_reprise.py` déroule désormais la chaîne entière par le point d'entrée.


**2026-09-03, mise en production.** Premier essai sur la VM, sur `T` et
`TINF_H`. `check.py` a rejeté les deux sorties : chronique commençant en 2000
et deux trous. Ce n'était pas une régression mais le contrôle faisant son
travail, et la démonstration de ce qui manquait le 4 août.

La cause était une optimisation prématurée dans `main.py` : le traitement ne
portait que sur les fichiers que le téléchargement venait de rapporter. Le
cache ayant été vidé à la main avant la mise à jour, les 58 autres années
n'étaient pas reconverties et l'assemblage a fait ce qu'il pouvait avec 11
années trouées. Corrigé : le parcours porte sur toutes les sources, la règle de
saut le rendant gratuit.


**2026-09-03.** Session entière. Diagnostic, réécriture de la chaîne,
assainissement du S3, validation sur `T` contre le dernier fichier de
production, refonte du fichier NetCDF et du catalogue, optimisations de flux,
documentation. Le détail de chaque décision est dans les commits du jour ; les
constats qui doivent survivre sont dans CLAUDE.md.

Deux découvertes qui ne venaient pas du changement de format et auraient survécu
à la réparation : les fichiers publiés n'étaient géoréférencés pour aucun SIG,
et les items du catalogue étaient invalides depuis l'origine.
