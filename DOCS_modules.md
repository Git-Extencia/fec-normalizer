# Documentation — Modules Python du projet FEC Normalizer

**Public visé :** Stéphane Torregrosa (pilote projet) et toute personne devant comprendre ce que fait chaque brique sans nécessairement coder.

**Version :** 1.0 — 21 avril 2026
**État :** 5 modules opérationnels, `cli.py` à venir.

---

## Vue d'ensemble en une page

Le projet est composé de **5 fichiers Python** qui se complètent, plus une checklist et la présente doc. Chaque module a un rôle unique et bien délimité — c'est un principe de conception qui rend le code lisible et testable.

```
┌──────────────────────────────────────────────────────────────────┐
│                                                                  │
│   FEC source (.txt)                                              │
│        │                                                         │
│        ▼                                                         │
│   parser_fec.py            ←── lit le FEC et le diagnostique     │
│        │                                                         │
│        ▼                                                         │
│   enrichissement.py        ←── ajoute les colonnes de travail    │
│        │                                                         │
│        ▼                                                         │
│   export.py                ←── écrit Excel, Parquet, diagnostic  │
│        │                                                         │
│        ▼                                                         │
│   FEC enrichi + rapport diagnostic                               │
│                                                                  │
│   generer_fec_test.py      ←── outil annexe : produit des FEC    │
│                                  factices pour tester sans       │
│                                  utiliser de FEC client réel     │
│                                                                  │
│   test_poc.py              ←── script de validation initiale     │
│                                  (à remplacer par de vrais tests │
│                                  pytest dans une prochaine tâche)│
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

Tous les modules tournent sur **Python 3.11+** et utilisent **Polars** pour la manipulation de données (10 fois plus rapide que pandas sur les gros volumes). Le seul module qui produit de l'Excel formaté utilise **openpyxl**.

---

## 1. `parser_fec.py` — La lecture intelligente du FEC

**Rôle :** transformer un fichier FEC brut (au format texte tel que l'éditeur du client l'a généré) en données exploitables, et produire un rapport de diagnostic conforme aux exigences de traçabilité audit.

### Ce qu'il sait faire

Le parser ne se contente pas de lire un fichier — il **détecte automatiquement** :
- L'**encodage** parmi UTF-8, ISO-8859-1, CP1252, UTF-16. La très grande majorité des FEC français sont en ISO-8859-1, mais certains éditeurs sortent de l'UTF-8 et c'est piégeux si on ne le détecte pas (les accents deviennent `é` au lieu de `é`).
- Le **séparateur** parmi tabulation, pipe (`|`), point-virgule. Selon l'éditeur, l'export du FEC peut utiliser n'importe lequel.
- Les **conversions de format** exigées par la norme DGFiP : virgules françaises remplacées par des points pour les montants, dates au format `AAAAMMJJ` converties en vraies dates Polars, espaces parasites supprimés.

### Les fonctions exposées

| Fonction | Ce qu'elle fait |
|---|---|
| `lire_fec(chemin)` | Lit le fichier et retourne un DataFrame Polars prêt à l'emploi avec les bons types de données. |
| `detecter_format(chemin)` | Retourne le couple `(encodage, séparateur)` détecté. Utile pour vérifier ce que l'outil a deviné. |
| `calculer_hash_sha256(chemin)` | Calcule la signature unique du fichier source (64 caractères hex). Indispensable à la traçabilité audit. |
| `creer_rapport_diagnostic(chemin, transformations, df)` | Produit un rapport de diagnostic complet (qui, quand, sur quelle machine, quel fichier, quelles transformations). |
| `diagnostiquer_fec(chemin)` | Version simplifiée du rapport (sans liste de transformations), pour usage rapide. |

### Le rapport de diagnostic en détail

C'est la pièce maîtresse en termes de conformité audit. Il contient :

- **Traçabilité** : horodatage UTC ISO 8601, utilisateur, machine, version de l'outil
- **Source** : nom du fichier, chemin complet, taille, hash SHA-256
- **Format détecté** : encodage et séparateur
- **Caractéristiques métier** : nombre de lignes, période couverte, nombre de journaux, totaux Débit et Crédit, écart d'équilibre
- **Conformité norme DGFiP** : liste des colonnes présentes vs colonnes manquantes parmi les 18 obligatoires
- **Transformations appliquées** : liste de ce que l'outil a fait au FEC

Le rapport est sérialisable proprement en JSON, donc archivable, comparable, loggable.

### Limites connues

- Si le FEC contient un encodage exotique non listé (ex. UTF-32, EBCDIC), la détection échoue avec un message d'erreur explicite.
- Si la première colonne n'est pas `JournalCode` (FEC mal formaté ou avec en-tête atypique), la détection peut renvoyer un mauvais séparateur. Cas rare mais à surveiller.

---

## 2. `enrichissement.py` — Les colonnes de travail des auditeurs

**Rôle :** ajouter au FEC les colonnes calculées qu'un auditeur fabriquerait à la main avant d'attaquer son analyse. Ce module remplace les "tâches vaisselle" répétitives décrites par le pôle Audit.

### Ce qu'il ajoute concrètement

À partir des 18 colonnes du FEC normé, le module en ajoute 9 :

| Colonne ajoutée | Comment elle est calculée | À quoi elle sert |
|---|---|---|
| `Entite` | Valeur fixe passée en paramètre (ex. `"SOC_ALPHA"`) | Identifier la société d'origine quand on cumule plusieurs FEC (cas Carrefour multi-entités) |
| `Racine` | 1er chiffre du `CompteNum`, ou `"?"` si anormal | Filtrer rapidement par classe PCG dans un TCD |
| `ClasseLib` | Libellé de la classe (`"4 - Tiers"`, `"6 - Charges"`, …) | Lecture humaine de la racine |
| `Sous_Racine` | 2 premiers caractères du compte (40, 41, 60, 70…), ou `"??"` si trop court | Granularité plus fine que la classe pour analyses ciblées |
| `Annee` | Année extraite de `EcritureDate` | Découpage temporel par exercice |
| `Trimestre` | Format `AAAA-Tn` (`"2025-T1"`, `"2025-T2"`…) | Tri lexicographique chronologique |
| `Mois` | Format `AAAA-MM` (`"2025-01"`…) | Idem, granularité mensuelle |
| `Solde` | `Débit − Crédit`, arrondi à 2 décimales | Lecture rapide du sens de l'écriture |
| `Sens` | `"D"`, `"C"` ou `"="` selon que Débit > Crédit, < ou = | Filtrage rapide |

### La règle métier sur les comptes anormaux

Un compte du PCG français commence forcément par un chiffre 1 à 8. Tout ce qui ne respecte pas cette règle (compte vide, NULL, commençant par une lettre, ou par 0/9) est étiqueté `Racine = "?"` et `ClasseLib = "? - Inconnu"`. Conséquence pratique : ces lignes anormales sont **regroupées et visibles** dans les TCD plutôt que silencieusement masquées avec des cellules vides. C'est un mini-contrôle qualité gratuit : un FEC sain doit avoir zéro ligne avec `Racine = "?"`.

### Les fonctions exposées

| Fonction | Ce qu'elle fait |
|---|---|
| `enrichir(df, entite=None)` | Ajoute les 9 colonnes calculées au DataFrame. Le paramètre `entite` est facultatif. |
| `cumuler_fec(dataframes_par_entite)` | Concatène plusieurs FEC enrichis en un seul, en préservant la colonne `Entite`. Cas multi-sociétés. |
| `reorganiser_colonnes(df)` | Réordonne les colonnes pour mettre les dimensions d'analyse en tête (pratique pour les TCD). |

### Limites connues

- `cumuler_fec()` n'a pas encore été testé sur un cas réel multi-entités (à valider avant le pilote sur un dossier groupe).
- Le calcul du Trimestre suppose que `EcritureDate` est bien typée comme date — si le parser n'a pas réussi à parser certaines dates, elles seront `NULL` dans Trimestre.

---

## 3. `export.py` — La sortie multi-formats

**Rôle :** écrire le FEC enrichi sur disque dans le format approprié à la volumétrie, avec mise en forme charte Extencia pour l'Excel.

### La logique de bascule auto

Le module choisit automatiquement le format selon la taille :

| Volume | Format auto | Pourquoi |
|---|---|---|
| Moins de 100 000 lignes | Excel `.xlsx` formaté | Excel reste fluide, l'auditeur l'ouvre directement, peut faire ses TCD |
| 100 000 lignes ou plus | Parquet `.parquet` compressé | Excel devient lent à l'écriture (>30 s) et à l'ouverture ; Parquet est 6× plus compact et lisible dans Power BI |

Le seuil est paramétrable via la constante `SEUIL_EXCEL`. L'utilisateur peut aussi forcer un format spécifique avec le paramètre `format_force=` (`"xlsx"`, `"parquet"`, ou `"csv"`).

### La mise en forme Excel

L'export Excel applique la charte graphique Extencia :
- En-têtes en bleu nuit `#152639`, texte blanc, police Arial gras
- Filtres automatiques sur toutes les colonnes
- Première ligne figée (freeze panes A2)
- Largeurs de colonnes adaptatives (calculées sur les 100 premières lignes pour éviter le coût)

