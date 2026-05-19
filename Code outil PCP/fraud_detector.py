"""
=============================================================================
Module : fraud_detector.py
Description : Détection de fraude documentaire (faux bulletins, relevés falsifiés).
Auteur : Équipe Technique PCP | Version : 1.0.0
=============================================================================
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Tuple
from enum import Enum
import re
import hashlib


class TypeDocument(str, Enum):
    BULLETIN_SALAIRE = "bulletin_salaire"
    CNI              = "cni"
    RELEVE_BANCAIRE  = "releve_bancaire"
    RELEVE_MOMO      = "releve_mobile_money"
    CONTRAT_TRAVAIL  = "contrat_travail"


class RisqueFraude(str, Enum):
    FAIBLE  = "FAIBLE"
    MODERE  = "MODÉRÉ"
    ELEVE   = "ÉLEVÉ"
    BLOQUE  = "BLOQUÉ"


@dataclass
class DocumentAnalyse:
    """Résultat de l'analyse d'un document."""
    type_document: TypeDocument
    donnees_extraites: Dict[str, str]
    score_confiance: float          # 0.0 à 1.0
    risque_fraude: RisqueFraude
    anomalies: List[str]
    recommandation: str
    hash_document: str              # pour déduplication


@dataclass
class ProfilDocumentaire:
    """Ensemble des documents d'un dossier."""
    contrat_id: str
    documents: List[DocumentAnalyse]
    coherence_globale: float        # 0.0 à 1.0
    decision_fraude: str
    flags: List[str]


# ─── Règles de détection ────────────────────────────────────────────────────

def analyser_coherence_revenus(
    revenu_declare: float,
    revenu_bulletin: float,
    solde_momo_moyen: float,
    tolerance: float = 0.05,
) -> Tuple[bool, str]:
    """
    Vérifie la cohérence entre revenus déclarés, bulletin et MoMo.

    Paramètres
    ----------
    revenu_declare : float
        Revenu déclaré par le client (XOF).
    revenu_bulletin : float
        Revenu extrait du bulletin de salaire par OCR (XOF).
    solde_momo_moyen : float
        Solde moyen Mobile Money sur 3 mois (XOF).
    tolerance : float
        Écart maximum acceptable entre déclaré et bulletin (5 %).

    Retourne
    --------
    Tuple[bool, str] : (est_coherent, message_explication)
    """
    ecart_bulletin = abs(revenu_declare - revenu_bulletin) / max(revenu_declare, 1)

    if ecart_bulletin > tolerance:
        return False, (
            f"Écart bulletin/déclaré : {ecart_bulletin * 100:.1f} % "
            f"(max toléré : {tolerance * 100:.0f} %). "
            f"Déclaré={revenu_declare:,.0f} XOF / Bulletin={revenu_bulletin:,.0f} XOF."
        )

    # Ratio MoMo / Revenu : un salarié formel devrait avoir un ratio cohérent
    ratio_momo = solde_momo_moyen / max(revenu_declare, 1)
    if ratio_momo > 3.0:
        return False, (
            f"Solde MoMo anormalement élevé par rapport au salaire "
            f"(ratio {ratio_momo:.1f}×). Possible fraude ou revenus non déclarés."
        )
    if ratio_momo < 0.05 and revenu_declare > 150_000:
        return False, (
            f"Solde MoMo très faible pour un salaire de {revenu_declare:,.0f} XOF "
            f"(ratio {ratio_momo:.1f}×). Incohérence possible."
        )

    return True, "Cohérence revenus validée."


def detecter_anomalies_bulletin(donnees_ocr: Dict[str, str]) -> List[str]:
    """
    Détecte les anomalies typiques des bulletins falsifiés.

    Tests appliqués :
    - Présence des champs obligatoires
    - Format numéro CNSS valide
    - Cohérence date / période
    - Présence du cachet employeur (métadonnée OCR)
    - Format montant cohérent

    Paramètres
    ----------
    donnees_ocr : Dict[str, str]
        Données extraites par OCR du bulletin de salaire.

    Retourne
    --------
    List[str] : Liste des anomalies détectées.
    """
    anomalies = []
    champs_obligatoires = ["nom_employe", "nom_employeur", "revenu_net", "periode", "cnss"]

    for champ in champs_obligatoires:
        if champ not in donnees_ocr or not donnees_ocr[champ].strip():
            anomalies.append(f"Champ manquant ou vide : '{champ}'.")

    # Validation format CNSS Bénin : BJ-CNSS-XXXXXX
    cnss = donnees_ocr.get("cnss", "")
    if cnss and not re.match(r"^(BJ-CNSS-\d{6,8}|\d{8,12})$", cnss.strip()):
        anomalies.append(f"Format N° CNSS suspect : '{cnss}'. Format attendu : BJ-CNSS-XXXXXX.")

    # Montant cohérent (pas de caractères alphabétiques parasites)
    revenu_str = donnees_ocr.get("revenu_net", "0").replace(" ", "").replace(",", "")
    try:
        revenu = float(revenu_str)
        if revenu < 50_000 or revenu > 5_000_000:
            anomalies.append(f"Montant revenu hors plage normale : {revenu:,.0f} XOF.")
    except ValueError:
        anomalies.append(f"Montant revenu illisible ou corrompu : '{revenu_str}'.")

    # Cachet employeur
    if not donnees_ocr.get("cachet_detecte", "").lower() in ["oui", "true", "yes", "1"]:
        anomalies.append("Cachet employeur non détecté par OCR (risque de falsification).")

    return anomalies


