"""
Générateur de FEC synthétique pour les tests.

Produit un FEC totalement factice mais rigoureusement conforme à la norme DGFiP
(BOI-CF-IOR-60-40-20-10) :
- 18 colonnes obligatoires dans l'ordre normé
- Encodage ISO-8859-1
- Séparateur tabulation
- Dates au format AAAAMMJJ
- Décimales avec virgule française
- Équilibre Débit / Crédit garanti par construction

Aucun lien avec un client réel : SIREN factice, libellés génériques, montants tirés au sort.

Usage :
    python generer_fec_test.py --lignes 5000 --sortie petit.txt
    python generer_fec_test.py --lignes 113000 --sortie moyen.txt --annee 2024
    python generer_fec_test.py --lignes 200000 --sortie gros.txt
"""

from __future__ import annotations

import argparse
import random
from datetime import date, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Référentiels (factices mais réalistes)
# ---------------------------------------------------------------------------

JOURNAUX = [
    ("VTE", "Journal des ventes"),
    ("ACH", "Journal des achats"),
    ("BNQ", "Journal de banque"),
    ("CAI", "Journal de caisse"),
    ("OD", "Opérations diverses"),
    ("PAY", "Journal de paie"),
    ("AN", "Journal des à-nouveaux"),
]

COMPTES_VENTE = [
    ("707000", "Ventes de marchandises"),
    ("706000", "Prestations de services"),
    ("708000", "Produits des activités annexes"),
    ("701000", "Ventes de produits finis"),
]

COMPTES_ACHAT = [
    ("607000", "Achats de marchandises"),
    ("606300", "Fournitures d'entretien"),
    ("606400", "Fournitures administratives"),
    ("613500", "Locations mobilières"),
    ("613200", "Locations immobilières"),
    ("621000", "Personnel extérieur"),
    ("622600", "Honoraires"),
    ("623000", "Publicité"),
    ("625100", "Voyages et déplacements"),
    ("626000", "Frais postaux et télécoms"),
    ("627000", "Services bancaires"),
    ("641000", "Rémunérations du personnel"),
    ("645000", "Charges de sécurité sociale"),
]

COMPTES_TIERS_CLIENTS = [f"411{i:06d}" for i in range(1, 200)]
COMPTES_TIERS_FOURNISSEURS = [f"401{i:06d}" for i in range(1, 150)]

COMPTES_TVA_COLLECTEE = ["445710", "445711"]
COMPTES_TVA_DEDUCTIBLE = ["445660", "445661", "445662"]
COMPTES_BANQUE = ["512100", "512200"]
COMPTES_CAISSE = ["530000"]

LIBELLES_VENTE = [
    "Facture client {num}",
    "Vente marchandises - dossier {num}",
    "Prestation - mission {num}",
    "Facture annuelle {num}",
]
LIBELLES_ACHAT = [
    "Facture fournisseur {num}",
    "Achat fournitures {num}",
    "Honoraires {num}",
    "Loyer mensuel {num}",
    "Frais de déplacement {num}",
    "Abonnement service {num}",
]
LIBELLES_BANQUE = [
    "Virement {num}",
    "Prélèvement {num}",
    "Remise chèque {num}",
    "Frais bancaires {num}",
]


# ---------------------------------------------------------------------------
# En-tête FEC (norme DGFiP)
# ---------------------------------------------------------------------------

COLONNES_FEC = [
    "JournalCode", "JournalLib", "EcritureNum", "EcritureDate",
    "CompteNum", "CompteLib", "CompAuxNum", "CompAuxLib",
    "PieceRef", "PieceDate", "EcritureLib", "Debit", "Credit",
    "EcritureLet", "DateLet", "ValidDate", "Montantdevise", "Idevise",
]


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------

def fmt_date(d: date) -> str:
    """Format AAAAMMJJ exigé par la norme DGFiP."""
    return d.strftime("%Y%m%d")


def fmt_montant(montant: float) -> str:
    """Décimale avec virgule, 2 décimales, sans séparateur de milliers."""
    return f"{montant:.2f}".replace(".", ",")


def date_aleatoire(annee: int) -> date:
    debut = date(annee, 1, 1)
    fin = date(annee, 12, 31)
    delta = (fin - debut).days
    return debut + timedelta(days=random.randint(0, delta))


def montant_aleatoire(min_eur=10, max_eur=50000) -> float:
    return round(random.uniform(min_eur, max_eur), 2)


# ---------------------------------------------------------------------------
# Génération d'écritures équilibrées par type
# ---------------------------------------------------------------------------

