"""
Enrichissement FEC - Ajout des colonnes de travail pour les auditeurs

Reprend les manipulations manuelles identifiées en entretien :
- Ajout de la racine de compte (1, 2, 3, 4, 5, 6, 7, 8) pour tri/filtrage
- Ajout d'une colonne mois pour analyses temporelles
- Calcul du solde de la ligne (Débit - Crédit)
- Sens de l'écriture (D/C) pour lecture rapide
"""

from __future__ import annotations

import polars as pl


# Libellés normalisés des classes du PCG
LIBELLES_CLASSES = {
    "1": "1 - Capitaux",
    "2": "2 - Immobilisations",
    "3": "3 - Stocks et en-cours",
    "4": "4 - Tiers",
    "5": "5 - Financiers",
    "6": "6 - Charges",
    "7": "7 - Produits",
    "8": "8 - Spéciaux",
}


# Libellés français des mois — préfixés par leur numéro pour conserver un tri
# lexicographique correct (01-Janvier vient bien avant 02-Février). Le mois
# pur (sans année) est volontaire : l'année est déjà disponible dans la
# colonne Annee, et cette séparation donne des TCD bien plus lisibles
# (Annee en colonne, Mois en ligne, par exemple).
LIBELLES_MOIS = {
    1: "01-Janvier",
    2: "02-Février",
    3: "03-Mars",
    4: "04-Avril",
    5: "05-Mai",
    6: "06-Juin",
    7: "07-Juillet",
    8: "08-Août",
    9: "09-Septembre",
    10: "10-Octobre",
    11: "11-Novembre",
    12: "12-Décembre",
}


def enrichir(
    df: pl.DataFrame,
    entite: str | None = None,
    exercice: str | None = None,
) -> pl.DataFrame:
    """
    Enrichit un FEC avec les colonnes calculées habituelles des auditeurs.

    Args:
        df: DataFrame FEC issu de lire_fec()
        entite: Nom de l'entité (utile pour cumul multi-sociétés, cas dossier groupe).
            Ajoute une colonne `Entite` avec cette valeur sur toutes les lignes.
        exercice: Libellé de l'exercice (utile pour cumul multi-années d'un même client).
            Ajoute une colonne `Exercice` avec cette valeur sur toutes les lignes.
            Les deux paramètres peuvent être utilisés simultanément (cas N entités × M années).

    Returns:
        DataFrame enrichi avec nouvelles colonnes :
        - Entite (si fourni) — identifie la société d'origine
        - Exercice (si fourni) — identifie l'exercice d'origine
        - Racine (1 à 8)
        - ClasseLib (libellé de la classe PCG)
        - Sous_Racine (2 premiers chiffres : 40, 41, 60...)
        - Racine_3 (3 premiers chiffres : 401, 411, 607...)
        - Mois (01-Janvier à 12-Décembre — préfixé pour tri)
        - Annee (AAAA)
        - Trimestre (T1 à T4 — l'année est dans la colonne Annee)
        - Solde (Débit − Crédit, positif = compte débiteur)
        - Montant (Crédit − Débit, positif = compte créditeur)
        - Sens (D, C, ou =)
    """
    nouvelles_colonnes = []

    # Colonnes d'identification multi-FEC en première position si fournies
    if entite is not None:
        nouvelles_colonnes.append(pl.lit(entite).alias("Entite"))
    if exercice is not None:
        nouvelles_colonnes.append(pl.lit(exercice).alias("Exercice"))

    # Racines de compte
    # Sécurité : on strip + fill_null pour neutraliser les CompteNum vides ou absents.
    # Règle métier : un compte du PCG français commence forcément par un chiffre 1-8.
    # Tout le reste (NULL, chaîne vide, lettre, chiffre 0/9) est étiqueté "?" pour
    # que ces lignes anormales soient visibles et regroupées dans les TCD.
    compte = pl.col("CompteNum").str.strip_chars().fill_null("")
    racine = (
        pl.when(compte.str.slice(0, 1).is_in(["1", "2", "3", "4", "5", "6", "7", "8"]))
          .then(compte.str.slice(0, 1))
          .otherwise(pl.lit("?"))
    )
    nouvelles_colonnes.extend([
        racine.alias("Racine"),
        racine.replace_strict(LIBELLES_CLASSES, default="? - Inconnu").alias("ClasseLib"),
        pl.when(compte.str.len_chars() >= 2)
          .then(compte.str.slice(0, 2))
          .otherwise(pl.lit("??"))
          .alias("Sous_Racine"),
        # Racine niveau 3 = compte général PCG (401, 411, 607, 627, 707…)
        # C'est le grain le plus utilisé en analyse audit et indispensable
        # pour les benchmarks sectoriels de la phase 2 (Infocentre).
        pl.when(compte.str.len_chars() >= 3)
          .then(compte.str.slice(0, 3))
          .otherwise(pl.lit("???"))
          .alias("Racine_3"),
    ])

    # Découpages temporels
    # Mois au format "01-Janvier" : numéro en préfixe pour le tri, nom complet
    # en français pour la lecture. L'année reste dans une colonne séparée.
    # Trimestre simple "T1" à "T4" pour la même raison (année déjà disponible).
    nouvelles_colonnes.extend([
        pl.col("EcritureDate")
          .dt.month()
          .replace_strict(LIBELLES_MOIS, default="??-Inconnu")
          .alias("Mois"),
        pl.col("EcritureDate").dt.year().alias("Annee"),
        (
            pl.lit("T") + pl.col("EcritureDate").dt.quarter().cast(pl.Utf8)
        ).alias("Trimestre"),
    ])

    # Calcul Solde / Montant / Sens
    # On expose volontairement les deux conventions de calcul du solde signé
    # car elles co-existent chez nos auditeurs :
    #   - Solde   = Débit − Crédit (positif = compte débiteur)
    #   - Montant = Crédit − Débit (positif = compte créditeur)
    # L'auditeur prend celle qui correspond à son habitude au moment du TCD,
    # sans avoir à relancer un traitement. Coût en stockage : 1 colonne en
    # plus, négligeable.
    nouvelles_colonnes.extend([
        (pl.col("Debit") - pl.col("Credit")).round(2).alias("Solde"),
        (pl.col("Credit") - pl.col("Debit")).round(2).alias("Montant"),
        pl.when(pl.col("Debit") > pl.col("Credit"))
          .then(pl.lit("D"))
          .when(pl.col("Credit") > pl.col("Debit"))
          .then(pl.lit("C"))
          .otherwise(pl.lit("="))
          .alias("Sens"),
    ])

    return df.with_columns(nouvelles_colonnes)