def calculer_score_confiance_document(nb_anomalies: int, nb_champs_ok: int) -> float:
    """
    Score de confiance d'un document (0 = suspect, 1 = parfait).

    Formule : confiance = champs_ok / total × pénalité_anomalies
    """
    total_champs = nb_champs_ok + nb_anomalies
    if total_champs == 0:
        return 0.0
    base = nb_champs_ok / total_champs
    penalite = max(0.0, 1 - nb_anomalies * 0.20)
    return round(base * penalite, 3)


def evaluer_risque_fraude(score_confiance: float, nb_anomalies: int) -> RisqueFraude:
    """Évalue le niveau de risque de fraude selon le score de confiance."""
    if nb_anomalies >= 3 or score_confiance < 0.40:
        return RisqueFraude.BLOQUE
    if nb_anomalies >= 2 or score_confiance < 0.65:
        return RisqueFraude.ELEVE
    if nb_anomalies >= 1 or score_confiance < 0.80:
        return RisqueFraude.MODERE
    return RisqueFraude.FAIBLE


def analyser_document(
    type_doc: TypeDocument,
    donnees_ocr: Dict[str, str],
    revenu_declare: float = 0,
    solde_momo_moyen: float = 0,
) -> DocumentAnalyse:
    """
    Analyse complète d'un document soumis par le client.

    Paramètres
    ----------
    type_doc : TypeDocument
    donnees_ocr : Dict[str, str]
        Données extraites par le moteur OCR.
    revenu_declare : float
        Revenu déclaré par le client (pour bulletins).
    solde_momo_moyen : float
        Solde moyen MoMo (pour bulletins).

    Retourne
    --------
    DocumentAnalyse
    """
    anomalies: List[str] = []

    if type_doc == TypeDocument.BULLETIN_SALAIRE:
        anomalies += detecter_anomalies_bulletin(donnees_ocr)
        revenu_ocr = float(donnees_ocr.get("revenu_net", "0").replace(" ", "").replace(",", "") or 0)
        coherent, msg_coh = analyser_coherence_revenus(revenu_declare, revenu_ocr, solde_momo_moyen)
        if not coherent:
            anomalies.append(msg_coh)

    champs_renseignes = sum(1 for v in donnees_ocr.values() if v and v.strip())
    score = calculer_score_confiance_document(len(anomalies), champs_renseignes)
    risque = evaluer_risque_fraude(score, len(anomalies))

    recommandation = {
        RisqueFraude.FAIBLE:  "Document validé automatiquement.",
        RisqueFraude.MODERE:  "Validation manuelle recommandée par un analyste.",
        RisqueFraude.ELEVE:   "Vérification obligatoire avec visite terrain ou appel employeur.",
        RisqueFraude.BLOQUE:  "DOSSIER BLOQUÉ. Ne pas poursuivre sans investigation approfondie.",
    }[risque]

    doc_hash = hashlib.sha256(str(donnees_ocr).encode()).hexdigest()[:16]

    return DocumentAnalyse(
        type_document=type_doc,
        donnees_extraites=donnees_ocr,
        score_confiance=score,
        risque_fraude=risque,
        anomalies=anomalies,
        recommandation=recommandation,
        hash_document=doc_hash,
    )


def evaluer_dossier_complet(
    contrat_id: str,
    documents: List[DocumentAnalyse],
) -> ProfilDocumentaire:
    """Évalue la cohérence globale d'un dossier documentaire."""
    if not documents:
        return ProfilDocumentaire(contrat_id, [], 0.0, "INCOMPLET", ["Aucun document soumis."])

    scores = [d.score_confiance for d in documents]
    coherence = sum(scores) / len(scores)

    flags = []
    for d in documents:
        if d.risque_fraude in [RisqueFraude.ELEVE, RisqueFraude.BLOQUE]:
            flags.append(f"🔴 {d.type_document.value} : {d.risque_fraude.value}")
        for a in d.anomalies:
            flags.append(f"  ⚠ {a}")

    if any(d.risque_fraude == RisqueFraude.BLOQUE for d in documents):
        decision = "BLOQUÉ — Dossier suspect. Investigation obligatoire avant toute décision."
    elif coherence >= 0.80:
        decision = "VALIDÉ — Documents conformes."
    elif coherence >= 0.65:
        decision = "REVUE MANUELLE — Cohérence insuffisante."
    else:
        decision = "REFUSÉ — Trop d'anomalies documentaires."

    return ProfilDocumentaire(contrat_id, documents, round(coherence, 3), decision, flags)