# =============================================================================
# Image Docker — FEC Normalizer (app web Streamlit)
#
# Build :
#   docker build -t fec-normalizer:latest .
#
# Run en local pour tester :
#   docker run --rm -p 8501:8501 fec-normalizer:latest
#   puis http://localhost:8501
#
# Déploiement Hostinger : voir docker-compose.fec.yml
# =============================================================================

FROM python:3.12-slim

# Métadonnées
LABEL org.opencontainers.image.title="FEC Normalizer"
LABEL org.opencontainers.image.description="Outil de retraitement FEC pour le pôle Audit Extencia"
LABEL org.opencontainers.image.vendor="Extencia — Pôle Innovation Hub"
LABEL org.opencontainers.image.version="1.3"

# Polars peut nécessiter libgomp1 (OpenMP) sur certaines plateformes
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgomp1 \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Environnement Python sain
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Configuration Streamlit pour usage en container derrière reverse proxy.
# XSRF et CORS désactivés pour permettre le bon fonctionnement des
# WebSockets via Traefik (sinon le frontend reste bloqué sur le skeleton
# de chargement). Pas un risque de sécurité dans notre cas : URL non
# publique, infrastructure Extencia interne.
ENV STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_SERVER_ENABLE_XSRF_PROTECTION=false \
    STREAMLIT_SERVER_ENABLE_CORS=false \
    STREAMLIT_SERVER_MAX_UPLOAD_SIZE=2048 \
    STREAMLIT_SERVER_FILE_WATCHER_TYPE=none \
    STREAMLIT_SERVER_ENABLE_WEBSOCKET_COMPRESSION=false

# Dossier de travail
WORKDIR /app

# Installation des dépendances en premier (meilleure mise en cache)
COPY requirements.txt .
RUN pip install -r requirements.txt

# Code de l'application
COPY parser_fec.py enrichissement.py export.py app_streamlit.py ./
COPY logo_extencia_blanc.svg logo_extencia_couleur.svg ./

# Utilisateur non-root pour la sécurité
RUN useradd --system --uid 1001 --create-home appuser \
    && chown -R appuser:appuser /app
USER appuser

# Port exposé en interne (Traefik s'occupe de l'exposition publique)
EXPOSE 8501

# Healthcheck pour que Docker sache si l'app est en ligne
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl --fail --silent http://localhost:8501/_stcore/health || exit 1

# Lancement de l'app
CMD ["streamlit", "run", "app_streamlit.py"]
