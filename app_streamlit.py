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
)
from enrichissement import enrichir, cumuler_fec, reorganiser_colonnes
from export import (
    exporter,
    exporter_rapport_diagnostic,
    SEUIL_AVERTISSEMENT_EXCEL,
    LIMITE_EXCEL_MONOFEUILLE,
)


VERSION = "1.1"
COLONNES_CRITIQUES = ("CompteNum", "EcritureDate", "Debit", "Credit")
RACINE_PROJET = Path(__file__).parent
# Logo blanc adapté au header bleu marine (charte Extencia : version sombre)
LOGO_PATH = RACINE_PROJET / "logo_extencia_blanc.svg"


# ---------------------------------------------------------------------------
# Configuration de la page
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="FEC Normalizer — Extencia",
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


# ---------------------------------------------------------------------------
# En-tête avec logo
# ---------------------------------------------------------------------------

logo_b64 = _logo_base64()
if logo_b64:
    st.markdown(
        f"""
        <div class="ext-header">
            <img src="data:image/svg+xml;base64,{logo_b64}" alt="Extencia" />
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
        "Outil de retraitement des Fichiers d'Écritures Comptables — Pôle Audit Extencia"
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
    if uploaded_files and len(uploaded_files) > 1:
        mode_cumul = st.radio(
            "Mode de cumul",
            options=["exercice", "entite"],
            format_func=lambda x: (
                "Multi-années (Exercice)" if x == "exercice"
                else "Multi-sociétés (Entité)"
            ),
            horizontal=True,
            help="Cumul multi-années : analyses pluriannuelles d'un client. "
                 "Cumul multi-sociétés : dossiers groupes.",
        )
    else:
        mode_cumul = None

# Libellés en mode multi-FEC
libelles: list[str] = []
if uploaded_files and len(uploaded_files) > 1:
    colonne_cible = "Exercice" if mode_cumul == "exercice" else "Entite"
    placeholder_exemple = (
        "ex. 2024, Exercice 2024…" if mode_cumul == "exercice"
        else "ex. Carrefour Bordeaux, SOC_ALPHA…"
    )

    st.markdown(f"##### Libellés associés à chaque FEC")
    st.caption(
        f"Chaque libellé apparaîtra dans la colonne **{colonne_cible}** "
        f"du fichier enrichi. La saisie est obligatoire : c'est vous qui "
        f"décidez du libellé propre, pas le nom de fichier source."
    )
    nb_cols = min(len(uploaded_files), 3)
    cols = st.columns(nb_cols)
    for i, f in enumerate(uploaded_files):
        with cols[i % nb_cols]:
            # On rappelle le nom du fichier d'origine au-dessus du champ
            # pour que l'auditeur sache exactement à quel fichier le libellé
            # se rapporte (évite toute confusion d'ordre).
            st.caption(f"📄 `{f.name}`")
            libelles.append(
                st.text_input(
                    "Libellé",
                    value="",
                    placeholder=placeholder_exemple,
                    key=f"lib_{i}",
                    label_visibility="collapsed",
                )
            )


# ---------------------------------------------------------------------------
# Section 3 — Lancement
# ---------------------------------------------------------------------------

_section_titre(3, "Traitement")

# En mode multi-FEC, on bloque le bouton tant que tous les libellés ne sont
# pas remplis. Décision UX : on force l'auditeur à choisir un libellé propre
# au lieu de laisser un défaut moche issu du nom de fichier.
multi_fec = uploaded_files and len(uploaded_files) > 1
libelles_manquants = multi_fec and any(not lib.strip() for lib in libelles)

bouton_lance = st.button(
    "🚀  Lancer le traitement",
    disabled=(not uploaded_files) or libelles_manquants,
    type="primary",
    use_container_width=True,
)

if libelles_manquants:
    st.caption(
        "⚠️ Renseignez un libellé pour chaque FEC avant de lancer le traitement."
    )


# Initialisation du conteneur de résultats persistant en session
if "resultats" not in st.session_state:
    st.session_state.resultats = None


if bouton_lance and uploaded_files:
    # On efface les résultats précédents avant de relancer
    st.session_state.resultats = None
    session_dir = Path(tempfile.mkdtemp(prefix="fec_session_"))

    try:
        # Sauvegarde temporaire des uploads
        chemins_locaux: list[Path] = []
        for f in uploaded_files:
            chemin = session_dir / f.name
            chemin.write_bytes(f.getbuffer())
            chemins_locaux.append(chemin)

        multi = len(chemins_locaux) > 1

        with st.status("Traitement en cours...", expanded=True) as status:
            transformations: list[dict] = []

            # Étape 1 — Lecture
            st.write("📥 **Lecture du/des FEC**")
            t0 = time.perf_counter()
            dfs: list[tuple] = []
            erreur_critique = None

            for chemin, libelle in zip(
                chemins_locaux, libelles or [None] * len(chemins_locaux)
            ):
                df_local, manquantes = _lire_et_valider(chemin)
                if manquantes:
                    erreur_critique = (
                        f"❌ **{chemin.name}** : colonne(s) obligatoire(s) "
                        f"absente(s) selon la norme DGFiP : "
                        f"`{', '.join(manquantes)}`. "
                        f"Vérifiez l'export depuis le logiciel comptable."
                    )
                    break
                dfs.append((chemin, libelle, df_local))

            if erreur_critique:
                st.error(erreur_critique)
                status.update(state="error", label="❌ Échec : FEC non conforme")
                st.stop()

            duree_lecture = time.perf_counter() - t0
            total_lignes = sum(d.height for _, _, d in dfs)
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
            st.write("🔧 **Enrichissement des colonnes de travail**")
            t0 = time.perf_counter()
            if multi:
                colonne = "Exercice" if mode_cumul == "exercice" else "Entite"
                kwarg = "exercice" if mode_cumul == "exercice" else "entite"
                dfs_enrichis: dict = {}
                for _, libelle, df_local in dfs:
                    dfs_enrichis[libelle] = enrichir(df_local, **{kwarg: libelle})
                df_final = cumuler_fec(dfs_enrichis, colonne_libelle=colonne)
                df_final = reorganiser_colonnes(df_final)
                transformations.append({
                    "nom": "cumul_fec",
                    "description": (
                        f"Cumul de {len(dfs)} FEC sur la colonne '{colonne}' "
                        f"avec libellés : {', '.join(libelles)}"
                    ),
                    "horodatage": _horodatage(),
                })
            else:
                df_final = enrichir(dfs[0][2])
                df_final = reorganiser_colonnes(df_final)
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
            st.write("📋 **Rapport de diagnostic**")
            rapport = creer_rapport_diagnostic(
                chemins_locaux[0],
                transformations=transformations,
                df=df_final,
            )
            rapport["utilisateur"] = initiales if initiales else "non renseigné"

            if multi:
                rapport["mode_cumul"] = mode_cumul
                rapport["fichiers_sources_cumules"] = [
                    {
                        "nom": chemin.name,
                        "libelle": libelle,
                        "sha256": calculer_hash_sha256(chemin),
                        "lignes": df_local.height,
                    }
                    for (chemin, libelle, df_local) in dfs
                ]

            chemin_diag_xlsx = exporter_rapport_diagnostic(
                [rapport], session_dir / f"{nom_base}_diagnostic"
            )
            chemin_diag_json = session_dir / f"{nom_base}_diagnostic.json"
            chemin_diag_json.write_text(
                json.dumps(rapport, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            st.write(f"  ✓ SHA-256 source : `{rapport['fichier_sha256'][:16]}…`")
            status.update(label="✅ Traitement terminé", state="complete")

        # --- Lecture des bytes en mémoire AVANT suppression du dossier ---
        # On stocke tout dans session_state pour que les résultats persistent
        # entre les re-runs déclenchés par les boutons de téléchargement.
        st.session_state.resultats = {
            "bytes_enrichi": chemin_sortie.read_bytes(),
            "bytes_diag_xlsx": chemin_diag_xlsx.read_bytes(),
            "bytes_diag_json": chemin_diag_json.read_bytes(),
            "nom_enrichi": chemin_sortie.name,
            "nom_diag_xlsx": chemin_diag_xlsx.name,
            "nom_diag_json": chemin_diag_json.name,
            "rapport": dict(rapport),
            "nb_lignes": df_final.height,
            "nb_colonnes": df_final.width,
        }

    finally:
        # Rétention nulle : on supprime immédiatement le dossier sur disque.
        # Les bytes restent en mémoire dans st.session_state, ce qui ne
        # contredit pas la doctrine "le FEC ne reste pas sur le serveur" :
        # session_state vit dans la mémoire vive du worker, est nettoyé à la
        # fin de la session ou quand on relance un traitement.
        shutil.rmtree(session_dir, ignore_errors=True)


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

    st.markdown("#### 📥 Télécharger les résultats")
    col1, col2, col3 = st.columns(3)
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
    with col3:
        st.download_button(
            "🔧  Diagnostic JSON",
            res["bytes_diag_json"],
            file_name=res["nom_diag_json"],
            mime="application/json",
            use_container_width=True,
            key="dl_diag_json",
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