def cumuler_fec(
    dataframes_par_libelle: dict[str, pl.DataFrame],
    colonne_libelle: str = "Entite",
) -> pl.DataFrame:
    """
    Cumule plusieurs FEC enrichis en un seul DataFrame.

    Couvre deux cas d'usage métier :
    - Cumul multi-sociétés (cas dossier groupe type Carrefour) :
        cumuler_fec({"SOC_A": df_a, "SOC_B": df_b}, colonne_libelle="Entite")
    - Cumul multi-années pour un même client (analyses pluriannuelles) :
        cumuler_fec({"2023": df_2023, "2024": df_2024}, colonne_libelle="Exercice")

    Pour les cas mixtes (N sociétés × M exercices), enrichir chaque DataFrame
    avec entite=... ET exercice=... avant l'appel, puis utiliser cette fonction
    pour la consolidation finale.

    Args:
        dataframes_par_libelle: Mapping {libellé: DataFrame} où chaque libellé
            identifiera l'origine du FEC dans le résultat.
        colonne_libelle: Nom de la colonne ajoutée pour identifier l'origine.
            Valeurs typiques : "Entite" (par défaut, pour multi-sociétés)
            ou "Exercice" (pour multi-années).

    Returns:
        DataFrame consolidé avec la colonne d'identification renseignée.
    """
    dfs = []
    for libelle, df in dataframes_par_libelle.items():
        # On (re)définit toujours la colonne pour garantir la cohérence du libellé
        df = df.with_columns(pl.lit(libelle).alias(colonne_libelle))
        dfs.append(df)
    return pl.concat(dfs, how="diagonal_relaxed")


