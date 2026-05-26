# FEC Normalizer

> Outil de retraitement automatisé des Fichiers d'Écritures Comptables (FEC) pour le pôle Audit du cabinet **Extencia**.

[![Made with Python](https://img.shields.io/badge/python-3.12+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Powered by Polars](https://img.shields.io/badge/data-Polars-CD7F32?logo=polars)](https://www.pola.rs/)
[![Streamlit](https://img.shields.io/badge/web-Streamlit-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io/)
[![License](https://img.shields.io/badge/license-Proprietary-152639)](#licence)

---

## Le projet en une phrase

Automatiser les manipulations préparatoires que les auditeurs effectuent à la main sur chaque FEC avant analyse — racines de compte, découpages temporels, soldes, cumul multi-années ou multi-entités, traçabilité audit — en moins d'une seconde au lieu de ~10 minutes.

## En chiffres

| | |
|---|---|
| Temps manuel par FEC | ~10 minutes |
| Temps avec l'outil | < 1 seconde de calcul (+ écriture Excel) |
| Lignes traitées au plus gros test | 1 400 000 (cumul Carrefour 7 ans) |
| Format de sortie | Excel (par défaut), Parquet, CSV |
| Conformité norme DGFiP | BOI-CF-IOR-60-40-20-10 |
| Tests automatisés | 29 (suite `tests_pipeline.py`) |

## Démo

L'app web est déployée en interne Extencia : **<https://fec.srv1269986.hstgr.cloud>**

Accès limité au cabinet — non destinée à un usage public.

---

## Ce que fait l'outil

À partir d'un FEC brut (norme DGFiP, 18 colonnes), l'outil produit :

1. **Le FEC enrichi** (Excel ou Parquet selon volume) — 9 colonnes ajoutées et placées en tête pour faciliter les TCD : `Entite`, `Exercice`, `Racine`, `ClasseLib`, `Sous_Racine`, `Annee`, `Trimestre`, `Mois`, `Solde`, `Sens`.
2. **Un rapport de diagnostic Excel** — pièce justificative à archiver dans le dossier de mission, contenant le hash SHA-256 du fichier source, l'horodatage du traitement, l'auditeur déclencheur et la liste exhaustive des transformations appliquées (conformité CNCC).
3. **Un rapport de diagnostic JSON** — version archivable et exploitable par script.

## Stack technique

- **Python 3.12+** (compatible 3.10+ via `from __future__ import annotations`)
- **[Polars](https://www.pola.rs/)** pour la manipulation de données (10× plus rapide que pandas sur gros volumes)
- **[openpyxl](https://openpyxl.readthedocs.io/)** pour l'export Excel formaté charte Extencia
- **[Streamlit](https://streamlit.io/)** pour l'interface web
- **Tkinter** (stdlib) pour le mode CLI graphique
- **Docker** pour le déploiement, **Traefik** pour le reverse proxy + HTTPS automatique

---

## Structure du projet

```
fec-normalizer/
├── parser_fec.py              Lecture du FEC, détection auto encodage/séparateur, rapport SHA-256
├── enrichissement.py          Ajout des 9 colonnes calculées + cumul multi-FEC
├── export.py                  Sortie Excel (avec découpage > 1M lignes), Parquet, CSV
├── cli.py                     Point d'entrée ligne de commande + mode Tkinter
├── app_streamlit.py           Interface web (déployée sur Hostinger)
├── generer_fec_test.py        Générateur de FEC synthétiques pour tests
├── tests_pipeline.py          Suite de 29 tests automatisés (à lancer avant chaque release)
├── Dockerfile                 Image Python 3.12-slim + dépendances
├── docker-compose.yml         Service Streamlit derrière Traefik (avec labels pour HTTPS auto)
├── requirements.txt           Dépendances Python verrouillées
├── logo_extencia_blanc.svg    Logo Extencia version fond sombre
├── logo_extencia_couleur.svg  Logo Extencia version fond clair
└── CLAUDE.md                  Doctrine du projet (à lire avant toute contribution)
```

## Trois modes d'usage

### 1. App web (production — pilote Audit Bordeaux)

Accès via navigateur à **<https://fec.srv1269986.hstgr.cloud>**. Glisser-déposer du ou des FEC, choix du mode de cumul si plusieurs fichiers, téléchargement des résultats. Aucune installation requise côté utilisateur.

### 2. CLI ligne de commande

Pour usage local ou intégration scriptée :

```bash
python cli.py --input mon_fec.txt --output-dir resultats/

# Cumul multi-années
python cli.py --input fec_2022.txt fec_2023.txt fec_2024.txt --mode-cumul exercice

# Cumul multi-entités
python cli.py --input soc_a.txt soc_b.txt soc_c.txt \
              --libelles SOC_ALPHA SOC_BETA SOC_GAMMA \
              --mode-cumul entite
```

### 3. CLI graphique (mode Tkinter)

Lancer `python cli.py` sans argument — une boîte de dialogue s'ouvre pour la sélection des fichiers.

---

## Installation locale (pour développement)

### Pré-requis

- Python 3.12 (ou 3.10+ minimum)
- Git
- Optionnel : Docker pour tester le packaging

### Mise en place

```bash
git clone https://github.com/Git-Extencia/fec-normalizer.git
cd fec-normalizer
python3 -m venv .venv
source .venv/bin/activate          # Linux/macOS
# .venv\Scripts\activate            # Windows
pip install -r requirements.txt
```

### Lancer l'app web en local

```bash
streamlit run app_streamlit.py
```

Ouvre automatiquement <http://localhost:8501> dans le navigateur.

### Lancer la suite de tests

```bash
python tests_pipeline.py
```

29 tests couvrant les 3 profils de volumétrie (TPE, PME, hypermarché), les cas pathologiques (FEC sans CompteNum, encodage UTF-8), le cumul multi-années/multi-entités, le découpage Excel automatique au-delà de 1M lignes, et la traçabilité SHA-256.

### Générer des FEC synthétiques pour tester

```bash
python generer_fec_test.py --lignes 5000 --sortie fec_petit.txt --annee 2024
python generer_fec_test.py --lignes 50000 --sortie fec_moyen.txt --annee 2025
python generer_fec_test.py --lignes 200000 --sortie fec_gros.txt
```

Aucune donnée client réelle ne transite jamais par les tests — les FEC synthétiques respectent rigoureusement la norme DGFiP.

---

## Déploiement

L'app est déployée en Docker sur le VPS Hostinger Extencia (`srv1269986.hstgr.cloud`), à côté de N8N. Traefik gère le routage et le HTTPS automatique via Let's Encrypt.

Pour redéployer après modification :

```bash
git push origin main
# Puis dans l'interface Hostinger : "Redéployer" sur le projet fec-normalizer
```

---

## Roadmap

### Phase 1 — Pilote Audit Bordeaux ✓
- App web fonctionnelle déployée
- Suite de tests automatisée
- Documentation utilisateur

### Phase 2 — Infocentre FEC (3-6 mois)
- Centralisation des 8 000+ FEC du cabinet
- Benchmarks sectoriels propriétaires
- Détection d'anomalies inter-dossiers
- Architecture pressentie : PostgreSQL ou DuckDB + Power BI

### Phase 3 — Intelligence augmentée (M+6)
- Matching factures/FEC via vision multimodale
- Reconnaissance signatures et tampons « bon à payer »
- Génération automatique de notes de synthèse pré-RDV

---

## Conformité et confidentialité

- **Aucune donnée client n'est conservée** sur le serveur après traitement (rétention nulle).
- **Hash SHA-256** automatique du FEC source pour preuve d'identité non falsifiable.
- **Traçabilité complète** des transformations appliquées dans le rapport de diagnostic.
- **Conformité norme DGFiP** BOI-CF-IOR-60-40-20-10.
- **Conformité CNCC** : le rapport de diagnostic constitue la pièce justificative attendue par les NEP.

---

## Contribution

Les contributions internes Extencia sont les bienvenues. Avant toute modification importante :

1. Lire le fichier `CLAUDE.md` qui décrit la doctrine du projet (conventions, performance, choix tranchés).
2. S'assurer que la suite `tests_pipeline.py` passe en vert avant de committer.
3. Respecter la charte graphique Extencia sur tout livrable visuel (couleurs, typographie, logos).

## Licence

Code propriétaire — Cabinet Extencia, Pôle Innovation Hub.
Reproduction et distribution réservées au cabinet.

## Contact

**Stéphane Torregrosa** — Pôle Innovation Hub Extencia
[s.torregrosa@extencia.fr](mailto:s.torregrosa@extencia.fr)
