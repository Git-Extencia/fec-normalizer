"""
Parser FEC - Lecture robuste des Fichiers d'Écritures Comptables
Conforme à la norme DGFiP (BOI-CF-IOR-60-40-20-10)

Gère automatiquement :
- Détection du séparateur (tabulation, pipe, point-virgule)
- Détection de l'encodage (UTF-8, ISO-8859-1/Latin-1, CP1252)
- Conversion des décimales virgule -> point
- Parsing des dates au format AAAAMMJJ
"""

from __future__ import annotations

import getpass
import hashlib
import platform
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple

import polars as pl


# Colonnes obligatoires du FEC selon norme DGFiP
COLONNES_FEC_NORME = [
    "JournalCode", "JournalLib", "EcritureNum", "EcritureDate",
    "CompteNum", "CompteLib", "CompAuxNum", "CompAuxLib",
    "PieceRef", "PieceDate", "EcritureLib", "Debit", "Credit",
    "EcritureLet", "DateLet", "ValidDate", "Montantdevise", "Idevise"
]

ENCODAGES_TESTES = ["utf-8", "iso-8859-1", "cp1252", "utf-16"]
SEPARATEURS_TESTES = ["\t", "|", ";"]


def detecter_format(chemin: Path) -> Tuple[str, str]:
    """
    Détecte l'encodage et le séparateur du fichier FEC.

    La détection est robuste à plusieurs pièges fréquents :
    - BOM (Byte Order Mark) en tête de fichier UTF-8 ou UTF-16
    - Guillemets autour des en-têtes
    - Espaces parasites
    - Faux positif sur encodage incorrect (par ex. UTF-16 lu en ISO-8859-1)

    Le premier en-tête doit être exactement "JournalCode" (après nettoyage),
    ET il faut retrouver au moins 3 autres en-têtes connus de la norme DGFiP
    parmi les 17 restants. Cette double vérification élimine les faux
    positifs sur fichiers mal encodés.

    Returns:
        (encodage, separateur)
    """
    # Caractères à ignorer en tête : BOM UTF-8, BOM UTF-16, guillemets, espaces
    a_nettoyer = "﻿￾ \t\"'"

    def _nettoyer(s: str) -> str:
        return s.strip().lstrip(a_nettoyer).rstrip(a_nettoyer).strip()

    for encodage in ENCODAGES_TESTES:
        try:
            with open(chemin, "r", encoding=encodage) as f:
                premiere_ligne = f.readline()

            for sep in SEPARATEURS_TESTES:
                colonnes = [_nettoyer(c) for c in premiere_ligne.strip().split(sep)]

                # 1. Au moins 15 colonnes (norme FEC = 18)
                if len(colonnes) < 15:
                    continue

                # 2. Premier en-tête = exactement "JournalCode"
                if colonnes[0] != "JournalCode":
                    continue

                # 3. Au moins 3 autres en-têtes connus retrouvés (anti-faux-positif
                #    sur encodage erroné qui produit du charabia)
                connues_trouvees = sum(
                    1 for c in colonnes[1:] if c in COLONNES_FEC_NORME
                )
                if connues_trouvees < 3:
                    continue

                return encodage, sep
        except (UnicodeDecodeError, UnicodeError):
            continue

    raise ValueError(
        f"Impossible de détecter le format du fichier {chemin.name}. "
        f"Encodages testés : {ENCODAGES_TESTES}, "
        f"séparateurs testés : {SEPARATEURS_TESTES}. "
        f"Vérifiez que le fichier respecte bien la norme DGFiP "
        f"(18 colonnes en en-tête, première colonne 'JournalCode')."
    )


def lire_fec(chemin: str | Path) -> pl.DataFrame:
    """
    Lit un FEC et le charge en DataFrame Polars.

    Conversions automatiques :
    - Décimales virgule -> point pour Debit, Credit, Montantdevise
    - Dates AAAAMMJJ -> Date Polars pour EcritureDate, PieceDate, ValidDate, DateLet

    Args:
        chemin: Chemin vers le fichier FEC

    Returns:
        DataFrame Polars avec types corrects
    """
    chemin = Path(chemin)
    if not chemin.exists():
        raise FileNotFoundError(f"Fichier introuvable : {chemin}")

    encodage, separateur = detecter_format(chemin)

    # Lecture brute en string pour contrôler les conversions
    df = pl.read_csv(
        chemin,
        separator=separateur,
        encoding=encodage,
        infer_schema_length=0,  # Tout en string, on convertit nous-mêmes
        truncate_ragged_lines=True,
    )

    # Nettoyage des espaces dans les colonnes texte
    colonnes_texte = ["JournalCode", "JournalLib", "EcritureNum", "CompteNum",
                       "CompteLib", "CompAuxNum", "CompAuxLib", "PieceRef",
                       "EcritureLib", "EcritureLet", "Idevise"]

    for col in colonnes_texte:
        if col in df.columns:
            df = df.with_columns(pl.col(col).str.strip_chars())

    # Conversion des montants : virgule -> point, puis Float64
    colonnes_montants = ["Debit", "Credit", "Montantdevise"]
    for col in colonnes_montants:
        if col in df.columns:
            df = df.with_columns(
                pl.col(col)
                .str.strip_chars()
                .str.replace(",", ".")
                .cast(pl.Float64, strict=False)
                .fill_null(0.0)
            )

    # Conversion des dates AAAAMMJJ -> Date
    colonnes_dates = ["EcritureDate", "PieceDate", "ValidDate", "DateLet"]
    for col in colonnes_dates:
        if col in df.columns:
            df = df.with_columns(
                pl.col(col)
                .str.strip_chars()
                .str.to_date(format="%Y%m%d", strict=False)
            )

    return df


