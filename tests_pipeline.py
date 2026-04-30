"""
Suite de tests du pipeline FEC Normalizer.

À lancer avant chaque livraison pour vérifier qu'aucune régression
n'a été introduite. Couvre :

- les 3 profils de volumétrie (TPE, PME, hypermarché) imposés par CLAUDE.md
- les cas pathologiques découverts pendant l'audit
- les invariants métier (équilibre D/C, traçabilité, format des sorties)

Usage :
    python tests_pipeline.py
    python tests_pipeline.py --keep   # conserve le dossier de tests pour inspection
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

import polars as pl

# Imports du projet
from parser_fec import lire_fec, creer_rapport_diagnostic, calculer_hash_sha256
from enrichissement import enrichir, cumuler_fec
from export import (
    SEUIL_EXCEL,
    SEUIL_AVERTISSEMENT_EXCEL,
    LIMITE_EXCEL_MONOFEUILLE,
    _decouper_pour_excel,
)
import generer_fec_test as gen


# Couleurs ANSI pour le terminal (graceful fallback si non supporté)
VERT = "\033[92m"
ROUGE = "\033[91m"
JAUNE = "\033[93m"
GRAS = "\033[1m"
RESET = "\033[0m"


# ---------------------------------------------------------------------------
# Mini-framework de tests (sans dépendance externe)
# ---------------------------------------------------------------------------

class Resultats:
    """Compteur global des tests."""
    def __init__(self):
        self.ok: list[str] = []
        self.ko: list[tuple[str, str]] = []

    def passe(self, nom: str) -> None:
        self.ok.append(nom)
        print(f"  {VERT}✓{RESET} {nom}")

    def echoue(self, nom: str, motif: str) -> None:
        self.ko.append((nom, motif))
        print(f"  {ROUGE}✗ {nom}{RESET}")
        print(f"    {ROUGE}{motif}{RESET}")


def section(titre: str) -> None:
    print(f"\n{GRAS}{titre}{RESET}")


def test(resultats: Resultats, nom: str, callable_) -> None:
    """Exécute un test, attrape les exceptions, log le résultat."""
    try:
        callable_()
        resultats.passe(nom)
    except AssertionError as e:
        resultats.echoue(nom, f"AssertionError : {e}")
    except Exception as e:
        resultats.echoue(nom, f"{type(e).__name__} : {e}\n{traceback.format_exc()}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CHEMIN_CLI = Path(__file__).parent / "cli.py"


def lancer_cli(input_fec: Path, output_dir: Path, *args: str) -> subprocess.CompletedProcess:
    """Lance cli.py en sous-processus et retourne le résultat."""
    cmd = [
        sys.executable, str(CHEMIN_CLI),
        "--input", str(input_fec),
        "--output-dir", str(output_dir),
        "--quiet",
        *args,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


def lire_diagnostic_json(output_dir: Path, nom_base: str) -> dict:
    """Récupère le rapport de diagnostic JSON."""
    chemin = output_dir / f"{nom_base}_diagnostic.json"
    assert chemin.exists(), f"Diagnostic JSON manquant : {chemin}"
    with open(chemin, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Tests par profil de volumétrie (CLAUDE.md)
# ---------------------------------------------------------------------------

def test_profil_tpe(dossier: Path, resultats: Resultats) -> None:
    """Petit FEC type TPE — vérifie la chaîne complète et le format Excel."""
    section("Profil TPE (3 000 lignes — Excel)")
    fec = dossier / "fec_tpe.txt"
    out = dossier / "out_tpe"
    out.mkdir(exist_ok=True)
    gen.generer_fec(3000, 2024, fec, seed=1)

    def _t1():
        r = lancer_cli(fec, out)
        assert r.returncode == 0, f"Exit code {r.returncode}, stderr : {r.stderr}"
    test(resultats, "Pipeline TPE — exit code 0", _t1)

    def _t2():
        assert (out / "fec_tpe_enrichi.xlsx").exists(), "Excel enrichi absent"
    test(resultats, "Pipeline TPE — produit un Excel (sous le seuil)", _t2)

    def _t3():
        diag = lire_diagnostic_json(out, "fec_tpe")
        assert diag["ecart_equilibre"] == 0.0, f"Écart D/C non nul : {diag['ecart_equilibre']}"
    test(resultats, "Pipeline TPE — équilibre Débit/Crédit conservé", _t3)

    def _t4():
        diag = lire_diagnostic_json(out, "fec_tpe")
        assert len(diag["fichier_sha256"]) == 64, "SHA-256 mal formé"
        assert diag["transformations_appliquees"], "Aucune transformation loggée"
    test(resultats, "Pipeline TPE — SHA-256 et transformations loggées", _t4)


def test_profil_pme(dossier: Path, resultats: Resultats) -> None:
    """FEC moyen type PME — toujours sous le seuil Excel."""
    section("Profil PME (50 000 lignes — Excel)")
    fec = dossier / "fec_pme.txt"
    out = dossier / "out_pme"
    out.mkdir(exist_ok=True)
    gen.generer_fec(50000, 2025, fec, seed=2)

    def _t1():
        r = lancer_cli(fec, out)
        assert r.returncode == 0
    test(resultats, "Pipeline PME — exit code 0", _t1)

    def _t2():
        assert (out / "fec_pme_enrichi.xlsx").exists(), "Excel enrichi absent"
    test(resultats, "Pipeline PME — produit un Excel (sous le seuil)", _t2)

    def _t3():
        diag = lire_diagnostic_json(out, "fec_pme")
        assert diag["nb_lignes"] >= 50000, f"Lignes : {diag['nb_lignes']}"
    test(resultats, "Pipeline PME — volume confirmé", _t3)


def test_profil_hyper(dossier: Path, resultats: Resultats) -> None:
    """Gros FEC type hypermarché — bascule auto en Parquet."""
    section("Profil Hypermarché (200 000 lignes — bascule Parquet)")
    fec = dossier / "fec_hyper.txt"
    out = dossier / "out_hyper"
    out.mkdir(exist_ok=True)
    gen.generer_fec(200000, 2025, fec, seed=3)

    def _t1():
        r = lancer_cli(fec, out)
        assert r.returncode == 0
    test(resultats, "Pipeline Hyper — exit code 0", _t1)

    def _t2():
        assert (out / "fec_hyper_enrichi.parquet").exists(), \
            "Parquet absent (bascule auto cassée ?)"
        assert not (out / "fec_hyper_enrichi.xlsx").exists(), \
            "Excel produit alors qu'on attend du Parquet"
    test(resultats, "Pipeline Hyper — bascule auto vers Parquet", _t2)

    def _t3():
        diag = lire_diagnostic_json(out, "fec_hyper")
        assert diag["nb_lignes"] >= 200000
        assert diag["nb_lignes"] >= SEUIL_EXCEL, "Volume sous le seuil — bascule incohérente"
    test(resultats, "Pipeline Hyper — volume au-dessus du seuil 100k", _t3)


# ---------------------------------------------------------------------------
# Tests des cas pathologiques (audit)
# ---------------------------------------------------------------------------

def test_fec_sans_compte_num(dossier: Path, resultats: Resultats) -> None:
    """FEC sans la colonne CompteNum — doit refuser proprement."""
    section("Cas pathologique : FEC sans CompteNum")
    fec = dossier / "fec_sans_compte.txt"
    en_tete = (
        "JournalCode\tJournalLib\tEcritureNum\tEcritureDate\tCompteLib\t"
        "CompAuxNum\tCompAuxLib\tPieceRef\tPieceDate\tEcritureLib\tDebit\t"
        "Credit\tEcritureLet\tDateLet\tValidDate\tMontantdevise\tIdevise"
    )
    ligne = (
        "VTE\tVentes\t1\t20250115\tCompte client\t\t\tFAC1\t20250115\t"
        "Vente test\t100,00\t0,00\t\t\t20250115\t\t"
    )
    fec.write_text(en_tete + "\n" + ligne + "\n", encoding="iso-8859-1")
    out = dossier / "out_pathologique"
    out.mkdir(exist_ok=True)

    def _t1():
        r = lancer_cli(fec, out)
        assert r.returncode == 2, \
            f"Attendu exit code 2 (erreur d'usage), reçu {r.returncode}"
    test(resultats, "FEC sans CompteNum — exit code 2 (erreur d'usage)", _t1)

    def _t2():
        r = lancer_cli(fec, out)
        msg = r.stderr.lower()
        assert "compte" in msg and "obligatoire" in msg, \
            f"Message d'erreur peu explicite : {r.stderr[:300]}"
    test(resultats, "FEC sans CompteNum — message métier clair", _t2)


def test_fec_utf8(dossier: Path, resultats: Resultats) -> None:
    """FEC encodé en UTF-8 (et pas ISO-8859-1) — doit être détecté."""
    section("Cas pathologique : encodage UTF-8")
    fec = dossier / "fec_utf8.txt"
    en_tete = (
        "JournalCode\tJournalLib\tEcritureNum\tEcritureDate\tCompteNum\tCompteLib\t"
        "CompAuxNum\tCompAuxLib\tPieceRef\tPieceDate\tEcritureLib\tDebit\t"
        "Credit\tEcritureLet\tDateLet\tValidDate\tMontantdevise\tIdevise"
    )
    ligne = (
        "VTE\tVentes éàç\t1\t20250115\t411000\tClient générique éàç\t\t\t"
        "FAC1\t20250115\tVente éàç\t100,00\t0,00\t\t\t20250115\t\t"
    )
    fec.write_text(en_tete + "\n" + ligne + "\n", encoding="utf-8")
    out = dossier / "out_utf8"
    out.mkdir(exist_ok=True)

    def _t1():
        r = lancer_cli(fec, out)
        assert r.returncode == 0, f"Exit code {r.returncode} : {r.stderr}"
    test(resultats, "FEC UTF-8 — pipeline OK", _t1)

    def _t2():
        diag = lire_diagnostic_json(out, "fec_utf8")
        assert diag["encodage_detecte"] == "utf-8", \
            f"Encodage détecté : {diag['encodage_detecte']}"
    test(resultats, "FEC UTF-8 — encodage correctement détecté", _t2)


def test_cumul_multi_entites(dossier: Path, resultats: Resultats) -> None:
    """Cumul de 3 FEC pour simuler un dossier groupe (cas Carrefour)."""
    section("Cas multi-entités : cumul de 3 FEC")

    def _t1():
        # Génère 3 FEC distincts en mémoire
        fec_a = dossier / "fec_alpha.txt"
        fec_b = dossier / "fec_beta.txt"
        fec_c = dossier / "fec_gamma.txt"
        gen.generer_fec(2000, 2025, fec_a, seed=10)
        gen.generer_fec(3000, 2025, fec_b, seed=11)
        gen.generer_fec(1500, 2025, fec_c, seed=12)

        df_a = enrichir(lire_fec(fec_a), entite="ALPHA_SAS")
        df_b = enrichir(lire_fec(fec_b), entite="BETA_SARL")
        df_c = enrichir(lire_fec(fec_c), entite="GAMMA_SCI")

        cumul = cumuler_fec({"ALPHA_SAS": df_a, "BETA_SARL": df_b, "GAMMA_SCI": df_c})
        assert cumul.height == df_a.height + df_b.height + df_c.height, \
            "Le cumul ne contient pas la somme des lignes"
        assert "Entite" in cumul.columns, "Colonne Entite absente du cumul"
        assert cumul["Entite"].n_unique() == 3, "Le cumul ne distingue pas les 3 entités"
    test(resultats, "Cumul 3 entités — concaténation correcte", _t1)


def test_idempotence_sha256(dossier: Path, resultats: Resultats) -> None:
    """Le SHA-256 doit être reproductible et discriminant."""
    section("Traçabilité : SHA-256 reproductible et discriminant")
    fec1 = dossier / "fec_id1.txt"
    fec2 = dossier / "fec_id2.txt"
    gen.generer_fec(500, 2025, fec1, seed=42)
    gen.generer_fec(500, 2025, fec2, seed=42)  # Même seed = même fichier
    fec3 = dossier / "fec_id3.txt"
    gen.generer_fec(500, 2025, fec3, seed=99)  # Autre seed

    def _t1():
        h1 = calculer_hash_sha256(fec1)
        h2 = calculer_hash_sha256(fec2)
        assert h1 == h2, f"Idempotence cassée : {h1[:16]}... != {h2[:16]}..."
    test(resultats, "SHA-256 — idempotent (même fichier = même hash)", _t1)

    def _t2():
        h1 = calculer_hash_sha256(fec1)
        h3 = calculer_hash_sha256(fec3)
        assert h1 != h3, "Hash identique sur fichiers différents"
    test(resultats, "SHA-256 — discriminant (fichiers différents = hash différents)", _t2)

    def _t3():
        h1 = calculer_hash_sha256(fec1)
        assert len(h1) == 64 and all(c in "0123456789abcdef" for c in h1), \
            f"Format SHA-256 incorrect : {h1}"
    test(resultats, "SHA-256 — format hexadécimal 64 caractères", _t3)


# ---------------------------------------------------------------------------
# Tests des nouveautés v1.1 (cumul multi-FEC, découpage Excel)
# ---------------------------------------------------------------------------

def test_cumul_multi_annees_cli(dossier: Path, resultats: Resultats) -> None:
    """Cumul de 3 FEC d'années différentes via le CLI complet."""
    section("Cumul multi-années via CLI (3 exercices)")
    fec_2022 = dossier / "fec_2022.txt"
    fec_2023 = dossier / "fec_2023.txt"
    fec_2024 = dossier / "fec_2024.txt"
    gen.generer_fec(2000, 2022, fec_2022, seed=22)
    gen.generer_fec(2500, 2023, fec_2023, seed=23)
    gen.generer_fec(3000, 2024, fec_2024, seed=24)
    out = dossier / "out_multi_annees"
    out.mkdir(exist_ok=True)

    def _t1():
        cmd = [
            sys.executable, str(CHEMIN_CLI),
            "--input", str(fec_2022), str(fec_2023), str(fec_2024),
            "--output-dir", str(out),
            "--mode-cumul", "exercice",
            "--quiet",
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, f"Exit code {r.returncode}, stderr : {r.stderr}"
    test(resultats, "Cumul multi-années — exit code 0", _t1)

    def _t2():
        # Le préfixe de sortie est "cumul_3_FEC"
        assert (out / "cumul_3_FEC_enrichi.xlsx").exists(), \
            "Fichier enrichi cumulé absent"
        assert (out / "cumul_3_FEC_diagnostic.json").exists(), \
            "Diagnostic JSON cumulé absent"
    test(resultats, "Cumul multi-années — fichiers de sortie générés", _t2)

    def _t3():
        with open(out / "cumul_3_FEC_diagnostic.json", encoding="utf-8") as f:
            diag = json.load(f)
        assert diag.get("mode_cumul") == "exercice", "mode_cumul absent ou faux"
        sources = diag.get("fichiers_sources_cumules", [])
        assert len(sources) == 3, f"Attendu 3 sources cumulées, reçu {len(sources)}"
        libelles = {s["libelle"] for s in sources}
        assert libelles == {"2022", "2023", "2024"}, \
            f"Libellés détectés : {libelles}"
    test(resultats, "Cumul multi-années — diagnostic conforme avec 3 hashs SHA-256", _t3)


def test_cumul_multi_entites_cli(dossier: Path, resultats: Resultats) -> None:
    """Cumul multi-entités via le CLI avec libellés explicites."""
    section("Cumul multi-entités via CLI (3 sociétés)")
    fec_a = dossier / "fec_alpha.txt"
    fec_b = dossier / "fec_beta.txt"
    fec_c = dossier / "fec_gamma.txt"
    gen.generer_fec(1000, 2025, fec_a, seed=100)
    gen.generer_fec(1500, 2025, fec_b, seed=101)
    gen.generer_fec(2000, 2025, fec_c, seed=102)
    out = dossier / "out_multi_entites"
    out.mkdir(exist_ok=True)

    def _t1():
        cmd = [
            sys.executable, str(CHEMIN_CLI),
            "--input", str(fec_a), str(fec_b), str(fec_c),
            "--libelles", "SOC_ALPHA", "SOC_BETA", "SOC_GAMMA",
            "--mode-cumul", "entite",
            "--output-dir", str(out),
            "--quiet",
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        assert r.returncode == 0
    test(resultats, "Cumul multi-entités — exit code 0", _t1)

    def _t2():
        with open(out / "cumul_3_FEC_diagnostic.json", encoding="utf-8") as f:
            diag = json.load(f)
        assert diag.get("mode_cumul") == "entite"
        libelles = {s["libelle"] for s in diag["fichiers_sources_cumules"]}
        assert libelles == {"SOC_ALPHA", "SOC_BETA", "SOC_GAMMA"}
    test(resultats, "Cumul multi-entités — libellés respectés", _t2)


def test_decoupage_excel(dossier: Path, resultats: Resultats) -> None:
    """Vérifie la logique de découpage Excel pour les volumes >1M lignes."""
    section("Découpage Excel automatique (>1M lignes)")

    def _t1():
        # Cas métier : 4 exercices × 300k = 1.2M lignes
        df = pl.DataFrame({
            "Exercice": ["2021"]*300_000 + ["2022"]*300_000
                       + ["2023"]*300_000 + ["2024"]*300_000,
            "Debit": [100.0] * 1_200_000,
        })
        partitions = _decouper_pour_excel(df)
        assert len(partitions) == 4, f"Attendu 4 partitions, reçu {len(partitions)}"
        noms = [p[0] for p in partitions]
        assert all(n.startswith("Exercice_") for n in noms), \
            f"Noms inattendus : {noms}"
        total = sum(p[1].height for p in partitions)
        assert total == df.height, "Perte de lignes au découpage"
    test(resultats, "Découpage par Exercice — 4 feuilles, somme conservée", _t1)

    def _t2():
        # Cas sans Exercice : 2.5M lignes → tranches de 900k
        df = pl.DataFrame({"Debit": [100.0] * 2_500_000})
        partitions = _decouper_pour_excel(df)
        assert len(partitions) == 3, f"Attendu 3 tranches, reçu {len(partitions)}"
        assert all(p[0].startswith("Tranche_") for p in partitions)
        total = sum(p[1].height for p in partitions)
        assert total == 2_500_000
    test(resultats, "Découpage par tranches — 3 feuilles, somme conservée", _t2)

    def _t3():
        # Cas pathologique : un seul exercice qui dépasse 1M
        df = pl.DataFrame({
            "Exercice": ["2024"] * 1_500_000,
            "Debit": [100.0] * 1_500_000,
        })
        partitions = _decouper_pour_excel(df)
        assert len(partitions) >= 2, "Devrait subdiviser le gros exercice"
        # Les noms doivent refléter le sous-tranchage de l'exercice
        assert all("2024" in p[0] for p in partitions), \
            f"Noms : {[p[0] for p in partitions]}"
    test(resultats, "Découpage exercice pathologique — sub-tranchage", _t3)


def test_seuils_export(dossier: Path, resultats: Resultats) -> None:
    """Vérifie la cohérence des seuils Excel."""
    section("Seuils export Excel")

    def _t1():
        assert SEUIL_AVERTISSEMENT_EXCEL == 500_000
        assert LIMITE_EXCEL_MONOFEUILLE == 1_000_000
        assert SEUIL_AVERTISSEMENT_EXCEL < LIMITE_EXCEL_MONOFEUILLE
    test(resultats, "Constantes de seuil cohérentes", _t1)


def test_deduction_libelle_annee(dossier: Path, resultats: Resultats) -> None:
    """Vérifie l'auto-détection des années dans les noms de fichiers."""
    section("Auto-détection des libellés d'année")
    # On importe la fonction depuis cli — import paresseux pour pas casser
    # le reste si cli a un souci
    sys.path.insert(0, str(Path(CHEMIN_CLI).parent))
    from cli import _deduire_libelle

    def _t1():
        cas = [
            (Path("fec_2022.txt"), "2022"),
            (Path("/dossier/FEC-2023-clientX.csv"), "2023"),
            (Path("ALPHA_2024_export.txt"), "2024"),
            (Path("export_1999.csv"), "1999"),
        ]
        for chemin, attendu in cas:
            obtenu = _deduire_libelle(chemin, "exercice", 0)
            assert obtenu == attendu, \
                f"{chemin.name} : attendu {attendu!r}, obtenu {obtenu!r}"
    test(resultats, "Détection année dans nom de fichier — 4 cas variés", _t1)

    def _t2():
        # Pas d'année détectable : fallback FEC_<n>
        chemin = Path("dossier_clientX.txt")
        assert _deduire_libelle(chemin, "exercice", 0) == "FEC_1"
        assert _deduire_libelle(chemin, "exercice", 5) == "FEC_6"
    test(resultats, "Pas d'année détectable — fallback FEC_<n>", _t2)


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keep", action="store_true",
        help="Conserver le dossier de tests pour inspection manuelle",
    )
    args = parser.parse_args()

    print(f"{GRAS}=== Suite de tests FEC Normalizer ==={RESET}")
    dossier = Path(tempfile.mkdtemp(prefix="fec_tests_"))
    print(f"  Dossier de tests : {dossier}")
    print(f"  Seuil Excel/Parquet : {SEUIL_EXCEL:,} lignes".replace(",", " "))

    resultats = Resultats()
    debut = time.perf_counter()

    try:
        test_profil_tpe(dossier, resultats)
        test_profil_pme(dossier, resultats)
        test_profil_hyper(dossier, resultats)
        test_fec_sans_compte_num(dossier, resultats)
        test_fec_utf8(dossier, resultats)
        test_cumul_multi_entites(dossier, resultats)
        test_idempotence_sha256(dossier, resultats)
        # Nouveautés v1.1
        test_cumul_multi_annees_cli(dossier, resultats)
        test_cumul_multi_entites_cli(dossier, resultats)
        test_decoupage_excel(dossier, resultats)
        test_seuils_export(dossier, resultats)
        test_deduction_libelle_annee(dossier, resultats)
    finally:
        if args.keep:
            print(f"\n{JAUNE}Dossier de tests conservé : {dossier}{RESET}")
        else:
            shutil.rmtree(dossier, ignore_errors=True)

    duree = time.perf_counter() - debut

    # Bilan
    print(f"\n{GRAS}=== Bilan ==={RESET}")
    print(f"  Tests passés : {VERT}{len(resultats.ok)} OK{RESET}")
    if resultats.ko:
        print(f"  Tests échoués : {ROUGE}{len(resultats.ko)} KO{RESET}")
        print(f"\n{ROUGE}Détail des échecs :{RESET}")
        for nom, motif in resultats.ko:
            print(f"  {ROUGE}✗{RESET} {nom}")
            print(f"    {motif.split(chr(10))[0]}")
    print(f"  Durée totale : {duree:.2f} s")

    return 0 if not resultats.ko else 1


if __name__ == "__main__":
    sys.exit(main())