### Le rapport de diagnostic exporté

Le module exporte aussi le rapport de diagnostic dans un Excel séparé, avec en-têtes en vert turquoise `#5EB2A1`. Pratique pour archivage et conformité CNCC : ce fichier accompagne le FEC enrichi dans le dossier de travail.

### Les fonctions exposées

| Fonction | Ce qu'elle fait |
|---|---|
| `exporter(df, chemin_sortie, format_force=None)` | Exporte le DataFrame. Si `format_force=None`, choisit automatiquement Excel ou Parquet selon le volume. |
| `exporter_rapport_diagnostic(diagnostics, chemin_sortie)` | Écrit un Excel formaté contenant le ou les rapports de diagnostic. |

### Performances mesurées (sur la machine de dev)

| Volume | Format | Durée | Taille fichier |
|---|---|---|---|
| 5 000 lignes | Excel | 0,9 s | 0,5 Mo |
| 50 000 lignes | Excel | 9 s | 5,0 Mo |
| 200 000 lignes | Parquet | < 1 s | 5,7 Mo |

À retenir : **le Parquet de 200 000 lignes est plus petit que l'Excel de 50 000 lignes**. Sur les dossiers Carrefour multi-années, l'écart sera encore plus spectaculaire.

### Limites connues

- L'écriture Excel est faite ligne par ligne via openpyxl, ce qui est le seul vrai goulot du pipeline (~36 s sur 113 k lignes). Optimisable plus tard avec `xlsxwriter` ou `polars.write_excel()` si besoin.
- L'export CSV utilise par défaut le séparateur point-virgule (compatible Excel français).

