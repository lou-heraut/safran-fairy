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

La chaîne est réécrite, validée sur une variable de bout en bout, et rien n'est
encore reconstruit en production.

```
phase 0   S3 assaini            fait, 132 objets retirés sur 264
phase 1   pipeline réécrit      fait
phase 2   validé sur T          fait, identique à la prod sur 24 806 jours
phase 3   rebuild et prod       à faire
phase 4   fichier NetCDF        fait
phase 5   catalogue STAC        fait, non publié
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

- [ ] rebuild complet des 26 variables sur le serveur. Tout est à refaire depuis
      la validation sur `T` : le découpage interne, la grille à 143 colonnes,
      les coordonnées, les bornes de temps, les métadonnées CF et le
      géoréférencement ont tous changé depuis.
- [ ] vider `data/safran-fairy/` et `stac-data/` avant de republier, pour retirer
      les `historical` et `previous` hérités.
- [ ] publier le catalogue refondu. Il n'a pas été publié jusqu'ici parce que la
      structure aplatie déplace les URL des items : autant que ce changement
      arrive une seule fois.
- [ ] relancer le timer, surveiller trois exécutions.
- [ ] mesurer le rebuild complet et reporter les chiffres dans INSTALL.md. Sur
      une variable, 10 min 50 dont 4 min 43 de découpage. Le facteur ne sera pas
      26, le CSV n'étant lu qu'une fois.

### Phase 8, hygiène du dépôt

- [ ] renommer le dépôt en `get-data-meteofrance-sim2`, le paquet en `sim2/`, le
      script d'entrée en `sync_sim2.py`. « SAFRAN Fairy » reste le nom d'usage
      du service, y compris dans le préfixe S3 et les identifiants STAC.
- [ ] `pyproject.toml` à la place de `requirements.txt`, avec `SCRIPT_VERSION`
      comme version unique de vérité, propagée à `CITATION.cff`.
- [ ] **refondre les affichages.** Ils ont été écrits quand chaque étape ne
      tournait qu'une fois : la bannière ASCII marquait alors une vraie
      transition et le bloc `RÉSUMÉ` résumait vraiment quelque chose. Depuis
      que le traitement boucle fichier par fichier, `tprint` est appelé 210
      fois et chaque `RÉSUMÉ` porte sur un seul fichier. Un run complet produit
      environ 10 000 lignes, dont 13 % de bannières, et l'information utile ne
      se distingue plus du décor.

      Quatre défauts, par ordre de gêne :

      - les bannières annoncent une transition qui n'en est plus une, et
        suggèrent une progression linéaire alors qu'on boucle ;
      - les blocs `RÉSUMÉ` résument un fichier et répètent un chemin qui ne
        change pas ;
      - la progression du téléchargement écrit avec `end="\r"` sans tester
        `isatty()`, d'où les ` 0.0 Mo` orphelins dans un journal ou un fichier ;
      - **rien n'est horodaté**, donc on ne peut pas savoir en relisant quelle
        étape a coûté du temps. C'est le manque le plus cher à l'usage pour un
        service qui tourne la nuit.

      Direction : rendre la structure du texte fidèle à celle de l'exécution.
      Une bannière par run, une phase par phase réelle, **une ligne par fichier**
      dans la boucle, et un bilan calculé sur l'ensemble à la fin de la phase.

          14:02:31  [12/70] QUOT_SIM2_2000   512 Mo -> 26 var -> 26 nc   12,4 s
          14:02:56  [14/70] QUOT_SIM2_2002   déjà converti, ignoré

      `logging` donne l'horodatage et permet de reléguer le détail en `DEBUG`,
      récupérable avec un `--verbose`. `isatty()` réserve la progression animée
      au terminal.

      Touche six modules mais aucune logique de traitement. **À faire après la
      republication**, pas pendant.
- [ ] la conversion annonce `142x134 points de grille` puis
      `grille complétée : 1 colonne` : les deux sont vrais, mais dans cet ordre
      le premier chiffre est corrigé par la ligne suivante.

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
