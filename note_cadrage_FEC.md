# Note de cadrage — Industrialisation du traitement FEC

**Pôle Innovation Hub Extencia**
Auteur : Stéphane Torregrosa
Date : 28 avril 2026
Version : 1.0 — POC validé
Sponsor pressenti : Pôle Audit Bordeaux

---

## TL;DR

Les auditeurs Extencia répètent manuellement les mêmes manipulations sur chaque FEC avant analyse. Le POC technique mené sur un FEC réel de 113 000 lignes (16 Mo) prouve qu'on peut **automatiser intégralement** ce retraitement en moins de 0,5 seconde, là où la manipulation manuelle prend ~10 minutes. Un Excel reste produit, mais un format Parquet est aussi disponible pour les très gros dossiers (Carrefour) où Excel atteint ses limites.

Cette automatisation n'est qu'**une première brique**. Le vrai actif stratégique est la mise en place d'un Infocentre SQL agrégeant tous les FEC du cabinet, qui ouvrira sur des cas d'usage à très forte valeur ajoutée (benchmarks sectoriels, ratios automatisés, traçabilité audit, IA matching documentaire).

**Recommandation** : démarrer par la phase 1 (quick win 4-6 semaines) en mode pilote sur Audit Bordeaux, puis enchaîner phase 2 (Infocentre, 3-6 mois) avec un budget et une gouvernance dédiés.

---

## 1. Contexte et constat

### 1.1 Origine de la demande

Le pôle Audit Bordeaux a remonté un besoin de normalisation systématique des FEC, confirmé par l'équipe de Lyon. Le FEC est l'outil de travail principal des auditeurs : tout dossier commence par lui, et il subit invariablement les mêmes traitements préparatoires.

### 1.2 Manipulations manuelles observées

| Manipulation | Description | Temps unitaire |
|---|---|---|
| Ajout de racines | Extraction du 1er chiffre du compte (1 à 8) pour tri/filtrage | ~30s |
| Datation mois | Création d'une colonne mois à partir de la date d'écriture | ~30s |
| Calcul de solde | Colonne Débit-Crédit (ou inverse selon habitudes) | ~30s |
| Cumul multi-entités | Concaténation de N FEC avec colonne entité (cas Carrefour) | 5-10 min |
| Mise en forme TCD | Réordonnancement, filtres, structuration | ~30s |

**Estimation conservatrice** : 2 à 10 minutes par dossier selon complexité.

### 1.3 Points de friction identifiés

