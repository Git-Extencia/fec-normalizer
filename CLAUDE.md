# CLAUDE.md — Projet FEC Normalizer

Ce fichier guide Claude Code (et toute future session Claude) qui interviendrait sur ce projet. Il est destiné à être lu en début de session pour donner le contexte minimum nécessaire à une contribution pertinente.

---

## Contexte projet

**Nom** : FEC Normalizer
**Sponsor métier** : Pôle Audit Bordeaux (Extencia)
**Sponsor technique** : Stéphane Torregrosa, Innovation Hub
**Statut actuel** : POC validé sur FEC réel (113 k lignes), MVP à packager

### Problème résolu

Les auditeurs Extencia répètent manuellement les mêmes manipulations sur chaque FEC (Fichier d'Écritures Comptables) avant analyse :
- Ajout des racines de compte (1 à 8) pour tri/filtrage
- Création d'une colonne mois à partir de la date d'écriture
- Calcul du solde par ligne (Débit − Crédit)
- Cumul multi-entités sur les dossiers groupes (ex. Carrefour)

Sur un dossier de 113 k lignes, ce retraitement manuel prend ~10 min. Le POC le fait en moins d'une seconde.

### Vision long terme

Ce projet est la **brique d'entrée d'un Infocentre FEC** qui agrégera à terme les 8 000+ dossiers du cabinet pour permettre :
- Benchmarks sectoriels propriétaires
- Ratios financiers automatisés
- Détection d'anomalies inter-dossiers
- Matching IA factures / FEC (phase 3)

Toute évolution doit garder cet horizon en tête.

---

## Architecture technique

### Stack

- **Python 3.11+**
- **Polars** pour la manipulation de données (10× plus rapide que pandas sur les gros volumes — ne pas remplacer par pandas)
- **openpyxl** pour le formatage Excel
- **N8N** pour l'orchestration (déclenchement, routage, notifications)
- **Supabase** envisagé pour l'Infocentre (phase 2)

### Structure du dépôt

```
fec_normalizer/
├── CLAUDE.md                # Ce fichier
├── README.md                # Doc utilisateur
├── parser_fec.py            # Lecture robuste, détection auto encodage/séparateur
├── enrichissement.py        # Ajout colonnes calculées
├── export.py                # Excel, Parquet, CSV
├── cli.py                   # À créer : interface ligne de commande
├── tests/                   # À créer : tests unitaires
├── workflows_n8n/           # À créer : exports JSON des workflows
└── docs/
    └── note_cadrage_FEC.md  # Roadmap stratégique 3 phases
```

### Norme FEC DGFiP

Le projet suit la norme officielle **BOI-CF-IOR-60-40-20-10** :
- 18 colonnes obligatoires dans un ordre défini
- Format texte (TXT ou CSV)
- Encodages courants : ISO-8859-1 (le plus fréquent), UTF-8, CP1252
- Séparateurs courants : tabulation, pipe, point-virgule
- Dates au format AAAAMMJJ
- Décimales avec virgule française (à convertir en point pour traitement)

Toute modification du parser doit préserver la compatibilité avec ces variantes.

---

## Conventions de code

### Style

- Code minimaliste, pas de commentaires redondants
- Docstrings en français (langue de travail du cabinet)
- Variables et fonctions en français quand le contexte est métier (ex. `cumuler_fec`, `racine`)
- Variables et fonctions en anglais quand le contexte est technique (ex. `parser`, `export`)
- Type hints systématiques sur les signatures publiques

### Performance

Sur les FEC volumineux (>100 k lignes), **toujours** :
- Utiliser Polars en mode lazy quand c'est possible (`pl.scan_csv` plutôt que `pl.read_csv`)
- Privilégier Parquet à Excel en sortie
- Éviter les conversions DataFrame → list of dicts → DataFrame

### Gestion d'erreurs

Le code doit échouer **explicitement** avec des messages métier compréhensibles par un auditeur, pas par un dev. Exemple :

```python
# OK
raise ValueError(f"Le fichier {chemin.name} ne contient pas la colonne 'CompteNum' obligatoire pour la norme DGFiP.")

# Pas OK
raise KeyError("CompteNum")
```

---

## Bonnes pratiques Extencia

### Charte graphique

Pour tout livrable visuel (Excel formaté, dashboards, exports HTML) :
- Couleur primaire : **#152639** (bleu nuit Extencia)
- Couleur accent : **#5EB2A1** (vert turquoise)
- Couleur signal : **#E5483A** (corail, alertes/erreurs)
- Police : Arial ou Poppins

### Format de sortie

- **Markdown** par défaut pour la documentation (compatibilité WordPress + Notion)
- **Excel formaté** pour les livrables auditeurs ne dépassant pas 100 k lignes
- **Parquet** au-delà, accompagné d'un Power BI ou d'un Excel allégé pour la consultation

### Traçabilité audit

Chaque traitement de FEC doit générer un **rapport de diagnostic** loggable, contenant au minimum :
- Nom du fichier source et son hash SHA-256
- Date/heure du traitement et utilisateur déclencheur
- Caractéristiques du FEC (lignes, période, équilibre Débit/Crédit)
- Liste des transformations appliquées
- Chemin du fichier de sortie

C'est un prérequis non négociable pour la conformité aux normes professionnelles d'audit.

---

## Workflow de développement

### Avant toute évolution majeure

1. Lire `docs/note_cadrage_FEC.md` pour comprendre où on va
2. Vérifier sur quelle phase on travaille (1 = quick win, 2 = Infocentre, 3 = IA)
3. Ne pas anticiper sur les phases ultérieures sans validation explicite

### Tests

Tout nouveau parser ou enrichissement doit être validé sur **au minimum 3 FEC de profils différents** :
- Un petit dossier (TPE, < 5 k lignes)
- Un dossier moyen (PME, ~50 k lignes)
- Un gros dossier (hypermarché, > 200 k lignes)

Les FEC de test sont stockés dans `tests/fixtures/` et **doivent être anonymisés**. Aucun SIREN ou nom de tiers réel ne doit transiter par Git.

### N8N

Les workflows N8N sont versionnés en JSON dans `workflows_n8n/`. Tout workflow modifié en production doit être réexporté dans le dépôt.

L'instance N8N de référence : `n8n.srv1269986.hstgr.cloud`

---

## Décisions techniques tranchées (à ne pas remettre en cause sans discussion)

- **Polars > pandas** : non-négociable pour les performances sur gros volumes
- **Pas de macros VBA** : non maintenable, sécurité DSI
- **Pas de Power Query seul** : ne scale pas au-delà de quelques dizaines de milliers de lignes
- **Python orchestré par N8N > tout-N8N JavaScript** : performance et maintenabilité
- **Parquet pour gros volumes** : 6× plus compact, 300× plus rapide à écrire qu'Excel

## Points en suspens à traiter

À l'attention de la prochaine session de travail :

- [ ] Packaging exécutable Windows via PyInstaller (priorité 1 pour déploiement Audit Bordeaux)
- [ ] Tests unitaires sur les 3 modules existants
- [ ] Validation de `cumuler_fec()` sur un vrai cas multi-entités (Carrefour ou équivalent)
- [ ] Création du script `cli.py` avec arguments standardisés pour intégration N8N
- [ ] Workflow N8N exemple à exporter
- [ ] Décision archi Infocentre : PostgreSQL vs DuckDB vs Supabase
- [ ] Politique de gestion des FEC sensibles (chiffrement au repos, durée de rétention)

---

## Comment Claude doit interagir sur ce projet

### Toujours

- Demander à voir un FEC réel anonymisé avant de proposer des modifications du parser
- Mesurer les performances avant et après toute optimisation
- Respecter la charte graphique Extencia sur tout livrable visuel
- Produire les retours en français
- Distinguer clairement ce qui est implémenté de ce qui est suggéré

### Jamais

- Remplacer Polars par pandas
- Stocker des données réelles non anonymisées dans le dépôt
- Ajouter des dépendances lourdes sans justification (numpy en transitif via Polars suffit pour 95 % des cas)
- Proposer des macros Excel comme solution
- Inventer des chiffres de ROI : se baser sur des mesures réelles ou indiquer explicitement « estimation à valider »

### En cas de doute

Sur les sujets métier (audit, comptabilité, normes), **demander confirmation à Stéphane** plutôt que d'inventer. Le risque d'erreur factuelle dans un contexte d'audit a des conséquences réelles.

---

*Dernière mise à jour : 28 avril 2026*
*Mainteneur : Stéphane Torregrosa — Innovation Hub Extencia*