def ecriture_vente(num_ecriture: int, journal: tuple[str, str], annee: int) -> list[list[str]]:
    """Vente : Client (D) = Produit (C) + TVA collectée (C)."""
    code, lib = journal
    dt = date_aleatoire(annee)
    montant_ht = montant_aleatoire(50, 8000)
    tva = round(montant_ht * 0.20, 2)
    ttc = round(montant_ht + tva, 2)

    client = random.choice(COMPTES_TIERS_CLIENTS)
    cpt_vente, lib_vente = random.choice(COMPTES_VENTE)
    cpt_tva = random.choice(COMPTES_TVA_COLLECTEE)
    piece_ref = f"FAC{num_ecriture:06d}"
    libelle = random.choice(LIBELLES_VENTE).format(num=num_ecriture)

    lignes = [
        [code, lib, str(num_ecriture), fmt_date(dt), client, "Compte client",
         "", "", piece_ref, fmt_date(dt), libelle, fmt_montant(ttc), fmt_montant(0),
         "", "", fmt_date(dt), "", ""],
        [code, lib, str(num_ecriture), fmt_date(dt), cpt_vente, lib_vente,
         "", "", piece_ref, fmt_date(dt), libelle, fmt_montant(0), fmt_montant(montant_ht),
         "", "", fmt_date(dt), "", ""],
        [code, lib, str(num_ecriture), fmt_date(dt), cpt_tva, "TVA collectée 20%",
         "", "", piece_ref, fmt_date(dt), libelle, fmt_montant(0), fmt_montant(tva),
         "", "", fmt_date(dt), "", ""],
    ]
    return lignes


def ecriture_achat(num_ecriture: int, journal: tuple[str, str], annee: int) -> list[list[str]]:
    """Achat : Charge (D) + TVA déductible (D) = Fournisseur (C)."""
    code, lib = journal
    dt = date_aleatoire(annee)
    montant_ht = montant_aleatoire(20, 5000)
    tva = round(montant_ht * 0.20, 2)
    ttc = round(montant_ht + tva, 2)

    fournisseur = random.choice(COMPTES_TIERS_FOURNISSEURS)
    cpt_achat, lib_achat = random.choice(COMPTES_ACHAT)
    cpt_tva = random.choice(COMPTES_TVA_DEDUCTIBLE)
    piece_ref = f"FAC{num_ecriture:06d}"
    libelle = random.choice(LIBELLES_ACHAT).format(num=num_ecriture)

    lignes = [
        [code, lib, str(num_ecriture), fmt_date(dt), cpt_achat, lib_achat,
         "", "", piece_ref, fmt_date(dt), libelle, fmt_montant(montant_ht), fmt_montant(0),
         "", "", fmt_date(dt), "", ""],
        [code, lib, str(num_ecriture), fmt_date(dt), cpt_tva, "TVA déductible 20%",
         "", "", piece_ref, fmt_date(dt), libelle, fmt_montant(tva), fmt_montant(0),
         "", "", fmt_date(dt), "", ""],
        [code, lib, str(num_ecriture), fmt_date(dt), fournisseur, "Compte fournisseur",
         "", "", piece_ref, fmt_date(dt), libelle, fmt_montant(0), fmt_montant(ttc),
         "", "", fmt_date(dt), "", ""],
    ]
    return lignes


def ecriture_banque(num_ecriture: int, journal: tuple[str, str], annee: int) -> list[list[str]]:
    """Banque : Banque (D ou C) <=> Tiers ou charge."""
    code, lib = journal
    dt = date_aleatoire(annee)
    montant = montant_aleatoire(50, 15000)
    cpt_banque = random.choice(COMPTES_BANQUE)
    piece_ref = f"BNQ{num_ecriture:06d}"
    libelle = random.choice(LIBELLES_BANQUE).format(num=num_ecriture)

    # Encaissement client (50%) ou règlement fournisseur (50%)
    if random.random() < 0.5:
        client = random.choice(COMPTES_TIERS_CLIENTS)
        return [
            [code, lib, str(num_ecriture), fmt_date(dt), cpt_banque, "Compte courant",
             "", "", piece_ref, fmt_date(dt), libelle, fmt_montant(montant), fmt_montant(0),
             "", "", fmt_date(dt), "", ""],
            [code, lib, str(num_ecriture), fmt_date(dt), client, "Compte client",
             "", "", piece_ref, fmt_date(dt), libelle, fmt_montant(0), fmt_montant(montant),
             "", "", fmt_date(dt), "", ""],
        ]
    else:
        fournisseur = random.choice(COMPTES_TIERS_FOURNISSEURS)
        return [
            [code, lib, str(num_ecriture), fmt_date(dt), fournisseur, "Compte fournisseur",
             "", "", piece_ref, fmt_date(dt), libelle, fmt_montant(montant), fmt_montant(0),
             "", "", fmt_date(dt), "", ""],
            [code, lib, str(num_ecriture), fmt_date(dt), cpt_banque, "Compte courant",
             "", "", piece_ref, fmt_date(dt), libelle, fmt_montant(0), fmt_montant(montant),
             "", "", fmt_date(dt), "", ""],
        ]