- **Limites Excel** : au-delà de ~100 000 lignes, Excel devient inadapté (lenteur d'ouverture, instabilité TCD, impossibilité de cumuler 6-7 années).
- **Cumul multi-sociétés** : tâche manuelle particulièrement coûteuse sur les grands comptes type hypermarchés.
- **BI Audit (CNCC)** : outil existant mais perçu comme une « usine à gaz », rendu visuel inadapté, performance discutable sur gros dossiers.
- **Aucune capitalisation** : chaque dossier repart de zéro, aucun benchmark inter-dossiers n'est possible.

---

## 2. Validation par le POC

### 2.1 Ce qui a été testé

Un POC Python a été développé et validé sur un FEC réel anonymisé du cabinet :

- **Volume** : 113 112 lignes, 16,17 Mo
- **Période** : novembre 2024 à octobre 2025
- **Caractéristiques** : 14 journaux, 18 colonnes norme DGFiP complète, équilibre parfait (137,3 M€ Débit = 137,3 M€ Crédit)

### 2.2 Résultats mesurés

| Étape | Durée | Volume traité |
|---|---|---|
| Diagnostic et détection format | 0,48 s | 113 k lignes |
| Lecture FEC complet | 0,27 s | 113 k lignes |
| Enrichissement (9 nouvelles colonnes) | 0,03 s | 113 k lignes |
| Export Parquet | 0,11 s | 113 k lignes |
| Export Excel formaté | 36,3 s | 113 k lignes |

**Conclusion** : le traitement métier (lecture + enrichissement + export Parquet) prend **moins d'une seconde**. Le seul goulot d'étranglement est l'écriture Excel — argument supplémentaire pour basculer les gros dossiers en Parquet + Power BI.

### 2.3 Détection automatique

Le POC détecte sans intervention :
- L'encodage (testé : ISO-8859-1, validé)
- Le séparateur (testé : tabulation, validé — pas pipe comme initialement supposé)
- Le format des dates (AAAAMMJJ DGFiP)
- Le séparateur décimal (virgule française → point)
- Les colonnes manquantes par rapport à la norme

### 2.4 Enrichissements produits

Au FEC original (18 colonnes) sont ajoutées 9 colonnes de travail :

- `Entite` — pour le cumul multi-sociétés
- `Racine` — 1er chiffre du compte (1 à 8)
- `ClasseLib` — libellé normalisé de la classe PCG
- `Sous_Racine` — 2 premiers chiffres (40, 41, 60...)
- `Annee`, `Trimestre`, `Mois` — découpages temporels
- `Solde` — Débit − Crédit, arrondi 2 décimales
- `Sens` — D / C / = pour lecture rapide

---

## 3. Roadmap proposée

### Phase 1 — Quick win normalisation (4 à 6 semaines)

**Objectif** : livrer aux auditeurs Bordelais un outil utilisable en autonomie, qui fait gagner ~10 min par dossier.

**Livrables** :
- Exécutable Windows packagé (PyInstaller) : l'auditeur dépose son FEC, double-clique, récupère un Excel ou Parquet enrichi
- Documentation utilisateur courte (1 page)
- Formation flash sur 1h en visio
- Déploiement pilote sur 5 auditeurs volontaires

**Charge** : ~3 semaines de dev (POC déjà fait), 1 semaine de tests, 1 semaine de déploiement.

**Bénéfices attendus** :
- Gain de temps mesurable : 10 min × 8 dossiers/auditeur/mois × 5 auditeurs = 400 min/mois ≈ 7h/mois
- Standardisation du retraitement (fini les variations selon les habitudes individuelles)
- Crédibilité du pôle Innovation Hub auprès du métier

**Risques** :
- Adoption faible si l'outil n'est pas intégré aux habitudes (risque mitigé par déploiement progressif et accompagnement)
- DSI potentiellement réticente sur exécutable non signé (à anticiper avec Julien)

### Phase 2 — Infocentre FEC (3 à 6 mois)

**Objectif** : agréger les 8 000+ dossiers FEC du cabinet dans une base centralisée pour ouvrir les cas d'usage à forte valeur.

**Architecture pressentie** :
- Stockage : PostgreSQL ou DuckDB selon volumétrie cible
- Ingestion : pipeline Python réutilisant la phase 1 comme connecteur
- Restitution : Power BI ou Metabase avec branding Extencia
- Gouvernance : un Data Steward dédié à la qualité de la donnée FEC

**Cas d'usage débloqués** :
- Benchmarks sectoriels propriétaires (frais bancaires moyens des électriciens, ratio masse salariale moyen des restaurateurs, etc.)
- Ratios financiers automatisés sur l'ensemble du portefeuille
- Détection d'anomalies inter-dossiers (un dossier sort-il statistiquement de la norme de son secteur ?)
- Traçabilité audit complète (log des transformations, justification des sondages)

**Risques majeurs** :
- Qualité de la donnée : un FEC mal normalisé pollue le benchmark
- RGPD et secret professionnel : règles d'accès strictes à définir
- Charge initiale d'ingestion : 8 000 FEC à charger une première fois

### Phase 3 — Intelligence augmentée (à partir du M+6)

**Objectif** : exploiter la base centralisée avec de l'IA pour augmenter le travail de l'auditeur.

**Pistes** :
- Matching factures / bons de commande / FEC via vision multimodale (Claude vision, GPT-4o)
- Reconnaissance de tampons « bon à payer » et signatures
- Génération automatique de notes de synthèse de dossier
- Assistant conversationnel pour interroger les données FEC en langage naturel

**Important** : cette phase est conditionnée par la réussite des phases 1 et 2. Pas de raccourci.

---

## 4. Comparaison aux outils du marché

| Outil | Forces | Faiblesses | Verdict |
|---|---|---|---|
| BI Audit (CNCC) | Conçu pour la profession, conformité | Usine à gaz, perf limitée gros dossiers, rendu inadapté | Insuffisant pour les besoins Extencia |
| Power BI seul | Excellent en restitution | Ne fait pas la normalisation amont | Complémentaire à notre solution, pas substitut |
| Macros Excel | Familier, déploiement facile | Ne résout pas le problème des gros dossiers, maintenance lourde, sécurité DSI | Écarté |
| Solution Python interne | Souplesse maximale, scalable, versionnable, gratuit, IP Extencia | Nécessite compétence interne | Recommandé |

---

## 5. Budget et ressources

### Phase 1
- **Coût direct** : nul (dev interne, outils open source)
- **Charge interne** : ~5 j/h Stéphane (finalisation), ~2 j/h Audit Bordeaux (tests utilisateurs)
- **Outils** : Python, Polars, openpyxl (tous gratuits)

### Phase 2
- **Infrastructure** : à chiffrer (serveur SQL ou DuckDB hébergé) — fourchette 100 à 500 €/mois selon archi
- **Charge interne** : ~30 j/h sur 6 mois, idéalement avec un alternant Data ou un prestataire ponctuel
- **Outils** : PostgreSQL ou DuckDB (gratuits), Power BI déjà licencié au cabinet

### Phase 3
- **Coûts API IA** : à évaluer selon volume — fourchette 200 à 2000 €/mois
- **Charge** : à cadrer en fin de phase 2

---

## 6. Décisions à prendre

Pour avancer, trois arbitrages sont nécessaires côté direction :

1. **Validation du sponsor Audit Bordeaux** sur le pilote phase 1 (5 auditeurs volontaires, calendrier, KPIs)
2. **Cadrage de la phase 2** : ressources, budget infra, gouvernance de la donnée FEC
3. **Positionnement vis-à-vis de la CNCC** : l'Infocentre Extencia est-il un actif différenciant gardé en interne, ou peut-il alimenter un partenariat / une mutualisation ?

---

## 7. Annexe — Architecture technique du POC

```
fec_normalizer/
├── parser_fec.py        # Lecture robuste, détection auto format
├── enrichissement.py    # Ajout colonnes calculées
├── export.py            # Excel, Parquet, CSV, rapport diagnostic
└── cli.py               # Interface ligne de commande (à finaliser)
```

**Stack** : Python 3.11+, Polars (10x plus rapide que pandas sur gros volumes), openpyxl pour le formatage Excel.

**Packaging cible** : PyInstaller pour générer un `.exe` Windows autonome distribuable sans installation Python.

**Versionnage** : Git interne Extencia, idéalement sur le GitHub du cabinet pour assurer la traçabilité des évolutions.

---

*Document préparé par le Pôle Innovation Hub pour discussion avec le Pôle Audit Bordeaux et la Direction. Toute remarque, ajout ou critique constructive est la bienvenue avant arbitrage final.*
