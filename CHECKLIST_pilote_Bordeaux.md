# Checklist — Du POC au .exe pilote Audit Bordeaux

**Objectif unique :** un auditeur Bordelais double-clique sur un fichier, choisit son FEC, récupère un Excel propre 30 secondes plus tard. Rien d'autre.

**Hors périmètre (volontairement, on y reviendra plus tard) :** N8N, Wearegenial, Vercel, Infocentre, IA fiscale, lanceurs d'alerte, benchmarks sectoriels, cumul multi-entités. Ces sujets n'existent pas avant que le pilote tourne.

---

## Semaine 1 — Stabiliser le moteur (≈ 2h30 cumulées)

- [x] **1. Sortir le FEC client réel du dossier projet** *(10 min)*
  Déplacer le FEC client (un fichier `<SIREN>FEC<AAAAMMJJ>.txt` situé dans ce dossier) vers un emplacement privé hors du projet partagé. Aucun SIREN ni FEC réel ne doit subsister dans l'arborescence versionnable.

- [x] **2. Nettoyer le code mort dans `enrichissement.py`** *(30 min)*
  Le bloc `if False else` autour du calcul du Trimestre est confus. Le simplifier en : `Année + "-T" + Trimestre`. Tester que le résultat est identique.

- [x] **3. Aligner le seuil Excel/Parquet à 100 000 dans `export.py`** *(5 min)*
  La constante `SEUIL_EXCEL = 1_000_000` est incohérente avec la doctrine du projet (100 000). À remplacer.

- [x] **4. Robustifier `enrichissement.py` contre les `CompteNum` vides ou non standards** *(30 min)*
  Aujourd'hui un compte NULL ou non numérique fait planter le `str.slice`. Ajouter un fallback "? - Inconnu".

- [x] **5. Enrichir le diagnostic** *(1h)*
  Ajouter au rapport de diagnostic : hash SHA-256 du fichier source, date/heure du traitement, utilisateur Windows, liste des transformations appliquées. C'est ce qui rend l'outil défendable en contrôle CNCC.

---

## Semaine 2 — Construire l'interface utilisateur (≈ 3h30 cumulées)

- [x] **6. Écrire `cli.py`** *(1h)*
  Une vingtaine de lignes : `--input` (FEC source), `--output-dir`, `--format` (xlsx/parquet/auto), `--entite` (facultatif). Appelle parser → enrichissement → export.

- [ ] **7. Ajouter une boîte de dialogue Tkinter** *(30 min)*
  Pour que l'auditeur double-clique le `.exe` et obtienne une fenêtre "choisir un fichier", sans passer par la ligne de commande. Tkinter est inclus dans Python, aucune dépendance.

- [x] **8. Tester le tout sur 3 FEC différents** *(1h)*
  Suite de tests automatisée dans `tests_pipeline.py` — 18 tests passés, ~13 s, à relancer avant chaque livraison via `python tests_pipeline.py`.
  Un petit (TPE, < 5 k lignes) que tu fabriques, le tien à 113 k lignes, et un volontairement cassé (mauvais encodage, colonne manquante) pour vérifier les messages d'erreur.

- [x] **9. Rédiger la notice utilisateur — 1 page** *(1h)*
  Trois sections : "Comment l'utiliser en 30 secondes", "Comment lire le diagnostic", "Que faire si ça ne marche pas". Avec 2 captures d'écran.

---

## Semaine 3 — Packaging et test sur poste vierge (≈ 4h cumulées)

- [ ] **10. Premier `.exe` avec PyInstaller** *(1h)*
  Commande type : `pyinstaller --onefile --windowed cli.py`. Vérifier que l'exécutable se lance.

- [ ] **11. Tester le `.exe` sur un poste Windows propre** *(1h)*
  Idéalement une VM ou un poste sans Python installé. C'est là qu'on découvre les vraies erreurs.

- [ ] **12. Régler les problèmes du test précédent** *(1-2h variable)*
  Typiquement : alertes SmartScreen, dépendances manquantes, chemins de sortie. Voir avec Julien si signature de code possible.

- [ ] **13. Préparer le dossier de distribution** *(30 min)*
  Un zip propre contenant : `FEC_Normalizer.exe` + `Notice.pdf` + un FEC d'exemple anonymisé pour démonstration.

---

## Semaine 4 — Pilote Audit Bordeaux (≈ 2h cumulées)

- [ ] **14. Identifier les 5 auditeurs volontaires + caler une démo** *(1h)*
  Mix junior/senior idéalement. 20 minutes de démo en visio, pas plus.

- [ ] **15. Démo collective + distribution du `.exe`** *(1h)*
  Tu montres en live sur ton FEC, tu réponds aux questions, tu envoies le zip à la fin.

- [ ] **16. Canal de retour Teams + suivi au fil de l'eau** *(continu, 15 min/jour)*
  Un channel "Pilote FEC Normalizer" sur Teams. Tu réponds aux questions, tu notes les bugs et les demandes d'évolution dans un fichier dédié — pas dans le code.

---

## Total honnête

≈ **12-15 heures de travail effectif** pour toi, étalées sur 4 semaines. Aucune tâche ne dépasse 2 heures. Si une tâche te bloque plus de 2h, tu m'envoies un message et on regarde ensemble — tu n'es pas censé creuser tout seul un problème technique.

Les tâches **5, 7, 10, 11** sont les plus risquées (techniquement). Le reste est de l'exécution.

---

## Quand tu auras coché les 16 cases

Le pilote tourne, tu as des retours réels, et **là seulement** on rouvre la conversation sur :
- les contrôles métier (TVA, cohérence CA)
- N8N pour les flux automatiques
- Wearegenial et l'agent conversationnel
- l'Infocentre

Pas avant. Promis.