def deduire_exercice_depuis_nom(nom_fichier: str) -> str | None:
    """
    Devine le libellé d'exercice à partir du nom de fichier normé DGFiP.

    Convention DGFiP officielle : le nom d'un FEC est construit ainsi
        <SIREN sur 9 chiffres><texte libre éventuel>FEC<AAAAMMJJ>.txt
    où AAAAMMJJ est la date de clôture de l'exercice.

    Logique de libellé retournée :
    - Si la date de clôture est un 31/12 → exercice civil → on retourne juste
      l'année "AAAA" (ex. "2025")
    - Si la date de clôture est autre → exercice décalé → on retourne "MM/AAAA"
      (ex. "06/2025" pour une clôture au 30/06)
    - Si la date n'est pas détectable dans le nom → None (l'auditeur saisira
      le libellé à la main).

    Args:
        nom_fichier: Nom du fichier FEC (avec ou sans extension).

    Returns:
        Libellé d'exercice (str) ou None si non détectable.
    """
    stem = Path(nom_fichier).stem
    # On cherche 8 chiffres consécutifs à la fin (la date de clôture AAAAMMJJ)
    match = re.search(r"(\d{4})(\d{2})(\d{2})\s*$", stem)
    if not match:
        return None
    annee, mois, jour = match.groups()
    # Validation basique : année plausible (1990-2099), mois 01-12, jour 01-31
    if not (1990 <= int(annee) <= 2099 and 1 <= int(mois) <= 12 and 1 <= int(jour) <= 31):
        return None
    # Exercice civil clôturé au 31/12 → libellé = année seule
    if mois == "12" and jour == "31":
        return annee
    # Exercice décalé → libellé = MM/AAAA
    return f"{mois}/{annee}"


def deduire_siren_depuis_nom(nom_fichier: str) -> str | None:
    """
    Extrait le SIREN d'un nom de fichier FEC selon la convention DGFiP :
        <SIREN sur 9 chiffres><texte libre éventuel>FEC<AAAAMMJJ>.txt

    Retourne le SIREN (9 chiffres) ou None si le nom ne commence pas par
    9 chiffres consécutifs.

    Notes :
    - Pas de validation par clé de Luhn ici. Le SIREN sera ensuite confronté
      à l'API recherche-entreprises qui rejettera de toute façon les SIREN
      inexistants.
    - Le préfixe "0" est conservé (un SIREN peut commencer par 0 même si
      c'est rare).

    Args:
        nom_fichier: Nom du fichier FEC (avec ou sans extension).

    Returns:
        SIREN sur 9 chiffres (str) ou None si non détectable.
    """
    stem = Path(nom_fichier).stem
    match = re.match(r"^(\d{9})", stem)
    if not match:
        return None
    return match.group(1)


def chercher_raison_sociale(siren: str, timeout: float = 3.0) -> str | None:
    """
    Interroge l'API publique recherche-entreprises (API Gouv) pour obtenir
    la raison sociale officielle d'une entreprise à partir de son SIREN.

    Pourquoi cette API plutôt que Sirene-INSEE :
    - Pas de clé API requise (Sirene exige une inscription)
    - Données rafraîchies quotidiennement à partir de Sirene
    - Format JSON propre avec `nom_complet` toujours présent

    Tolérance aux pannes : en cas de timeout, d'erreur réseau, d'API down
    ou de résultat vide, on retourne None. Côté UI, l'auditeur sera invité
    à saisir manuellement le nom — comme c'est déjà le cas pour l'exercice
    quand l'auto-détection échoue.

    Confidentialité : seul le SIREN sort du serveur. Le SIREN est une donnée
    publique (publié au BODACC), donc pas une fuite au sens RGPD. Aucun
    contenu du FEC n'est transmis.

    Args:
        siren: Numéro SIREN à 9 chiffres.
        timeout: Délai maximum d'attente en secondes (défaut : 3.0).

    Returns:
        Raison sociale (str) ou None si non trouvée / API indisponible.
    """
    if not siren or not siren.isdigit() or len(siren) != 9:
        return None

    try:
        import json
        import urllib.parse
        import urllib.request

        url = (
            "https://recherche-entreprises.api.gouv.fr/search"
            f"?q={urllib.parse.quote(siren)}&page=1&per_page=1"
        )
        req = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "FEC-Normalizer/1.1"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        results = data.get("results", [])
        if not results:
            return None

        entreprise = results[0]
        # Vérifie que c'est bien le bon SIREN (l'API peut faire du fuzzy match)
        if entreprise.get("siren") != siren:
            return None

        # nom_complet est le champ standard ; fallback sur nom_raison_sociale
        return (
            entreprise.get("nom_complet")
            or entreprise.get("nom_raison_sociale")
            or None
        )
    except Exception:
        # Volontairement large : timeout, erreur DNS, JSON mal formé, etc.
        # On préfère un échec silencieux qui laisse l'auditeur saisir à la
        # main plutôt qu'une exception qui plante l'UI.
        return None


