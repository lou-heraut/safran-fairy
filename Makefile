.PHONY: help install install-prod install-service uninstall-service update \
        run-all run-as-service run-setup \
        run-download run-decompress run-split run-convert run-build run-check run-upload run-ui run-clean \
        service-stop service-restart service-restart-timer service-status service-logs service-logs-last-run \
        data-hard-clean data-hard-clean-all data-stats

# Variables
PYTHON := python3
VENV := .python_env
BIN := $(VENV)/bin
PIP := $(BIN)/pip
PYTHON_VENV := $(BIN)/python

# Couleurs
GREEN  := \033[0;32m
YELLOW := \033[0;33m
RED    := \033[0;31m
NC     := \033[0m

help: ## Affiche cette aide
	@echo "$(GREEN)SAFRAN Fairy - Commandes disponibles$(NC)"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(YELLOW)%-25s$(NC) %s\n", $$1, $$2}'


# ─── INSTALLATION ────────────────────────────────────────────────────────────

install: ## Installe le projet (virtualenv + dépendances) - dev
	@echo "$(GREEN)Installation de SAFRAN Fairy...$(NC)"
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	@echo "$(GREEN)✓ Installation terminée$(NC)"
	@echo "Pour activer l'environnement : source $(VENV)/bin/activate"

install-prod: ## Configure l'environnement de production
	@echo "$(GREEN)Configuration de SAFRAN Fairy pour la prod...$(NC)"
	sudo useradd --system --no-create-home --shell /usr/sbin/nologin safran-fairy 2>/dev/null || true
	sudo mkdir -p /var/lib/safran-fairy/{00_data-download,01_data-raw,02_data-split,03_data-convert,04_data-output,05_catalog}
	sudo chown -R safran-fairy:safran-fairy /var/lib/safran-fairy

install-service: install-prod ## Installe et active le service systemd
	@echo "$(GREEN)Installation du service systemd...$(NC)"
	sudo cp safran-sync.service /etc/systemd/system/
	sudo cp safran-sync.timer /etc/systemd/system/
	sudo systemctl daemon-reload
	sudo systemctl enable safran-sync.timer
	sudo systemctl start safran-sync.timer
	@echo "$(GREEN)✓ Service installé et activé$(NC)"

uninstall-service: ## Désinstalle le service systemd
	@echo "$(YELLOW)Désinstallation du service systemd...$(NC)"
	sudo systemctl stop safran-sync.timer || true
	sudo systemctl disable safran-sync.timer || true
	sudo rm -f /etc/systemd/system/safran-sync.service
	sudo rm -f /etc/systemd/system/safran-sync.timer
	sudo systemctl daemon-reload
	sudo userdel safran-fairy 2>/dev/null || true
	@echo "$(GREEN)✓ Service désinstallé$(NC)"

update: ## Met à jour le projet depuis git
	@echo "$(GREEN)Mise à jour du projet...$(NC)"
	sudo git pull
	sudo $(PIP) install --upgrade -r requirements.txt
	@echo "$(GREEN)✓ Mise à jour terminée$(NC)"


# ─── PIPELINE ────────────────────────────────────────────────────────────────

run-all: ## Exécute le pipeline complet (dev)
	@echo "$(GREEN)Exécution du pipeline complet...$(NC)"
	sudo -u safran-fairy $(PYTHON_VENV) main.py --all

run-as-service: ## Exécute comme le ferait le service systemd
	@echo "$(GREEN)Exécution du pipeline complet par le service...$(NC)"
	sudo -u safran-fairy /opt/safran-fairy/.python_env/bin/python /opt/safran-fairy/main.py --all

run-setup: ## Configure le bucket S3 (policy + CORS) - une seule fois
	@echo "$(GREEN)Configuration du bucket S3...$(NC)"
	sudo -u safran-fairy $(PYTHON_VENV) main.py --setup

run-download: ## Télécharge les nouvelles données
	@echo "$(GREEN)Téléchargement des données...$(NC)"
	sudo -u safran-fairy $(PYTHON_VENV) main.py --download

run-decompress: ## Décompresse les fichiers téléchargés
	@echo "$(GREEN)Décompression des données...$(NC)"
	sudo -u safran-fairy $(PYTHON_VENV) main.py --decompress

run-split: ## Découpe les CSV par variable
	@echo "$(GREEN)Découpage des données...$(NC)"
	sudo -u safran-fairy $(PYTHON_VENV) main.py --split

run-convert: ## Convertit en NetCDF
	@echo "$(GREEN)Conversion en NetCDF...$(NC)"
	sudo -u safran-fairy $(PYTHON_VENV) main.py --convert

run-build: ## Assemble une chronique continue par variable
	@echo "$(GREEN)Assemblage des chroniques...$(NC)"
	sudo -u safran-fairy $(PYTHON_VENV) main.py --build

run-check: ## Contrôle les fichiers de sortie sans rien publier
	@echo "$(GREEN)Contrôle des sorties...$(NC)"
	sudo -u safran-fairy $(PYTHON_VENV) main.py --check

run-upload: ## Upload les données sur S3
	@echo "$(GREEN)Upload sur S3...$(NC)"
	sudo -u safran-fairy $(PYTHON_VENV) main.py --upload

run-ui: ## Génère et uploade le catalogue STAC
	@echo "$(GREEN)Mise à jour du catalogue STAC...$(NC)"
	sudo -u safran-fairy $(PYTHON_VENV) main.py --ui

run-clean: ## Nettoie les anciennes versions (local + S3)
	@echo "$(GREEN)Nettoyage des anciennes versions...$(NC)"
	sudo -u safran-fairy $(PYTHON_VENV) main.py --clean


# ─── SERVICE ─────────────────────────────────────────────────────────────────

service-stop: ## Stoppe le run en cours (le timer reste actif)
	@echo "$(YELLOW)Arrêt du service...$(NC)"
	sudo systemctl stop safran-sync.service
	@echo "$(GREEN)✓ Service stoppé$(NC)"

service-restart: ## Relance immédiatement le service sans attendre le timer
	@echo "$(GREEN)Relance immédiate du service...$(NC)"
	sudo systemctl start safran-sync.service
	@echo "$(GREEN)✓ Service relancé$(NC)"

service-restart-timer: ## Relance le timer
	@echo "$(GREEN)Relance du timer...$(NC)"
	sudo systemctl start safran-sync.timer
	@echo "$(GREEN)✓ Timer relancé$(NC)"

service-status: ## Affiche le statut du service systemd
	@echo "$(GREEN)Statut du service :$(NC)"
	@sudo systemctl status safran-sync.timer --no-pager || true
	@echo ""
	@echo "$(GREEN)Prochaines exécutions :$(NC)"
	@systemctl list-timers safran-sync.timer --no-pager || true

service-logs: ## Affiche les logs en temps réel
	@echo "$(GREEN)Logs en temps réel (Ctrl+C pour quitter) :$(NC)"
	sudo journalctl -u safran-sync.service -f

service-logs-last-run: ## Affiche les logs de la dernière exécution
	@echo "$(GREEN)Logs de la dernière exécution :$(NC)"
	@sudo journalctl -u safran-sync.service --since "24 hours ago" --no-pager | tail -50


# ─── DONNÉES ─────────────────────────────────────────────────────────────────

data-hard-clean: ## Nettoie les fichiers temporaires (garde les outputs)
	@echo "$(YELLOW)Nettoyage des fichiers temporaires...$(NC)"
	rm -rf /var/lib/safran-fairy/01_data-raw/*
	rm -rf /var/lib/safran-fairy/02_data-split/*
	rm -rf /var/lib/safran-fairy/03_data-convert/*
	@echo "$(GREEN)✓ Nettoyage terminé$(NC)"

data-hard-clean-all: ## Nettoie TOUS les fichiers générés (⚠️ destructif)
	@echo "$(RED)⚠️  Suppression de TOUTES les données...$(NC)"
	@read -p "Êtes-vous sûr ? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		rm -rf /var/lib/safran-fairy/00_data-download/*; \
		rm -rf /var/lib/safran-fairy/01_data-raw/*; \
		rm -rf /var/lib/safran-fairy/02_data-split/*; \
		rm -rf /var/lib/safran-fairy/03_data-convert/*; \
		rm -rf /var/lib/safran-fairy/04_data-output/*; \
		echo "$(GREEN)✓ Nettoyage complet terminé$(NC)"; \
	fi

data-stats: ## Affiche des statistiques sur les données
	@echo "$(GREEN)Statistiques SAFRAN Fairy :$(NC)"
	@echo ""
	@echo "Espace disque :"
	@du -sh /var/lib/safran-fairy/0*_data-*/ 2>/dev/null || echo "  Aucune donnée"
	@echo ""
	@echo "Nombre de fichiers :"
	@echo "  Downloads  : $$(ls -1 /var/lib/safran-fairy/00_data-download/*.csv.gz 2>/dev/null | wc -l)"
	@echo "  Raw        : $$(ls -1 /var/lib/safran-fairy/01_data-raw/*.csv 2>/dev/null | wc -l)"
	@echo "  Split      : $$(ls -1 /var/lib/safran-fairy/02_data-split/*.parquet 2>/dev/null | wc -l)"
	@echo "  Converted  : $$(ls -1 /var/lib/safran-fairy/03_data-convert/*.nc 2>/dev/null | wc -l)"
	@echo "  Outputs    : $$(ls -1 /var/lib/safran-fairy/04_data-output/*.nc 2>/dev/null | wc -l)"
	@echo ""
	@echo "Dernière mise à jour :"
	@stat -c '%y %n' /var/lib/safran-fairy/04_data-output/*.nc 2>/dev/null | sort | tail -1 | awk '{print "  " $$1, $$2, $$4}' || echo "  Aucune donnée"





# ─── STAC BROWSER ────────────────────────────────────────────────────────────
# STAC_BROWSER_DIR = 05_catalog/stac-browser
# STAC_CATALOG_URL = https://s3-data.meso.umontpellier.fr/safran-fairy-data/stac-data/catalog.json

# browser-install: ## Clone et installe STAC Browser (une seule fois)
# 	git clone https://github.com/radiantearth/stac-browser $(STAC_BROWSER_DIR) || true
# 	cd $(STAC_BROWSER_DIR) && npm install

# browser-build: ## Build STAC Browser
# 	cd $(STAC_BROWSER_DIR) && \
# 	STAC_APP_NAME="SAFRAN-Fairy" \
# 	STAC_CATALOG_URL=$(STAC_CATALOG_URL) \
# 	npm run build
