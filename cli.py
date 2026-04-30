#!/usr/bin/env python3
"""
cli.py — Interface ligne de commande de FEC Normalizer.

Point d'entrée du programme. Enchaîne :
  1. Lecture et diagnostic préliminaire du FEC
  2. Enrichissement (racines, mois, solde, sens, entité)
  3. Export du FEC enrichi (Excel ou Parquet selon volume)
  4. Export du rapport de diagnostic (Excel + JSON)

Maintient automatiquement la liste des transformations appliquées,
qui est intégrée au rapport pour la traçabilité audit.

Usage typique :
    python3 cli.py --input mon_fec.txt --output-dir resultats/

Conforme à la norme DGFiP BOI-CF-IOR-60-40-20-10.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from parser_fec import lire_fec, detecter_format, creer_rapport_diagnostic
from enrichissement import enrichir, cumuler_fec, reorganiser_colonnes
from export import (
    exporter,
    exporter_rapport_diagnostic,
    SEUIL_AVERTISSEMENT_EXCEL,
    LIMITE_EXCEL_MONOFEUILLE,
)


VERSION = "1.1"
LARGEUR_BANDEAU = 70

# Colonnes sans lesquelles on ne peut rien faire de l'enrichissement.
# Si l'une manque, on refuse de continuer avec un message métier explicite.
COLONNES_CRITIQUES = ("CompteNum", "EcritureDate", "Debit", "Credit")

# Mode de cumul quand plusieurs FEC sont fournis en entrée
MODE_CUMUL_ENTITE = "entite"
MODE_CUMUL_EXERCICE = "exercice"


# ---------------------------------------------------------------------------
# Utilitaires d'affichage et de journalisation
# ---------------------------------------------------------------------------

def _horodatage() -> str:
    """Horodatage UTC ISO 8601, tronqué à la seconde."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _journaliser(transformations: list[dict], nom: str, description: str) -> None:
    """Ajoute une entrée datée à la liste des transformations."""
    transformations.append({
        "nom": nom,
        "description": description,
        "horodatage": _horodatage(),
    })


class Console:
    """Affichage console avec un mode silencieux pour usage en script."""

    def __init__(self, quiet: bool = False):
        self.quiet = quiet

    def bandeau(self, message: str, char: str = "=") -> None:
        if self.quiet:
            return
        print(char * LARGEUR_BANDEAU)
        print(f"  {message}")
        print(char * LARGEUR_BANDEAU)

    def section(self, etape: str, titre: str) -> None:
        if self.quiet:
            return
        print(f"\n  [{etape}] {titre}")

    def ligne(self, label: str, valeur: str) -> None:
        if self.quiet:
            return
        print(f"        {label:<20}: {valeur}")

    def ok(self, message: str) -> None:
        if self.quiet:
            return
        print(f"        ✓ {message}")

    def info(self, message: str) -> None:
        if self.quiet:
            return
        print(f"  {message}")


# ---------------------------------------------------------------------------
# Parsing des arguments
# ---------------------------------------------------------------------------

