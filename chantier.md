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
- [ ] **republier le catalogue avec l'emprise corrigée.** Celui du 9 septembre à
      14:52 porte encore l'ancienne bbox, celle de la France continentale sans
      la Corse. Un `git pull` puis `make run-ui` suffit, rien n'est à
      reconstruire.
- [ ] surveiller trois exécutions automatiques. Le timer est actif, la première
      est celle de la nuit du 9 au 10 septembre.
- [ ] reporter dans INSTALL.md les mesures du 9 septembre, à la place des
      estimations faites sur une variable.

### Phase 8, hygiène du dépôt

- [ ] renommer le dépôt en `get-data-meteofrance-sim2`, le paquet en `sim2/`, le
      script d'entrée en `sync_sim2.py`. « SAFRAN Fairy » reste le nom d'usage
      du service, y compris dans le préfixe S3 et les identifiants STAC.
- [ ] `pyproject.toml` à la place de `requirements.txt`, avec `SCRIPT_VERSION`
      comme version unique de vérité, propagée à `CITATION.cff`.
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
- [ ] vérifier le rendu dans l'instance STAC Browser de
      `catalog.riverly-data-lake.inrae.fr`.

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