---

## 4. `generer_fec_test.py` — Le générateur de FEC synthétiques

**Rôle :** produire à la demande des FEC totalement factices mais rigoureusement conformes à la norme DGFiP, pour développer et tester sans utiliser de FEC client réel.

### Pourquoi cet outil existe

La doctrine du projet (CLAUDE.md) interdit de stocker dans le dépôt Git des FEC contenant des données client réelles (SIREN, noms de tiers, montants nominatifs). Pour autant, on a besoin de FEC pour développer, tester les performances, valider les corrections de bugs. Solution : générer des FEC factices à la demande.

### Ce que le générateur produit

Un fichier texte parfaitement conforme à la norme :
- 18 colonnes obligatoires dans l'ordre normé
- Encodage ISO-8859-1
- Séparateur tabulation
- Dates au format AAAAMMJJ
- Décimales avec virgule française
- **Équilibre Débit/Crédit garanti par construction** (à chaque écriture, débits = crédits)

Avec une distribution réaliste : 40 % de ventes, 35 % d'achats, 25 % de banque, sur les 7 journaux courants (VTE, ACH, BNQ, CAI, OD, PAY, AN). Les comptes utilisés sont du PCG français (411xxx pour les clients, 401xxx pour les fournisseurs, 6xx et 7xx pour les charges/produits, etc.). Aucun lien avec un client existant.

### Comment l'utiliser

```bash
# Petit FEC pour test rapide
python3 generer_fec_test.py --lignes 5000 --sortie fec_petit.txt

# FEC moyen
python3 generer_fec_test.py --lignes 50000 --sortie fec_moyen.txt --annee 2024

# Gros FEC pour test de performance
python3 generer_fec_test.py --lignes 200000 --sortie fec_gros.txt

# Avec graine pour reproductibilité (mêmes données à chaque exécution)
python3 generer_fec_test.py --lignes 5000 --sortie fec_test.txt --seed 42
```