def calculer_hash_sha256(chemin: Path, taille_buffer: int = 65536) -> str:
    """
    Calcule la signature SHA-256 d'un fichier, lu par chunks pour rester
    efficace y compris sur des FEC de plusieurs centaines de Mo.

    Cette signature est l'équivalent numérique d'une empreinte digitale :
    si une seule virgule change dans le fichier, la signature change
    intégralement. Indispensable à la traçabilité audit.
    """
    h = hashlib.sha256()
    with open(chemin, "rb") as f:
        while chunk := f.read(taille_buffer):
            h.update(chunk)
    return h.hexdigest()


def creer_rapport_diagnostic(
    chemin: str | Path,
    transformations: list[dict] | None = None,
    df: pl.DataFrame | None = None,
) -> dict:
    """
    Produit un rapport de diagnostic complet conforme aux exigences de
    traçabilité audit (norme professionnelle CNCC / NEP).

    Le rapport contient :
    - les métadonnées de traçabilité (qui, quand, sur quelle machine)
    - l'identification du fichier source (nom, taille, hash SHA-256)
    - les caractéristiques métier (lignes, période, équilibre D/C)
    - la liste des transformations appliquées par l'outil

    Args:
        chemin: Chemin vers le fichier FEC source.
        transformations: Liste de dicts décrivant chaque transformation
            appliquée. Format conseillé :
            {"nom": "ajout_racine", "description": "...", "horodatage": "..."}
        df: DataFrame déjà chargé (évite une relecture coûteuse).
            Si None, le fichier est lu.

    Returns:
        Dictionnaire prêt à sérialiser en JSON ou à exporter en Excel.
    """
    chemin = Path(chemin)
    if not chemin.exists():
        raise FileNotFoundError(f"Fichier introuvable : {chemin}")

    transformations = transformations or []
    encodage, separateur = detecter_format(chemin)
    if df is None:
        df = lire_fec(chemin)

    return {
        # --- Traçabilité ---
        "horodatage_traitement": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "utilisateur": getpass.getuser(),
        "machine": platform.node(),
        "outil_version": "FEC_Normalizer 1.0",
        # --- Source ---
        "fichier_source": chemin.name,
        "fichier_chemin": str(chemin.resolve()),
        "fichier_taille_mo": round(chemin.stat().st_size / (1024 * 1024), 2),
        "fichier_sha256": calculer_hash_sha256(chemin),
        # --- Format détecté ---
        "encodage_detecte": encodage,
        "separateur_detecte": "tabulation" if separateur == "\t" else f"'{separateur}'",
        # --- Caractéristiques FEC ---
        "nb_lignes": df.height,
        "nb_colonnes": df.width,
        "colonnes_presentes": df.columns,
        "colonnes_manquantes": [c for c in COLONNES_FEC_NORME if c not in df.columns],
        "periode_min": str(df["EcritureDate"].min()) if "EcritureDate" in df.columns else None,
        "periode_max": str(df["EcritureDate"].max()) if "EcritureDate" in df.columns else None,
        "nb_journaux": df["JournalCode"].n_unique() if "JournalCode" in df.columns else None,
        "total_debit": round(df["Debit"].sum(), 2) if "Debit" in df.columns else None,
        "total_credit": round(df["Credit"].sum(), 2) if "Credit" in df.columns else None,
        "ecart_equilibre": round(df["Debit"].sum() - df["Credit"].sum(), 2)
            if "Debit" in df.columns and "Credit" in df.columns else None,
        # --- Transformations appliquées ---
        "transformations_appliquees": transformations,
    }


def diagnostiquer_fec(chemin: str | Path) -> dict:
    """
    Diagnostic FEC standard, sans transformations.
    Conserve la signature historique du POC (rétrocompatibilité).
    Pour un rapport complet incluant les transformations appliquées,
    utiliser creer_rapport_diagnostic().
    """
    return creer_rapport_diagnostic(chemin)