def concatener_fec_enrichis(dataframes: list[pl.DataFrame]) -> pl.DataFrame:
    """
    Concatène simplement plusieurs DataFrames FEC déjà enrichis.

    Utilisé en mode unifié (multi-société + multi-exercice) : chaque
    DataFrame est passé séparément à enrichir() avec ses propres valeurs
    d'entite et d'exercice, puis on les empile via cette fonction sans
    re-définir aucune colonne (contrairement à cumuler_fec qui ajoute
    une colonne à la volée).
    """
    if not dataframes:
        raise ValueError("Aucun DataFrame à concaténer.")
    return pl.concat(dataframes, how="diagonal_relaxed")


def calculer_resultat_par_groupe(df: pl.DataFrame) -> pl.DataFrame:
    """
    Calcule le résultat comptable estimé par combinaison (Entite × Exercice).

    Formule métier :
        Produits  = somme(Crédit − Débit) sur les écritures de classe 7
        Charges   = somme(Débit − Crédit) sur les écritures de classe 6
        Résultat  = Produits − Charges

    Important : ce résultat est *indicatif* (FEC brut, avant écritures de
    clôture). À présenter à l'auditeur comme tel, pas comme le résultat
    fiscal définitif.

    Le groupement se fait automatiquement selon les colonnes disponibles :
    - Entite + Exercice : groupement à 2 dimensions
    - Entite seule : groupement par société (cas dossier groupe sans pluriannuel)
    - Exercice seul : groupement par exercice (cas mono-société pluriannuel)
    - Aucun des deux : 1 seule ligne globale

    Args:
        df: DataFrame enrichi (doit contenir au minimum Racine, Debit, Credit)

    Returns:
        DataFrame avec colonnes : [Entite,] [Exercice,] Produits, Charges, Resultat
    """
    if "Racine" not in df.columns:
        raise ValueError(
            "La colonne 'Racine' est requise. Appliquer enrichir() avant."
        )

    # On ne garde que les écritures de classe 6 (charges) et 7 (produits)
    df_67 = df.filter(pl.col("Racine").is_in(["6", "7"]))

    # Détermine les dimensions de groupement présentes
    dimensions = [c for c in ("Entite", "Exercice") if c in df.columns]

    # Agrégats Produits / Charges
    agg_exprs = [
        pl.when(pl.col("Racine") == "7")
          .then(pl.col("Credit") - pl.col("Debit"))
          .otherwise(0.0)
          .sum()
          .round(2)
          .alias("Produits"),
        pl.when(pl.col("Racine") == "6")
          .then(pl.col("Debit") - pl.col("Credit"))
          .otherwise(0.0)
          .sum()
          .round(2)
          .alias("Charges"),
    ]

    if dimensions:
        resultat = df_67.group_by(dimensions).agg(agg_exprs)
        resultat = resultat.sort(dimensions)
    else:
        resultat = df_67.select(agg_exprs)

    # Colonne Résultat = Produits − Charges
    resultat = resultat.with_columns(
        (pl.col("Produits") - pl.col("Charges")).round(2).alias("Resultat")
    )
    return resultat


def reorganiser_colonnes(df: pl.DataFrame) -> pl.DataFrame:
    """
    Réordonne les colonnes pour mettre les colonnes calculées en tête.
    Pratique pour les TCD : les dimensions d'analyse en premier.
    """
    colonnes_priorite = [
        "Entite", "Exercice",
        "Racine", "ClasseLib", "Sous_Racine", "Racine_3",
        "Annee", "Trimestre", "Mois",
        "JournalCode", "JournalLib",
        "EcritureNum", "EcritureDate",
        "CompteNum", "CompteLib",
        "CompAuxNum", "CompAuxLib",
        "PieceRef", "PieceDate", "EcritureLib",
        "Debit", "Credit", "Solde", "Montant", "Sens",
        "EcritureLet", "DateLet", "ValidDate",
        "Montantdevise", "Idevise",
    ]

    colonnes_existantes = [c for c in colonnes_priorite if c in df.columns]
    autres = [c for c in df.columns if c not in colonnes_existantes]
    return df.select(colonnes_existantes + autres)
