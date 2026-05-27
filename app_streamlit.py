"""
app_streamlit.py — Interface web FEC Normalizer.

Application web qui réutilise les modules Python du projet (parser_fec,
enrichissement, export). Streamlit gère l'UI et le passage des fichiers,
le moteur de calcul reste identique au CLI.

Principes de fonctionnement :
- Aucune authentification (décision Pôle Innovation, mai 2026)
- Aucun stockage : les FEC sont traités dans un dossier temporaire détruit
  immédiatement après lecture des sorties en mémoire (rétention nulle)
- Pas de logs détaillés des fichiers traités, conformément à la décision DSI

À lancer en local pour développement :
    streamlit run app_streamlit.py
"""

from __future__ import annotations

import base64
import json
import re
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from parser_fec import (
    lire_fec,
    creer_rapport_diagnostic,
    calculer_hash_sha256,
    deduire_siren_depuis_nom,
    chercher_raison_sociale,
)
from enrichissement import (
    enrichir,
    cumuler_fec,
    concatener_fec_enrichis,
    reorganiser_colonnes,
    calculer_resultat_par_groupe,
)
from export import (
    exporter,
    exporter_rapport_diagnostic,
    SEUIL_AVERTISSEMENT_EXCEL,
    LIMITE_EXCEL_MONOFEUILLE,
)


VERSION = "1.4"
COLONNES_CRITIQUES = ("CompteNum", "EcritureDate", "Debit", "Credit")
RACINE_PROJET = Path(__file__).parent
# Logo blanc adapté au header bleu marine — marque Auditoria (pôle audit
# du groupe Extencia) puisque c'est la cible utilisateur de l'outil.
LOGO_PATH = RACINE_PROJET / "logo_auditoria_blanc.svg"
# Manuel utilisateur téléchargeable depuis la page d'accueil.
MANUEL_PATH = RACINE_PROJET / "Manuel utilisateur FEC Normalizer.docx"


# ---------------------------------------------------------------------------
# Configuration de la page
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="FEC Normalizer — Auditoria",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ---------------------------------------------------------------------------
# Style — charte Extencia, polices, ergonomie
# ---------------------------------------------------------------------------