### Le mode reproductible (`--seed`)

Sans `--seed`, chaque exécution produit un FEC différent (utile pour tester sur de la variété). Avec `--seed N`, la génération devient strictement reproductible : même graine = même FEC, à la virgule près. C'est la base des **tests de régression** : on génère un FEC avec une graine fixe avant une modification du code, on relance après, on compare. Si les sorties sont identiques sur les écritures normales, c'est qu'on n'a rien cassé.

---

## 5. `test_poc.py` — Le script de validation initiale

**Rôle historique :** script qui a servi à valider le POC sur le FEC réel de 113 k lignes lors du développement initial.

**État actuel :** à remplacer par de vrais tests pytest. Le fichier contient des chemins d'environnement de développement (`/home/claude/...`) qui ne fonctionnent pas en production. Tâche prévue dans la roadmap d'industrialisation (mais pas dans la checklist du pilote — ce n'est pas bloquant pour la livraison du `.exe`).

---

## Comment les modules s'utilisent ensemble

Aujourd'hui, sans `cli.py`, on enchaîne les modules manuellement en Python. Voilà la séquence type pour traiter un FEC :

```python
from parser_fec import lire_fec, creer_rapport_diagnostic
from enrichissement import enrichir, reorganiser_colonnes
from export import exporter, exporter_rapport_diagnostic

# 1. Lire le FEC
df = lire_fec("mon_fec.txt")

# 2. L'enrichir avec les colonnes de travail
df_enrichi = enrichir(df, entite="SOC_ALPHA")
df_enrichi = reorganiser_colonnes(df_enrichi)

# 3. Préparer la liste des transformations appliquées (pour la traçabilité)
transformations = [
    {"nom": "ajout_racine", "description": "..."},
    {"nom": "ajout_mois", "description": "..."},
    # etc.
]

# 4. Produire le rapport de diagnostic
rapport = creer_rapport_diagnostic("mon_fec.txt", transformations=transformations, df=df_enrichi)

# 5. Exporter le FEC enrichi (format auto selon volume)
exporter(df_enrichi, "sortie/mon_fec_enrichi")

# 6. Exporter le rapport de diagnostic
exporter_rapport_diagnostic([rapport], "sortie/mon_fec_diagnostic")
```

Cette séquence est exactement ce que la **tâche 6 (création de `cli.py`)** va automatiser. Une fois `cli.py` en place, l'utilisateur tapera simplement :

```bash
python3 cli.py --input mon_fec.txt --output-dir sortie/
```

Et l'outil enchaînera tout seul les 6 étapes ci-dessus, en maintenant automatiquement la liste des transformations.

---

## Dépendances Python

Le projet a deux dépendances externes seulement :

| Bibliothèque | Rôle | Installation |
|---|---|---|
| `polars` | Manipulation de données ultra-rapide | `pip3 install polars --break-system-packages` |
| `openpyxl` | Écriture Excel formatée | `pip3 install openpyxl --break-system-packages` |

Tout le reste utilise la bibliothèque standard de Python (argparse, hashlib, pathlib, datetime, getpass, platform, random) — donc aucune installation supplémentaire à prévoir, ni risque de version cassée.

---

## Ce qui manque encore (rappel)

Pour passer du POC actuel au `.exe` livrable au pilote Audit Bordeaux, il reste sur la checklist :

- **Tâche 6** : créer `cli.py` (point d'entrée ligne de commande)
- **Tâche 7** : ajouter une boîte de dialogue Tkinter pour le double-clic
- **Tâche 8** : tester sur 3 FEC différents (petit, moyen, volontairement bancal)
- **Tâche 9** : rédiger la notice utilisateur 1 page
- **Tâches 10-13** : packaging PyInstaller et test sur poste vierge
- **Tâches 14-16** : pilote Audit Bordeaux

---

*Document à mettre à jour à chaque évolution majeure des modules. La référence d'autorité reste le code lui-même — cette doc est un guide d'orientation, pas une spec contractuelle.*
