```markdown
# Installation


## Installation sur serveur Linux
### 1. Prérequis système
```bash
# Mise à jour
sudo apt update && sudo apt upgrade -y
# Dépendances système
sudo apt install -y \
    python3.10 \
    python3-pip \
    python3-venv \
    nco \
    git
```

### 2. Installation du projet
```bash
# Cloner le projet
sudo git clone https://github.com/lou-heraut/safran-fairy.git /opt/safran-fairy
cd /opt/safran-fairy
# Installer le virtualenv et les dépendances Python
sudo make install
```

### 3. Configuration
#### 3.1. env
```bash
# Copier et éditer le fichier d'environnement
sudo cp env.dist .env
sudo nano .env
```
Remplir avec vos paramètres pour la prod :
```bash
MODE=prod
CONFIG_FILE=config-prod.json
RDG_API_TOKEN=token_dataverse
S3_ACCESS_KEY=clé_accès_S3
S3_SECRET_KEY=clé_secrète_S3
```

#### 3.2. config.json
```bash
# Copier et éditer le fichier de configuration
sudo cp config.json.dist config-prod.json
sudo nano config-prod.json
```
Remplir avec vos paramètres pour la prod, en particulier :
```json
"STATE_FILE": "/var/lib/safran-fairy/download_state.json",
"INDEX_PATH": "/var/lib/safran-fairy/data-access.html",
"DOWNLOAD_DIR": "/var/lib/safran-fairy/00_data-download",
"RAW_DIR": "/var/lib/safran-fairy/01_data-raw",
"SPLIT_DIR": "/var/lib/safran-fairy/02_data-split",
"CONVERT_DIR": "/var/lib/safran-fairy/03_data-convert",
"OUTPUT_DIR": "/var/lib/safran-fairy/04_data-output",
"CATALOG_DIR": "/var/lib/safran-fairy/05_catalog"
```

### 4. Installation prod et service systemd
```bash
# Crée l'user système, les dossiers /var/lib avec les bons droits,
# installe et démarre le timer — tout en une commande
sudo make install-service
```

### 5. Test manuel
```bash
# Tester le pipeline comme le ferait le service
make run-as-service

# Vérifier les données générées
ls -lh /var/lib/safran-fairy/04_data-output/
```

### 6. Vérification
```bash
# Voir les prochaines exécutions planifiées
make service-status

# Tester une exécution manuelle via systemd
sudo systemctl start safran-sync.service

# Suivre les logs en temps réel
make service-logs
```


## Configuration avancée
### Changer l'heure d'exécution
Éditer le timer :
```bash
sudo systemctl edit safran-sync.timer
```
Ajouter :
```ini
[Timer]
OnCalendar=
OnCalendar=*-*-* 03:00:00
```
Recharger :
```bash
sudo systemctl daemon-reload
sudo systemctl restart safran-sync.timer
```

### Notifications par email
Installer postfix :
```bash
sudo apt install postfix mailutils
```
Modifier le service pour envoyer un email en cas d'erreur :
```bash
sudo systemctl edit safran-sync.service
```
Ajouter :
```ini
[Service]
OnFailure=status-email@%n.service
```

### Rotation des logs
Créer `/etc/logrotate.d/safran-fairy` :
```
/var/log/safran-fairy/*.log {
    daily
    rotate 30
    compress
    delaycompress
    notifempty
    create 0644 safran-fairy safran-fairy
    sharedscripts
}
```


## Monitoring
### Vérifier la santé du service
```bash
# Statut général
make service-status

# Logs de la dernière exécution
make service-logs-last-run

# Logs des 24 dernières heures
sudo journalctl -u safran-sync.service --since "24 hours ago"

# Erreurs uniquement
sudo journalctl -u safran-sync.service -p err
```

### Métriques utiles
```bash
# Taille des données
make data-stats

# Taille brute des dossiers
du -sh /var/lib/safran-fairy/*/

# Nombre de fichiers traités
ls /var/lib/safran-fairy/04_data-output/*.nc | wc -l

# Dernière mise à jour
stat -c '%y' /var/lib/safran-fairy/04_data-output/*.nc | sort | tail -1
```


## Mise à jour
```bash
# Mettre à jour le code depuis git
cd /opt/safran-fairy
make update

# Le service utilisera automatiquement le nouveau code
# à sa prochaine exécution planifiée
# OU tester immédiatement :
sudo systemctl start safran-sync.service
make service-logs
```

**Note :** La mise à jour ne modifie pas vos fichiers de configuration (`.env`, `config.json`) ni vos données.


## Désinstallation
```bash
# Arrêter et désactiver le service
make uninstall-service
# Supprimer le projet (attention : supprime toutes les données !)
sudo rm -rf /opt/safran-fairy
```


## Migration vers un nouveau serveur
```bash
# Sur l'ancien serveur : sauvegarder la config et l'état
tar czf safran-backup.tar.gz .env resources/download_state.json
# Sur le nouveau serveur : suivre l'installation normale puis restaurer
tar xzf safran-backup.tar.gz
```
```