st.markdown(
    """
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        /* ---- Variables charte Extencia ---- */
        :root {
            --ext-bleu:       #152639;
            --ext-bleu-2:     #1d3554;
            --ext-turquoise:  #5EB2A1;
            --ext-turquoise-clair: #E8F5F2;
            --ext-corail:     #E5483A;
            --ext-gris-bleu:  #A9BDCB;
            --ext-orange:     #F6A11B;
            --ext-texte:      #33302D;
            --ext-fond:       #FAFBFC;
            --ext-bord:       #EDF0F3;
        }

        /* ---- Layout général ---- */
        html, body, [class*="css"] {
            font-family: 'Poppins', 'Arial', sans-serif !important;
        }
        .stApp { background-color: var(--ext-fond); }
        .main .block-container {
            max-width: 1080px;
            padding-top: 1.5rem;
            padding-bottom: 4rem;
        }

        /* ---- Bandeau d'en-tête ---- */
        .ext-header {
            background: linear-gradient(135deg, var(--ext-bleu) 0%, var(--ext-bleu-2) 100%);
            color: white;
            padding: 32px 40px;
            border-radius: 16px;
            margin-bottom: 32px;
            box-shadow: 0 8px 28px rgba(21, 38, 57, 0.18);
            display: flex;
            align-items: center;
            gap: 28px;
        }
        .ext-header img { height: 48px; }
        .ext-header h1 {
            color: white !important;
            margin: 0 !important;
            border: none !important;
            padding: 0 !important;
            font-weight: 700;
            font-size: 1.85rem;
            letter-spacing: -0.01em;
        }
        .ext-header p {
            color: rgba(255, 255, 255, 0.7);
            margin: 4px 0 0 0;
            font-size: 0.92rem;
            font-weight: 300;
        }

        /* ---- Encart confidentialité ---- */
        .ext-banner-info {
            background: white;
            border: 1px solid var(--ext-bord);
            border-radius: 12px;
            padding: 14px 20px;
            margin-bottom: 32px;
            color: var(--ext-texte);
            display: flex;
            align-items: center;
            gap: 12px;
            box-shadow: 0 1px 2px rgba(21, 38, 57, 0.03);
        }
        .ext-banner-info .ext-icon {
            background: var(--ext-turquoise-clair);
            color: var(--ext-turquoise);
            width: 36px;
            height: 36px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            flex-shrink: 0;
            font-size: 1.1rem;
        }
        .ext-banner-info b { color: var(--ext-bleu); }

        /* ---- Titres de section : numéro dans pastille ronde ---- */
        h2 {
            color: var(--ext-bleu) !important;
            font-weight: 600 !important;
            font-size: 1.25rem !important;
            margin-top: 2rem !important;
            margin-bottom: 1rem !important;
            border: none !important;
            padding: 0 !important;
            display: flex;
            align-items: center;
            gap: 12px;
            letter-spacing: -0.01em;
        }
        /* Si le titre commence par "1.", "2.", "3." etc., on remplace visuellement */
        h2::first-letter { /* fallback non intrusif */ }

        h3 {
            color: var(--ext-bleu) !important;
            font-weight: 600 !important;
            font-size: 1.05rem !important;
        }

        /* ---- Zone d'upload : design solide, pas de pointillés ---- */
        section[data-testid="stFileUploaderDropzone"] {
            background: white !important;
            border: 1px solid var(--ext-bord) !important;
            border-radius: 12px !important;
            padding: 36px 24px !important;
            transition: all 0.2s ease;
            box-shadow: 0 1px 3px rgba(21, 38, 57, 0.03);
        }
        section[data-testid="stFileUploaderDropzone"]:hover {
            border-color: var(--ext-turquoise) !important;
            background: var(--ext-turquoise-clair) !important;
            box-shadow: 0 2px 12px rgba(94, 178, 161, 0.15);
        }
        /* Bouton "Browse files" interne */
        section[data-testid="stFileUploaderDropzone"] button {
            background: var(--ext-bleu) !important;
            color: white !important;
            border: none !important;
            border-radius: 8px !important;
            font-weight: 500 !important;
            padding: 8px 20px !important;
            transition: all 0.2s ease;
        }
        section[data-testid="stFileUploaderDropzone"] button:hover {
            background: var(--ext-bleu-2) !important;
        }

        /* ---- Boutons ---- */
        .stButton button[kind="primary"] {
            background: var(--ext-turquoise);
            color: white;
            border: none;
            font-weight: 600;
            padding: 12px 32px;
            border-radius: 10px;
            transition: all 0.2s ease;
            box-shadow: 0 2px 8px rgba(94, 178, 161, 0.25);
            font-size: 0.95rem;
        }
        .stButton button[kind="primary"]:hover {
            background: #4d9788;
            transform: translateY(-1px);
            box-shadow: 0 4px 16px rgba(94, 178, 161, 0.4);
        }
        .stButton button[kind="primary"]:disabled {
            background: #D5DCE3;
            color: white;
            box-shadow: none;
            cursor: not-allowed;
            transform: none;
        }
        .stDownloadButton button {
            background: white;
            border: 1px solid var(--ext-bord);
            color: var(--ext-bleu);
            font-weight: 500;
            border-radius: 10px;
            padding: 10px 16px;
            transition: all 0.2s ease;
        }
        .stDownloadButton button:hover {
            border-color: var(--ext-turquoise);
            color: var(--ext-turquoise);
            background: var(--ext-turquoise-clair);
        }

        /* ---- Champs de saisie ---- */
        .stTextInput input, .stTextArea textarea {
            border-radius: 8px !important;
            border-color: var(--ext-bord) !important;
        }
        .stTextInput input:focus, .stTextArea textarea:focus {
            border-color: var(--ext-turquoise) !important;
            box-shadow: 0 0 0 2px rgba(94, 178, 161, 0.15) !important;
        }

        /* ---- Métriques ---- */
        [data-testid="stMetric"] {
            background: white;
            padding: 16px 20px;
            border-radius: 12px;
            border: 1px solid var(--ext-bord);
            box-shadow: 0 1px 2px rgba(21, 38, 57, 0.03);
        }
        [data-testid="stMetric"] label {
            color: var(--ext-gris-bleu);
            font-weight: 500;
            font-size: 0.8rem !important;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }
        [data-testid="stMetric"] [data-testid="stMetricValue"] {
            color: var(--ext-bleu);
            font-weight: 700;
            font-size: 1.4rem !important;
        }

        /* ---- Alertes (success/warning/error/info) ---- */
        div[data-testid="stAlert"] {
            border-radius: 12px;
            border: none;
        }

        /* ---- Footer ---- */
        .ext-footer {
            margin-top: 56px;
            padding-top: 20px;
            border-top: 1px solid var(--ext-bord);
            text-align: center;
            color: var(--ext-gris-bleu);
            font-size: 0.82rem;
            font-weight: 400;
        }
        .ext-footer b { color: var(--ext-turquoise); font-weight: 600; }

        /* ---- Espacement Streamlit ---- */
        .element-container { margin-bottom: 0.6rem; }
        hr { border-color: var(--ext-bord) !important; opacity: 0.6; }
    </style>
    """,
    unsafe_allow_html=True,
)