def parser_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="fec_normalizer",
        description=(
            "Normalise et enrichit un FEC (Fichier des Écritures Comptables) "
            "pour analyse audit. Conforme à la norme DGFiP BOI-CF-IOR-60-40-20-10."
        ),
        epilog=(
            "Mode interactif : lancez sans argument pour ouvrir une boîte "
            "de dialogue. Mode CLI : utilisez --input et --output-dir."
        ),
    )
    p.add_argument(
        "-i", "--input", type=Path, default=None, nargs="+",
        help="Chemin(s) vers le ou les FEC source(s) (.txt ou .csv). "
             "Plusieurs valeurs autorisées pour cumuler. "
             "Si omis, une boîte de dialogue s'ouvre.",
    )
    p.add_argument(
        "-o", "--output-dir", type=Path, default=None,
        help="Dossier de sortie. Si omis en mode interactif, "
             "une boîte de dialogue s'ouvre. En mode CLI, défaut : dossier courant.",
    )
    p.add_argument(
        "-f", "--format", choices=["auto", "xlsx", "parquet", "csv"],
        default="auto",
        help="Format de sortie (par défaut : auto selon le volume)",
    )
    p.add_argument(
        "-e", "--entite", default=None,
        help="Nom de l'entité à ajouter en colonne (cas mono-FEC multi-sociétés)",
    )
    p.add_argument(
        "--mode-cumul", choices=[MODE_CUMUL_ENTITE, MODE_CUMUL_EXERCICE],
        default=MODE_CUMUL_EXERCICE,
        help="Si plusieurs FEC sont fournis : mode de regroupement. "
             "'exercice' (défaut) pour cumul multi-années d'un même client, "
             "'entite' pour cumul multi-sociétés d'un dossier groupe.",
    )
    p.add_argument(
        "--libelles", nargs="+", default=None,
        help="Libellés à associer à chaque FEC en mode cumul (un par fichier, "
             "même ordre). Si omis, déduit du nom de fichier (recherche d'une "
             "année AAAA) ou numéroté FEC_1, FEC_2…",
    )
    p.add_argument(
        "--no-diagnostic", action="store_true",
        help="Désactive l'export du rapport de diagnostic",
    )
    p.add_argument(
        "-q", "--quiet", action="store_true",
        help="Mode silencieux (n'affiche que les erreurs)",
    )
    p.add_argument(
        "--version", action="version", version=f"FEC Normalizer {VERSION}",
    )
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# Vérifications préalables
# ---------------------------------------------------------------------------

def _deduire_libelle(chemin: Path, mode: str, index: int) -> str:
    """
    Devine un libellé pertinent pour un FEC d'après son nom de fichier.

    Recherche d'abord une année à 4 chiffres (1900-2099) dans le nom.
    Sinon, fallback sur "FEC_<n>" pour ne pas bloquer l'utilisateur.
    """
    import re
    nom = chemin.stem
    # On cherche une année à 4 chiffres (1900-2099) délimitée par des non-chiffres
    # ou par les bords de la chaîne. Les délimiteurs courants sont _, -, espace.
    match = re.search(r"(?:^|\D)((?:19|20)\d{2})(?:\D|$)", nom)
    if match:
        return match.group(1)
    return f"FEC_{index + 1}"


def _selectionner_via_dialogue(args: argparse.Namespace) -> None:
    """
    Mode interactif : ouvre une boîte de dialogue Tkinter pour
    sélectionner le FEC source et le dossier de sortie quand ils
    n'ont pas été fournis en ligne de commande.

    Tkinter est inclus dans la bibliothèque standard Python et marche
    de manière identique sur Windows, macOS et Linux.
    """
    # Import paresseux : on ne charge tkinter qu'en mode interactif.
    # Cela évite un crash si jamais l'environnement n'a pas Tk
    # (rare mais possible sur certains serveurs Linux headless).
    from tkinter import Tk, filedialog, messagebox

    racine = Tk()
    racine.withdraw()  # On masque la fenêtre principale, on ne veut que les dialogues
    racine.attributes("-topmost", True)  # Forcer au premier plan sous Windows

    if args.input is None:
        # Sélection multiple : permet de cumuler plusieurs FEC d'un seul coup
        chemins = filedialog.askopenfilenames(
            title="Choisir le ou les FEC à traiter (Cmd/Ctrl pour sélection multiple)",
            filetypes=[
                ("Fichiers FEC", "*.txt *.csv"),
                ("Tous les fichiers", "*.*"),
            ],
        )
        if not chemins:
            messagebox.showinfo(
                "Traitement annulé",
                "Aucun fichier sélectionné. Le programme va se fermer.",
            )
            racine.destroy()
            sys.exit(0)
        args.input = [Path(c) for c in chemins]

    if args.output_dir is None:
        # En cas de cumul, on prend le dossier du premier FEC comme initialdir
        initialdir = str(args.input[0].parent) if args.input else str(Path.home())
        chemin = filedialog.askdirectory(
            title="Choisir le dossier de sortie",
            initialdir=initialdir,
        )
        if not chemin:
            # L'utilisateur a annulé : on prend le dossier du premier FEC source
            args.output_dir = args.input[0].parent
        else:
            args.output_dir = Path(chemin)

    racine.destroy()