# ---------------------------------------------------------------------------
# Boucle principale
# ---------------------------------------------------------------------------

GENERATEURS = [
    ("VTE", ecriture_vente, 0.40),    # 40% ventes
    ("ACH", ecriture_achat, 0.35),    # 35% achats
    ("BNQ", ecriture_banque, 0.25),   # 25% banque
]


def generer_fec(nb_lignes_cible: int, annee: int, chemin_sortie: Path,
                seed: int | None = None) -> dict:
    """Génère un FEC synthétique."""
    if seed is not None:
        random.seed(seed)

    journaux_par_code = {code: (code, lib) for code, lib in JOURNAUX}
    lignes_finales: list[list[str]] = []
    num_ecriture = 1
    total_debit = 0.0
    total_credit = 0.0

    while len(lignes_finales) < nb_lignes_cible:
        # Tirage du type d'écriture selon les probabilités
        tirage = random.random()
        cum = 0
        choix = GENERATEURS[0]
        for code, fn, proba in GENERATEURS:
            cum += proba
            if tirage <= cum:
                choix = (code, fn, proba)
                break

        code, fn, _ = choix
        lignes = fn(num_ecriture, journaux_par_code[code], annee)
        lignes_finales.extend(lignes)

        for ligne in lignes:
            total_debit += float(ligne[11].replace(",", "."))
            total_credit += float(ligne[12].replace(",", "."))

        num_ecriture += 1

    # On NE tronque PAS au milieu d'une écriture pour préserver l'équilibre D/C.
    # Le nombre de lignes final sera donc ≥ nb_lignes_cible (écart ≤ 3 lignes).

    # Écriture du fichier (encodage ISO-8859-1, séparateur tabulation)
    chemin_sortie.parent.mkdir(parents=True, exist_ok=True)
    with open(chemin_sortie, "w", encoding="iso-8859-1", newline="") as f:
        f.write("\t".join(COLONNES_FEC) + "\n")
        for ligne in lignes_finales:
            f.write("\t".join(ligne) + "\n")

    return {
        "fichier": str(chemin_sortie),
        "lignes": len(lignes_finales),
        "ecritures": num_ecriture - 1,
        "annee": annee,
        "total_debit": round(total_debit, 2),
        "total_credit": round(total_credit, 2),
        "ecart_equilibre": round(total_debit - total_credit, 2),
        "taille_mo": round(chemin_sortie.stat().st_size / (1024 * 1024), 2),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="Génère un FEC synthétique conforme DGFiP.")
    p.add_argument("--lignes", type=int, default=5000,
                   help="Nombre de lignes à générer (défaut : 5000)")
    p.add_argument("--annee", type=int, default=2025,
                   help="Année des écritures (défaut : 2025)")
    p.add_argument("--sortie", type=str, default="fec_test.txt",
                   help="Chemin du fichier de sortie (défaut : fec_test.txt)")
    p.add_argument("--seed", type=int, default=None,
                   help="Graine aléatoire pour reproductibilité (optionnel)")
    args = p.parse_args()

    chemin = Path(args.sortie)
    print(f"Génération d'un FEC synthétique de ~{args.lignes:,} lignes...")
    diag = generer_fec(args.lignes, args.annee, chemin, args.seed)

    print(f"\n[OK] Fichier généré : {diag['fichier']}")
    print(f"  Lignes      : {diag['lignes']:,}")
    print(f"  Écritures   : {diag['ecritures']:,}")
    print(f"  Année       : {diag['annee']}")
    print(f"  Taille      : {diag['taille_mo']} Mo")
    print(f"  Total Débit : {diag['total_debit']:,.2f} €")
    print(f"  Total Crédit: {diag['total_credit']:,.2f} €")
    print(f"  Écart D/C   : {diag['ecart_equilibre']:,.2f} €")


if __name__ == "__main__":
    main()