def _section_titre(numero: int, titre: str) -> None:
    """Titre de section avec numéro dans une pastille ronde turquoise."""
    st.markdown(
        f"""
        <div style="display:flex;align-items:center;gap:14px;margin-top:2rem;margin-bottom:1rem;">
            <div style="
                background: var(--ext-turquoise);
                color: white;
                width: 32px;
                height: 32px;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                font-weight: 700;
                font-size: 0.95rem;
                box-shadow: 0 2px 6px rgba(94, 178, 161, 0.3);
                flex-shrink: 0;
            ">{numero}</div>
            <div style="
                color: var(--ext-bleu);
                font-weight: 600;
                font-size: 1.25rem;
                letter-spacing: -0.01em;
            ">{titre}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Fonctions utilitaires
# ---------------------------------------------------------------------------

def _logo_base64() -> str | None:
    """Charge le logo SVG et le renvoie encodé en base64 pour <img src=...>."""
    if not LOGO_PATH.exists():
        return None
    contenu = LOGO_PATH.read_bytes()
    return base64.b64encode(contenu).decode("ascii")


def _deduire_libelle_annee(nom_fichier: str, index: int) -> str:
    """Devine une année (1900-2099) dans un nom de fichier, fallback FEC_<n>."""
    match = re.search(r"(?:^|\D)((?:19|20)\d{2})(?:\D|$)", nom_fichier)
    if match:
        return match.group(1)
    return f"FEC_{index + 1}"


def _lire_et_valider(chemin: Path) -> tuple:
    df = lire_fec(chemin)
    manquantes = [c for c in COLONNES_CRITIQUES if c not in df.columns]
    return df, manquantes


def _horodatage() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _calculer_resultat_safe(df) -> list[dict]:
    """
    Calcule le résultat par groupe et retourne une liste de dicts sérialisables.
    Renvoie une liste vide si le calcul plante (ex. pas de classes 6/7 dans le FEC).
    """
    try:
        df_res = calculer_resultat_par_groupe(df)
        return df_res.to_dicts()
    except Exception:
        return []


@st.cache_data(show_spinner=False, ttl=3600)
def _raison_sociale_depuis_fichier(nom_fichier: str) -> str:
    """
    Pré-remplissage du champ « Société » à partir du nom de fichier FEC.

    Étapes :
    1. Extraire le SIREN (9 premiers chiffres du nom) via deduire_siren_depuis_nom().
    2. Appeler l'API publique recherche-entreprises (timeout 3s).
    3. Si tout échoue, retourner "" — l'auditeur saisira à la main.

    Le résultat est mis en cache 1h pour éviter de spammer l'API si l'auditeur
    re-dépose le même fichier ou navigue dans la page.

    Retour str (jamais None) pour usage direct comme `value=` d'un text_input.
    """
    siren = deduire_siren_depuis_nom(nom_fichier)
    if not siren:
        return ""
    raison = chercher_raison_sociale(siren)
    return raison or ""


def _format_euros(montant: float) -> str:
    """Formate un montant en euros, style français avec séparateurs."""
    signe = "+" if montant >= 0 else "−"
    abs_val = abs(montant)
    if abs_val >= 1_000_000:
        return f"{signe}{abs_val / 1_000_000:.2f} M€"
    if abs_val >= 1_000:
        return f"{signe}{abs_val:,.0f} €".replace(",", " ")
    return f"{signe}{abs_val:.2f} €"


# ---------------------------------------------------------------------------
# En-tête avec logo
# ---------------------------------------------------------------------------

logo_b64 = _logo_base64()
if logo_b64:
    st.markdown(
        f"""
        <div class="ext-header">
            <img src="data:image/svg+xml;base64,{logo_b64}" alt="Auditoria" />
            <div>
                <h1>FEC Normalizer</h1>
                <p>Outil de retraitement des Fichiers d'Écritures Comptables — Pôle Audit</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.title("FEC Normalizer")
    st.caption(
        "Outil de retraitement des Fichiers d'Écritures Comptables — Auditoria"
    )

st.markdown(
    """
    <div class="ext-banner-info">
        <div class="ext-icon">🔒</div>
        <div>
            <b>Confidentialité</b> — Vos fichiers sont traités en mémoire et supprimés
            immédiatement après téléchargement. Aucun FEC n'est conservé sur le serveur.
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Bouton discret de téléchargement du manuel utilisateur (utile pour les
# nouveaux collaborateurs ou en cas de doute sur un point précis d'usage).
# Placé en haut pour rester accessible avant de commencer un traitement.
if MANUEL_PATH.exists():
    col_manuel, _ = st.columns([1, 3])
    with col_manuel:
        with open(MANUEL_PATH, "rb") as _f_manuel:
            st.download_button(
                "📖 Manuel utilisateur (.docx)",
                _f_manuel.read(),
                file_name=MANUEL_PATH.name,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
                key="dl_manuel",
                help="Guide complet d'utilisation à conserver dans votre dossier "
                     "de référence — version à jour de l'outil.",
            )


# ---------------------------------------------------------------------------
# Section 1 — Upload
# ---------------------------------------------------------------------------

_section_titre(1, "Importer le ou les FEC")

st.caption(
    "Glissez-déposez directement vos fichiers ci-dessous, ou cliquez pour parcourir. "
    "Sélectionnez **un** fichier pour un traitement simple, ou **plusieurs** pour un cumul."
)

uploaded_files = st.file_uploader(
    label="Zone de dépôt",
    label_visibility="collapsed",
    type=["txt", "csv"],
    accept_multiple_files=True,
)

if uploaded_files:
    nb = len(uploaded_files)
    taille_totale_mo = sum(f.size for f in uploaded_files) / (1024 * 1024)
    st.success(
        f"**{nb} fichier{'s' if nb > 1 else ''}** chargé{'s' if nb > 1 else ''} "
        f"({taille_totale_mo:.2f} Mo au total)"
    )
    with st.expander("Détail des fichiers", expanded=False):
        for f in uploaded_files:
            st.write(f"  • `{f.name}` — {f.size / (1024 * 1024):.2f} Mo")


# ---------------------------------------------------------------------------
# Section 2 — Options
# ---------------------------------------------------------------------------

_section_titre(2, "Options")

col_a, col_b = st.columns(2)
with col_a:
    initiales = st.text_input(
        "Vos initiales",
        max_chars=20,
        placeholder="ex. STO",
        help="Apparaîtront dans le champ 'utilisateur' du rapport "
             "de diagnostic (traçabilité audit).",
    )

with col_b:
    # Le champ "entité unique" sert pour le cas mono-FEC où l'auditeur veut
    # quand même tracer la société en colonne Entite (utile pour le futur
    # cumul avec d'autres FEC).
    if uploaded_files and len(uploaded_files) == 1:
        # Pré-remplissage auto depuis l'API recherche-entreprises (SIREN
        # extrait du nom de fichier). Échec silencieux = champ vide.
        raison_auto = _raison_sociale_depuis_fichier(uploaded_files[0].name)
        entite_unique = st.text_input(
            "Société (optionnel)",
            value=raison_auto,
            placeholder="ex. Carrefour Bordeaux",
            help="Auto-rempli depuis le SIREN détecté dans le nom de fichier "
                 "(API publique recherche-entreprises). Modifiable.",
        )
    else:
        entite_unique = ""

# Libellés en mode multi-FEC : société (saisie) + exercice (auto-détecté,
# modifiable). Mode unifié — plus de choix « exercice OU entité », on saisit
# toujours les deux dimensions et le fichier enrichi a toujours les deux
# colonnes Entite et Exercice.
societes: list[str] = []
exercices: list[str] = []
if uploaded_files and len(uploaded_files) > 1:
    from parser_fec import deduire_exercice_depuis_nom

    st.markdown(f"##### Libellés associés à chaque FEC")
    st.caption(
        "**Société** et **exercice** sont pré-remplis automatiquement à partir "
        "du nom de fichier (SIREN → API recherche-entreprises pour la société, "
        "date de clôture pour l'exercice). Vous pouvez ajuster si nécessaire."
    )
    for i, f in enumerate(uploaded_files):
        # Affichage : 1 ligne par FEC avec [nom du fichier] | [Société] | [Exercice]
        st.caption(f"📄 `{f.name}`")
        col_soc, col_ex = st.columns([2, 1])
        with col_soc:
            raison_auto = _raison_sociale_depuis_fichier(f.name)
            societes.append(
                st.text_input(
                    "Société",
                    value=raison_auto,
                    placeholder="ex. Carrefour Bordeaux",
                    key=f"soc_{i}",
                    help="Auto-rempli depuis l'API recherche-entreprises "
                         "si le nom de fichier commence par un SIREN valide."
                    if raison_auto
                    else "Saisie manuelle (SIREN non détecté ou API indisponible).",
                )
            )
        with col_ex:
            exercice_auto = deduire_exercice_depuis_nom(f.name) or ""
            exercices.append(
                st.text_input(
                    "Exercice",
                    value=exercice_auto,
                    placeholder="ex. 2025",
                    key=f"ex_{i}",
                    help="Auto-détecté si le nom suit la convention DGFiP. "
                         "Format : « 2025 » pour exercice civil, « MM/AAAA » sinon.",
                )
            )
        st.markdown(
            "<div style='margin-bottom: 8px;'></div>",
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Section 3 — Lancement
# ---------------------------------------------------------------------------

_section_titre(3, "Traitement")

# En mode multi-FEC, on bloque le bouton tant que toutes les sociétés ne
# sont pas remplies (l'exercice étant auto-détecté, il est rarement vide).
multi_fec = uploaded_files and len(uploaded_files) > 1
societes_manquantes = multi_fec and any(not s.strip() for s in societes)
exercices_manquants = multi_fec and any(not e.strip() for e in exercices)
libelles_manquants = societes_manquantes or exercices_manquants

# Placeholder qui sera remplacé par un bandeau "traitement en cours"
# dès que l'utilisateur clique sur le bouton — pour bien marquer
# visuellement que quelque chose se passe et empêcher tout reclic.
bouton_placeholder = st.empty()
progress_placeholder = st.empty()

bouton_lance = bouton_placeholder.button(
    "🚀  Lancer le traitement",
    disabled=(not uploaded_files) or libelles_manquants,
    type="primary",
    use_container_width=True,
)

if libelles_manquants:
    if societes_manquantes:
        st.caption(
            "⚠️ Renseignez la **société** pour chaque FEC avant de lancer."
        )
    elif exercices_manquants:
        st.caption(
            "⚠️ Renseignez l'**exercice** pour chaque FEC (auto-détection a échoué)."
        )


# Initialisation du conteneur de résultats persistant en session
if "resultats" not in st.session_state:
    st.session_state.resultats = None


if bouton_lance and uploaded_files:
    # On efface les résultats précédents avant de relancer
    st.session_state.resultats = None
    session_dir = Path(tempfile.mkdtemp(prefix="fec_session_"))

    # --- Remplace immédiatement le bouton par un bandeau bien visible ---
    # Plus aucune ambiguïté sur le fait que le traitement est lancé,
    # et plus aucun moyen de cliquer une 2e fois par erreur.
    bouton_placeholder.markdown(
        """
        <div style="
            background: linear-gradient(135deg, var(--ext-turquoise), #4d9788);
            color: white;
            padding: 18px 24px;
            border-radius: 10px;
            text-align: center;
            font-weight: 600;
            font-size: 1.05rem;
            box-shadow: 0 4px 16px rgba(94, 178, 161, 0.35);
            animation: pulse 2s ease-in-out infinite;
        ">
            ⏳ Traitement en cours — ne fermez pas la page
        </div>
        <style>
            @keyframes pulse {
                0%, 100% { opacity: 1; }
                50% { opacity: 0.85; }
            }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Barre de progression visible juste sous le bandeau, mise à jour à
    # chaque grande étape du pipeline.
    progress_bar = progress_placeholder.progress(0, text="Initialisation…")

    try:
        # Sauvegarde temporaire des uploads
        chemins_locaux: list[Path] = []
        for f in uploaded_files:
            chemin = session_dir / f.name
            chemin.write_bytes(f.getbuffer())
            chemins_locaux.append(chemin)

        multi = len(chemins_locaux) > 1
        progress_bar.progress(10, text="Fichiers réceptionnés…")

        with st.status("Traitement en cours...", expanded=True) as status:
            transformations: list[dict] = []

            # Étape 1 — Lecture
            progress_bar.progress(20, text="Lecture du/des FEC…")
            st.write("📥 **Lecture du/des FEC**")
            t0 = time.perf_counter()
            # On stocke (chemin, société, exercice, df) pour chaque FEC.
            # Pour le mono-FEC, société/exercice peuvent venir du seul champ
            # « entite_unique » saisi par l'auditeur (optionnel).
            dfs: list[tuple] = []
            erreur_critique = None

            if multi:
                meta_par_fec = list(zip(chemins_locaux, societes, exercices))
            else:
                meta_par_fec = [
                    (chemins_locaux[0], entite_unique or None, None)
                ]

            for chemin, soc, exo in meta_par_fec:
                df_local, manquantes = _lire_et_valider(chemin)
                if manquantes:
                    erreur_critique = (
                        f"❌ **{chemin.name}** : colonne(s) obligatoire(s) "
                        f"absente(s) selon la norme DGFiP : "
                        f"`{', '.join(manquantes)}`. "
                        f"Vérifiez l'export depuis le logiciel comptable."
                    )
                    break
                dfs.append((chemin, soc, exo, df_local))

            if erreur_critique:
                st.error(erreur_critique)
                status.update(state="error", label="❌ Échec : FEC non conforme")
                st.stop()

            duree_lecture = time.perf_counter() - t0
            total_lignes = sum(d.height for _, _, _, d in dfs)
            st.write(
                f"  ✓ {total_lignes:,} lignes en {duree_lecture:.2f} s"
                .replace(",", " ")
            )
            transformations.append({
                "nom": "lecture_fec",
                "description": f"Lecture de {len(chemins_locaux)} fichier(s) FEC",
                "horodatage": _horodatage(),
            })

            # Étape 2 — Enrichissement
            progress_bar.progress(40, text="Enrichissement des colonnes…")
            st.write("🔧 **Enrichissement des colonnes de travail**")
            t0 = time.perf_counter()

            from enrichissement import concatener_fec_enrichis

            dfs_enrichis: list = []
            for chemin, soc, exo, df_local in dfs:
                df_enrichi = enrichir(
                    df_local,
                    entite=soc or None,
                    exercice=exo or None,
                )
                dfs_enrichis.append(df_enrichi)

            if multi:
                df_final = concatener_fec_enrichis(dfs_enrichis)
                df_final = reorganiser_colonnes(df_final)
                couples = ", ".join(
                    f"({s or '—'} / {e or '—'})" for _, s, e, _ in dfs
                )
                transformations.append({
                    "nom": "cumul_fec",
                    "description": (
                        f"Cumul de {len(dfs)} FEC enrichis avec leurs colonnes "
                        f"Entite/Exercice. Couples (Société/Exercice) : {couples}"
                    ),
                    "horodatage": _horodatage(),
                })
            else:
                df_final = reorganiser_colonnes(dfs_enrichis[0])

            transformations.append({
                "nom": "enrichissement",
                "description": "Ajout des colonnes Racine, ClasseLib, Mois, "
                               "Trimestre, Solde, Sens et autres dimensions d'analyse",
                "horodatage": _horodatage(),
            })
            duree_enr = time.perf_counter() - t0
            st.write(f"  ✓ Enrichissement en {duree_enr:.2f} s")

            if df_final.height > LIMITE_EXCEL_MONOFEUILLE:
                st.warning(
                    f"⚠️ Volume très élevé ({df_final.height:,} lignes) — "
                    f"l'Excel sera découpé automatiquement en plusieurs feuilles."
                    .replace(",", " ")
                )
            elif df_final.height >= SEUIL_AVERTISSEMENT_EXCEL:
                st.warning(
                    f"⚠️ Volume élevé ({df_final.height:,} lignes) — "
                    f"l'export Excel peut prendre 1 à 3 minutes."
                    .replace(",", " ")
                )

            # Étape 3 — Export
            progress_bar.progress(65, text="Export Excel en cours (étape la plus longue)…")
            st.write("📤 **Export Excel**")
            t0 = time.perf_counter()
            nom_base = (
                f"cumul_{len(dfs)}_FEC" if multi
                else chemins_locaux[0].stem
            )
            chemin_sortie = exporter(
                df_final, session_dir / f"{nom_base}_enrichi"
            )
            transformations.append({
                "nom": "export",
                "description": f"Export Excel formaté ({chemin_sortie.name})",
                "horodatage": _horodatage(),
            })
            duree_export = time.perf_counter() - t0
            st.write(f"  ✓ Export en {duree_export:.2f} s")

            # Étape 4 — Diagnostic
            progress_bar.progress(90, text="Génération du rapport de diagnostic…")
            st.write("📋 **Rapport de diagnostic**")
            rapport = creer_rapport_diagnostic(
                chemins_locaux[0],
                transformations=transformations,
                df=df_final,
            )
            rapport["utilisateur"] = initiales if initiales else "non renseigné"

            if multi:
                rapport["mode_cumul"] = "multi-FEC (société + exercice)"
                rapport["fichiers_sources_cumules"] = [
                    {
                        "nom": chemin.name,
                        "societe": soc,
                        "exercice": exo,
                        "sha256": calculer_hash_sha256(chemin),
                        "lignes": df_local.height,
                    }
                    for (chemin, soc, exo, df_local) in dfs
                ]

            chemin_diag_xlsx = exporter_rapport_diagnostic(
                [rapport], session_dir / f"{nom_base}_diagnostic"
            )
            # Note : le JSON de diagnostic n'est plus exposé en téléchargement
            # (décision UX du 26/05/2026, Denis). Le rapport reste disponible
            # via l'expander « Voir le détail du diagnostic » qui affiche les
            # mêmes infos en lecture seule.
            st.write(f"  ✓ SHA-256 source : `{rapport['fichier_sha256'][:16]}…`")
            progress_bar.progress(100, text="✅ Terminé")
            status.update(label="✅ Traitement terminé", state="complete")

        # --- Lecture des bytes en mémoire AVANT suppression du dossier ---
        # On stocke tout dans session_state pour que les résultats persistent
        # entre les re-runs déclenchés par les boutons de téléchargement.
        st.session_state.resultats = {
            "bytes_enrichi": chemin_sortie.read_bytes(),
            "bytes_diag_xlsx": chemin_diag_xlsx.read_bytes(),
            "nom_enrichi": chemin_sortie.name,
            "nom_diag_xlsx": chemin_diag_xlsx.name,
            "rapport": dict(rapport),
            "nb_lignes": df_final.height,
            "nb_colonnes": df_final.width,
            # Résultat estimé par groupe (Entite × Exercice) — utile pour le
            # bloc « Aperçu financier » affiché juste sous les boutons.
            "resultat_par_groupe": _calculer_resultat_safe(df_final),
        }

    finally:
        # Rétention nulle : on supprime immédiatement le dossier sur disque.
        # Les bytes restent en mémoire dans st.session_state, ce qui ne
        # contredit pas la doctrine "le FEC ne reste pas sur le serveur" :
        # session_state vit dans la mémoire vive du worker, est nettoyé à la
        # fin de la session ou quand on relance un traitement.
        shutil.rmtree(session_dir, ignore_errors=True)
        # Nettoyage des placeholders UI (bandeau + barre de progression)
        # pour que l'utilisateur voie les résultats sans bruit visuel.
        bouton_placeholder.empty()
        progress_placeholder.empty()


# ---------------------------------------------------------------------------
# Affichage des résultats (persistant entre les re-runs)
# ---------------------------------------------------------------------------

if st.session_state.resultats:
    res = st.session_state.resultats
    rapport = res["rapport"]

    st.markdown("---")
    st.markdown("### 🎉 Traitement réussi")

    # Indicateurs clés
    col1, col2, col3, col4 = st.columns(4)
    col1.metric(
        "Lignes traitées",
        f"{res['nb_lignes']:,}".replace(",", " "),
    )
    col2.metric("Colonnes", res["nb_colonnes"])
    periode_min = (rapport.get("periode_min") or "—")[:7]
    periode_max = (rapport.get("periode_max") or "—")[:7]
    col3.metric("Période", f"{periode_min} → {periode_max}")
    col4.metric("Équilibre D/C", f"{rapport['ecart_equilibre']} €")

    # ----- Aperçu financier estimé (résultat par groupe) -----
    resultat_par_groupe = res.get("resultat_par_groupe") or []
    if resultat_par_groupe:
        st.markdown("#### 📊 Aperçu financier estimé")
        st.caption(
            "Résultat comptable indicatif calculé sur FEC brut "
            "(**avant écritures de clôture** : à interpréter avec prudence)."
        )
        # On affiche 1 carte par groupe, en colonnes de 2
        nb_cartes = len(resultat_par_groupe)
        nb_par_ligne = min(2, nb_cartes)
        for i in range(0, nb_cartes, nb_par_ligne):
            cols_cartes = st.columns(nb_par_ligne)
            for j, ligne in enumerate(resultat_par_groupe[i:i + nb_par_ligne]):
                resultat = ligne.get("Resultat", 0.0) or 0.0
                produits = ligne.get("Produits", 0.0) or 0.0
                charges = ligne.get("Charges", 0.0) or 0.0
                couleur_res = "#5EB2A1" if resultat >= 0 else "#E5483A"
                # Construit l'en-tête à partir des dimensions disponibles
                entete_parts = []
                if "Entite" in ligne and ligne["Entite"]:
                    entete_parts.append(str(ligne["Entite"]))
                if "Exercice" in ligne and ligne["Exercice"]:
                    entete_parts.append(f"Exercice {ligne['Exercice']}")
                entete = " — ".join(entete_parts) if entete_parts else "Global"

                with cols_cartes[j]:
                    st.markdown(
                        f"""
                        <div style="
                            background: white;
                            border: 1px solid var(--ext-bord);
                            border-left: 4px solid {couleur_res};
                            border-radius: 12px;
                            padding: 16px 20px;
                            margin-bottom: 8px;
                        ">
                            <div style="
                                color: var(--ext-gris-bleu);
                                font-size: 0.85rem;
                                font-weight: 500;
                                margin-bottom: 8px;
                                text-transform: uppercase;
                                letter-spacing: 0.04em;
                            ">{entete}</div>
                            <div style="display: flex; justify-content: space-between; font-size: 0.9rem; color: var(--ext-texte);">
                                <span>Produits (cl. 7)</span>
                                <span style="font-variant-numeric: tabular-nums;">{_format_euros(produits)}</span>
                            </div>
                            <div style="display: flex; justify-content: space-between; font-size: 0.9rem; color: var(--ext-texte);">
                                <span>Charges (cl. 6)</span>
                                <span style="font-variant-numeric: tabular-nums;">{_format_euros(charges)}</span>
                            </div>
                            <hr style="margin: 8px 0; border: none; border-top: 1px solid var(--ext-bord);">
                            <div style="display: flex; justify-content: space-between; font-weight: 700; font-size: 1.05rem;">
                                <span style="color: var(--ext-bleu);">Résultat estimé</span>
                                <span style="color: {couleur_res}; font-variant-numeric: tabular-nums;">{_format_euros(resultat)}</span>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

    st.markdown("#### 📥 Télécharger les résultats")
    st.caption(
        "💡 Le fichier enrichi contient deux conventions de solde au choix : "
        "**Solde** = Débit − Crédit (positif = compte débiteur), "
        "**Montant** = Crédit − Débit (positif = compte créditeur). "
        "Vous prenez celle qui correspond à votre habitude au moment du TCD."
    )
    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            "📊  FEC enrichi",
            res["bytes_enrichi"],
            file_name=res["nom_enrichi"],
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True,
            key="dl_enrichi",
        )
    with col2:
        st.download_button(
            "📋  Diagnostic Excel",
            res["bytes_diag_xlsx"],
            file_name=res["nom_diag_xlsx"],
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="dl_diag_xlsx",
        )

    st.caption(
        "💡 Le diagnostic Excel est à archiver dans le dossier de mission "
        "comme pièce justificative (conformité CNCC)."
    )

    with st.expander("🔍 Voir le détail du diagnostic"):
        st.json(rapport)

    # Bouton de réinitialisation
    st.markdown("")
    if st.button("↺ Nouveau traitement (effacer les résultats)", key="reset"):
        st.session_state.resultats = None
        st.rerun()


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.markdown(
    f"""
    <div class="ext-footer">
        <b>FEC Normalizer v{VERSION}</b>  •  Pôle Innovation Hub Extencia  •
        Conforme norme DGFiP <i>BOI-CF-IOR-60-40-20-10</i>
    </div>
    """,
    unsafe_allow_html=True,
)