def verifier_entrees(args: argparse.Namespace) -> None:
    """Échoue avec un message métier si les entrées sont invalides."""
    # args.input est désormais une liste de Path (1 ou plusieurs FEC)
    for chemin in args.input:
        if not chemin.exists():
            raise FileNotFoundError(
                f"Le fichier source est introuvable : {chemin}"
            )
        if not chemin.is_file():
            raise ValueError(
                f"Le chemin source n'est pas un fichier : {chemin}"
            )

    # Si des libellés sont fournis explicitement, leur nombre doit correspondre
    if args.libelles and len(args.libelles) != len(args.input):
        raise ValueError(
            f"Nombre de libellés ({len(args.libelles)}) différent du nombre de FEC "
            f"({len(args.input)}). Les deux doivent correspondre."
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    if not args.output_dir.is_dir():
        raise ValueError(
            f"Le dossier de sortie n'a pas pu être créé : {args.output_dir}"
        )
    # Test d'écriture effectif : permet de détecter "Permission denied",
    # disque plein, ou dossier accessible en lecture seule
    fichier_test = args.output_dir / ".fec_normalizer_write_test"
    try:
        fichier_test.write_text("ok", encoding="utf-8")
        fichier_test.unlink()
    except OSError as e:
        raise PermissionError(
            f"Impossible d'écrire dans le dossier de sortie {args.output_dir}. "
            f"Vérifiez les permissions ou l'espace disque disponible. "
            f"Détail technique : {e}"
        ) from e


def verifier_colonnes_critiques(df_columns: list[str], chemin_source: Path) -> None:
    """
    Refuse de poursuivre si une colonne critique manque dans le FEC.

    Les colonnes définies dans COLONNES_CRITIQUES sont indispensables au
    pipeline d'enrichissement (calcul de la racine, des découpages temporels,
    du solde). Sans elles, on ne peut produire aucune valeur exploitable.
    """
    manquantes = [c for c in COLONNES_CRITIQUES if c not in df_columns]
    if manquantes:
        raise ValueError(
            f"Le fichier {chemin_source.name} ne respecte pas la norme DGFiP : "
            f"colonne(s) obligatoire(s) absente(s) : {', '.join(manquantes)}. "
            f"Le retraitement ne peut pas se faire sans ces colonnes. "
            f"Vérifiez l'export du FEC depuis votre logiciel comptable."
        )


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

def _resoudre_libelles(args: argparse.Namespace) -> list[str]:
    """Détermine le libellé associé à chaque FEC en mode multi-fichiers."""
    if args.libelles:
        return args.libelles
    return [_deduire_libelle(c, args.mode_cumul, i) for i, c in enumerate(args.input)]


def traiter_fec(args: argparse.Namespace, console: Console) -> dict:
    """
    Exécute le pipeline complet et retourne un dict résumé du traitement.

    Gère deux cas :
    - Un seul FEC : pipeline classique
    - Plusieurs FEC : lecture individuelle, enrichissement avec libellé
      (Entite ou Exercice selon --mode-cumul), puis cumul en un seul DataFrame.
    """
    transformations: list[dict] = []
    multi_fichiers = len(args.input) > 1

    # Choix du préfixe de sortie
    if multi_fichiers:
        nom_base = f"cumul_{len(args.input)}_FEC"
    else:
        nom_base = args.input[0].stem
    chemin_sortie_base = args.output_dir / f"{nom_base}_enrichi"
    chemin_diag_base = args.output_dir / f"{nom_base}_diagnostic"
    durees: dict[str, float] = {}
    tailles: dict[str, str] = {}

    # Mode multi-FEC : libellés à associer
    libelles = _resoudre_libelles(args) if multi_fichiers else [None]

    # --- Étape 1 : lecture et détection format ----------------------------
    titre_etape = (
        f"Lecture des {len(args.input)} FEC..." if multi_fichiers
        else "Lecture du FEC..."
    )
    console.section("1/4", titre_etape)
    t0 = time.perf_counter()
    dfs_individuels: list = []
    total_lignes = 0
    encodages_detectes: set = set()
    separateurs_detectes: set = set()

    for chemin, libelle in zip(args.input, libelles):
        encodage, separateur = detecter_format(chemin)
        df_local = lire_fec(chemin)
        verifier_colonnes_critiques(df_local.columns, chemin)
        encodages_detectes.add(encodage)
        separateurs_detectes.add(separateur)
        dfs_individuels.append((chemin, libelle, df_local))
        total_lignes += df_local.height
        if multi_fichiers:
            console.ligne(
                f"  ▸ {chemin.name}",
                f"{df_local.height:,} lignes (libellé : {libelle})".replace(",", " "),
            )

    durees["lecture"] = time.perf_counter() - t0
    if not multi_fichiers:
        df_unique = dfs_individuels[0][2]
        encodage = list(encodages_detectes)[0]
        separateur = list(separateurs_detectes)[0]
        sep_humain = "tabulation" if separateur == "\t" else f"'{separateur}'"
        console.ligne("Encodage détecté", encodage)
        console.ligne("Séparateur détecté", sep_humain)
        console.ligne("Lignes", f"{df_unique.height:,}".replace(",", " "))
        console.ligne("Colonnes", str(df_unique.width))
        if "EcritureDate" in df_unique.columns:
            console.ligne(
                "Période",
                f"{df_unique['EcritureDate'].min()} → {df_unique['EcritureDate'].max()}",
            )
    else:
        console.ligne("Total lignes", f"{total_lignes:,}".replace(",", " "))
        console.ligne(
            "Encodages détectés",
            ", ".join(encodages_detectes) if encodages_detectes else "—",
        )
    console.ok(f"Lecture en {durees['lecture']:.2f} s")

    if multi_fichiers:
        _journaliser(
            transformations,
            "lecture_fec_multi",
            f"Lecture cumulative de {len(args.input)} FEC "
            f"({total_lignes} lignes au total) "
            f"avec mode de cumul '{args.mode_cumul}'",
        )
    else:
        _journaliser(
            transformations,
            "lecture_fec",
            f"Lecture du fichier {args.input[0].name} "
            f"({df_unique.height} lignes)",
        )

    # --- Étape 2 : enrichissement ----------------------------------------
    console.section("2/4", "Enrichissement...")
    t0 = time.perf_counter()

    if multi_fichiers:
        # Enrichir chaque FEC avec son libellé puis cumuler
        colonne_libelle = "Entite" if args.mode_cumul == MODE_CUMUL_ENTITE else "Exercice"
        dfs_enrichis_par_libelle: dict = {}
        for _, libelle, df_local in dfs_individuels:
            kwargs = {colonne_libelle.lower(): libelle}
            df_local_enrichi = enrichir(df_local, **kwargs)
            dfs_enrichis_par_libelle[libelle] = df_local_enrichi
        df_enrichi = cumuler_fec(dfs_enrichis_par_libelle, colonne_libelle=colonne_libelle)
        df_enrichi = reorganiser_colonnes(df_enrichi)
        console.ligne(
            "Mode de cumul",
            f"{args.mode_cumul} → colonne '{colonne_libelle}'",
        )
        console.ligne("Libellés", ", ".join(libelles))
        _journaliser(
            transformations,
            "cumul_fec",
            f"Cumul de {len(libelles)} FEC sur la colonne '{colonne_libelle}' "
            f"avec libellés : {', '.join(libelles)}",
        )
    else:
        df_enrichi = enrichir(dfs_individuels[0][2], entite=args.entite)
        df_enrichi = reorganiser_colonnes(df_enrichi)
        if args.entite:
            console.ligne("Entité", args.entite)

    durees["enrichissement"] = time.perf_counter() - t0
    nb_avant = sum(df.width for _, _, df in dfs_individuels) // len(dfs_individuels) if dfs_individuels else 0
    nb_nouvelles = df_enrichi.width - nb_avant
    console.ligne(
        "Colonnes ajoutées",
        f"{nb_nouvelles} (Racine, ClasseLib, Mois, Trimestre, Solde, Sens, …)",
    )
    console.ok(f"Enrichissement en {durees['enrichissement']:.2f} s")

    if not multi_fichiers and args.entite:
        _journaliser(
            transformations,
            "ajout_entite",
            f"Ajout de la colonne Entite avec la valeur '{args.entite}'",
        )
    _journaliser(
        transformations,
        "ajout_racine",
        "Extraction du 1er chiffre du compte (classes 1 à 8 du PCG, "
        "'?' pour les comptes non standards)",
    )
    _journaliser(
        transformations,
        "ajout_classe_lib",
        "Libellé normalisé de la classe PCG ('1 - Capitaux', "
        "'2 - Immobilisations', …)",
    )
    _journaliser(
        transformations,
        "ajout_sous_racine",
        "Extraction des 2 premiers caractères du compte ('40', '41', '60', …)",
    )
    _journaliser(
        transformations,
        "ajout_decoupages_temporels",
        "Création des colonnes Annee, Trimestre (AAAA-Tn), Mois (AAAA-MM)",
    )
    _journaliser(
        transformations,
        "calcul_solde",
        "Solde par ligne = Débit - Crédit, arrondi à 2 décimales",
    )
    _journaliser(
        transformations,
        "calcul_sens",
        "Sens de l'écriture : 'D' si Débit > Crédit, 'C' si Crédit > Débit, "
        "'=' sinon",
    )
    _journaliser(
        transformations,
        "reorganisation_colonnes",
        "Mise en tête des colonnes calculées pour faciliter les TCD",
    )

    # --- Étape 3 : export du FEC enrichi ---------------------------------
    console.section("3/4", "Export du FEC enrichi...")
    t0 = time.perf_counter()
    format_force = None if args.format == "auto" else args.format
    chemin_sortie = exporter(df_enrichi, chemin_sortie_base,
                             format_force=format_force)
    durees["export"] = time.perf_counter() - t0
    taille_mo = chemin_sortie.stat().st_size / (1024 * 1024)
    tailles["sortie"] = f"{taille_mo:.2f} Mo"

    if args.format == "auto":
        if df_enrichi.height > LIMITE_EXCEL_MONOFEUILLE:
            raison = (
                f"volume > {LIMITE_EXCEL_MONOFEUILLE:,} lignes — "
                "découpage automatique en plusieurs feuilles"
            ).replace(",", " ")
        elif df_enrichi.height >= SEUIL_AVERTISSEMENT_EXCEL:
            raison = "volume élevé — l'export peut être lent"
        else:
            raison = "volume standard"
        console.ligne(
            "Format choisi", f"{chemin_sortie.suffix[1:]} ({raison})"
        )
    else:
        console.ligne("Format choisi", chemin_sortie.suffix[1:])
    console.ligne("Fichier", f"{chemin_sortie.name} ({taille_mo:.2f} Mo)")
    console.ok(f"Export en {durees['export']:.2f} s")

    _journaliser(
        transformations,
        "export_donnees",
        f"Écriture du FEC enrichi au format "
        f"{chemin_sortie.suffix[1:].upper()} ({chemin_sortie.name})",
    )

    # --- Étape 4 : rapport de diagnostic ---------------------------------
    # En mode multi-FEC, on prend le 1er fichier comme source nominale du rapport,
    # mais on enrichit avec les hashs SHA-256 de tous les fichiers d'entrée.
    rapport = creer_rapport_diagnostic(
        args.input[0],
        transformations=transformations,
        df=df_enrichi,
    )
    if multi_fichiers:
        from parser_fec import calculer_hash_sha256
        rapport["fichiers_sources_cumules"] = [
            {
                "nom": chemin.name,
                "libelle": libelle,
                "sha256": calculer_hash_sha256(chemin),
                "lignes": df_local.height,
            }
            for (chemin, libelle, df_local) in dfs_individuels
        ]
        rapport["mode_cumul"] = args.mode_cumul
    chemins_diag: dict[str, Path] = {}

    if not args.no_diagnostic:
        console.section("4/4", "Rapport de diagnostic...")
        t0 = time.perf_counter()
        chemin_xlsx = exporter_rapport_diagnostic([rapport], chemin_diag_base)
        chemin_json = chemin_diag_base.with_suffix(".json")
        with open(chemin_json, "w", encoding="utf-8") as f:
            json.dump(rapport, f, indent=2, ensure_ascii=False, default=str)
        durees["diagnostic"] = time.perf_counter() - t0
        chemins_diag["xlsx"] = chemin_xlsx
        chemins_diag["json"] = chemin_json
        console.ligne("Fichier Excel", chemin_xlsx.name)
        console.ligne("Fichier JSON", chemin_json.name)
        console.ligne("SHA-256 source", rapport["fichier_sha256"][:16] + "…")
        console.ok(f"Diagnostic en {durees['diagnostic']:.2f} s")
    else:
        console.section("4/4", "Rapport de diagnostic désactivé (--no-diagnostic)")

    return {
        "rapport": rapport,
        "chemin_sortie": chemin_sortie,
        "chemins_diagnostic": chemins_diag,
        "durees": durees,
    }


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    args = parser_arguments(argv)

    # Mode interactif : si --input manque, on ouvre une boîte de dialogue
    # pour sélectionner le FEC (et le dossier de sortie si non précisé).
    # C'est ce qui permet à l'auditeur de double-cliquer sur le .exe.
    if args.input is None:
        try:
            _selectionner_via_dialogue(args)
        except ImportError:
            print(
                "ERREUR : aucun FEC fourni en argument et l'interface graphique "
                "(Tkinter) n'est pas disponible sur ce système.\n"
                "Utilisez : python cli.py --input <fichier.txt> --output-dir <dossier>",
                file=sys.stderr,
            )
            return 2

    # Si --output-dir n'a pas été fourni en mode CLI pur, on retombe sur le défaut historique
    if args.output_dir is None:
        args.output_dir = Path(".")

    console = Console(quiet=args.quiet)

    console.bandeau(f"FEC Normalizer {VERSION} — Traitement en cours")
    console.info("")
    if len(args.input) == 1:
        console.info(f"Source : {args.input[0]}")
    else:
        console.info(f"Sources : {len(args.input)} FEC à cumuler ({args.mode_cumul})")
        for chemin in args.input:
            console.info(f"  ▸ {chemin.name}")
    console.info(f"Sortie : {args.output_dir.resolve()}")

    try:
        verifier_entrees(args)
        t0 = time.perf_counter()
        resultat = traiter_fec(args, console)
        duree_totale = time.perf_counter() - t0
    except FileNotFoundError as e:
        print(f"\nERREUR : {e}", file=sys.stderr)
        return 2
    except PermissionError as e:
        print(f"\nERREUR : {e}", file=sys.stderr)
        return 4
    except ValueError as e:
        print(f"\nERREUR : {e}", file=sys.stderr)
        return 2
    except KeyError as e:
        print(
            f"\nERREUR : colonne attendue absente du FEC : {e}\n"
            "Le fichier ne respecte peut-être pas la norme DGFiP "
            "(18 colonnes obligatoires).",
            file=sys.stderr,
        )
        return 3
    except Exception as e:
        print(f"\nERREUR INATTENDUE : {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    # Bilan final
    console.info("")
    console.bandeau(f"TRAITEMENT TERMINÉ — durée totale : {duree_totale:.2f} s")
    console.info("")
    console.info(f"Fichier enrichi : {resultat['chemin_sortie']}")
    if resultat["chemins_diagnostic"]:
        console.info(f"Diagnostic Excel: {resultat['chemins_diagnostic']['xlsx']}")
        console.info(f"Diagnostic JSON : {resultat['chemins_diagnostic']['json']}")
    console.info("")

    return 0


if __name__ == "__main__":
    sys.exit(main())
