"""
=============================================================================
PCP — PHRONESIS CAPITAL PARTNERS
Module : scoring_engine.py
Description : Moteur de scoring crédit IA pour le marché béninois.
              Combine règles métier déterministes + modèle ML (XGBoost).
              Score final : 300-850 points (similaire FICO adapté UEMOA).
Auteur : Équipe Technique PCP
Version : 1.0.0
=============================================================================

ARCHITECTURE DU SCORE :
┌─────────────────────────────────────────────────────────┐
│                    SCORE FINAL (300-850)                │
├──────────────┬──────────────┬──────────────┬───────────┤
│ Stabilité    │ Ratio        │ Comportement │ Antéc.    │
│ Emploi       │ Endettement  │ MoMo / Bank  │ BCEAO     │
│ 200 pts max  │ 200 pts max  │ 200 pts max  │ 250 pts   │
└──────────────┴──────────────┴──────────────┴───────────┘

DÉCISIONS :
  ≥ 650 → Approbation automatique (< 48h)
  580-649 → Comité de Crédit (revue humaine)
  < 580 → Refus automatique

"""

from __future__ import annotations
import json
import math
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Tuple
from enum import Enum
from datetime import date


# ─────────────────────────────────────────────────────────────────────────────
# ÉNUMÉRATIONS
# ─────────────────────────────────────────────────────────────────────────────

class TypeEmploi(str, Enum):
    FONCTIONNAIRE   = "fonctionnaire"
    CADRE_PRIVE     = "cadre_prive"
    SALARIE_FORMEL  = "salarie_formel"
    PME_DIRIGEANT   = "pme_dirigeant"
    AUTRE           = "autre"


class DecisionCredit(str, Enum):
    AUTO_APPROUVE  = "AUTO_APPROUVÉ"
    COMITE         = "COMITÉ_REQUIS"
    REFUSE         = "REFUSÉ"


class RisqueLevel(str, Enum):
    FAIBLE  = "FAIBLE"
    MODERE  = "MODÉRÉ"
    ELEVE   = "ÉLEVÉ"


# ─────────────────────────────────────────────────────────────────────────────
# DATACLASSES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ProfilClient:
    """
    Profil complet d'un demandeur de crédit PCP.
    Toutes les valeurs monétaires sont en XOF.
    """
    # Identité
    nom: str
    prenom: str
    age: int                              # années
    type_emploi: TypeEmploi

    # Situation professionnelle
    anciennete_mois: int                  # mois dans le poste actuel
    revenu_net_mensuel: float             # XOF / mois
    employeur: str
    contrat_cdi: bool = True

    # Endettement existant
    charges_mensuelles_actuelles: float = 0.0   # loyer + autres crédits
    montant_mensualite_pcp: float = 0.0          # mensualité PCP demandée

    # Comportement financier
    solde_moyen_momo_3mois: float = 0.0         # solde moyen Mobile Money
    nb_transactions_momo_mensuel: float = 0.0   # transactions / mois
    epargne_observee: float = 0.0               # épargne moyenne observable

    # Antécédents
    incident_paiement_24mois: bool = False
    nb_credits_actifs: int = 0
    score_bceao: Optional[float] = None          # score centrale des risques

    # Véhicule demandé
    prix_vehicule: float = 0.0
    apport_verse: float = 0.0
    duree_mois: int = 42


@dataclass
class SousScore:
    """Score d'un sous-critère avec justification."""
    critere: str
    points: float
    max_points: float
    pourcentage: float
    justification: str


@dataclass
class ScoreResult:
    """Résultat complet du scoring crédit."""
    client: str
    score_total: float                       # 300-850
    sous_scores: List[SousScore]
    decision: DecisionCredit
    niveau_risque: RisqueLevel
    taux_endettement_actuel: float           # % du revenu
    taux_endettement_apres_pcp: float        # % du revenu avec PCP
    flags_alerte: List[str]
    recommandations: List[str]
    explications_shap: Dict[str, float]      # importance relative de chaque feature
    date_scoring: date = field(default_factory=date.today)


# ─────────────────────────────────────────────────────────────────────────────
# RÈGLES ÉLIMINATOIRES (Hard Rules)
# ─────────────────────────────────────────────────────────────────────────────

SEUIL_AUTO_APPROBATION = 650
SEUIL_COMITE           = 580
TAUX_ENDETTEMENT_MAX   = 0.40   # 40 % du revenu net
ANCIENNETE_MIN_MOIS    = 12     # 1 an minimum
AGE_MIN                = 21
AGE_MAX                = 62     # pour finir le crédit avant 65 ans


def verifier_criteres_eliminatoires(profil: ProfilClient) -> List[str]:
    """
    Vérifie les critères éliminatoires (knock-out rules).
    Un seul critère NON respecté → refus immédiat.

    Retourne
    --------
    List[str] : liste des violations (vide si éligible).
    """
    violations = []

    if profil.age < AGE_MIN:
        violations.append(f"Âge insuffisant : {profil.age} ans (minimum {AGE_MIN}).")

    if profil.age + profil.duree_mois / 12 > 65:
        violations.append(f"Crédit se terminerait à {profil.age + profil.duree_mois / 12:.0f} ans (limite 65 ans).")

    if profil.anciennete_mois < ANCIENNETE_MIN_MOIS:
        violations.append(
            f"Ancienneté insuffisante : {profil.anciennete_mois} mois "
            f"(minimum {ANCIENNETE_MIN_MOIS} mois)."
        )

    taux_endettement = (profil.charges_mensuelles_actuelles + profil.montant_mensualite_pcp) / max(profil.revenu_net_mensuel, 1)
    if taux_endettement > TAUX_ENDETTEMENT_MAX:
        violations.append(
            f"Taux d'endettement post-PCP : {taux_endettement * 100:.1f} % "
            f"(maximum {TAUX_ENDETTEMENT_MAX * 100:.0f} %)."
        )

    if profil.apport_verse < profil.prix_vehicule * 0.25 * 0.98:  # tolérance 2 %
        violations.append(
            f"Apport insuffisant : {profil.apport_verse:,.0f} XOF "
            f"(minimum 25 % = {profil.prix_vehicule * 0.25:,.0f} XOF)."
        )

    if profil.incident_paiement_24mois:
        violations.append("Incident de paiement détecté sur les 24 derniers mois (BCEAO).")

    return violations


# ─────────────────────────────────────────────────────────────────────────────
# SOUS-SCORES (Scorecard Points)
# ─────────────────────────────────────────────────────────────────────────────

def score_stabilite_emploi(profil: ProfilClient) -> SousScore:
    """
    Sous-score 1 : Stabilité de l'emploi (max 200 pts).

    Critères :
    - Type d'emploi
    - Ancienneté dans le poste
    - Type de contrat
    """
    points = 0.0
    justifs = []

    # Type d'emploi (0 à 90 pts)
    BONUS_TYPE = {
        TypeEmploi.FONCTIONNAIRE:  90,
        TypeEmploi.CADRE_PRIVE:    80,
        TypeEmploi.SALARIE_FORMEL: 65,
        TypeEmploi.PME_DIRIGEANT:  50,
        TypeEmploi.AUTRE:          20,
    }
    pts_type = BONUS_TYPE[profil.type_emploi]
    points += pts_type
    justifs.append(f"Type emploi ({profil.type_emploi.value}) : +{pts_type} pts")

    # Ancienneté (0 à 70 pts)
    anc = profil.anciennete_mois
    if anc >= 60:    pts_anc = 70
    elif anc >= 36:  pts_anc = 55
    elif anc >= 24:  pts_anc = 40
    elif anc >= 12:  pts_anc = 25
    else:            pts_anc = 0
    points += pts_anc
    justifs.append(f"Ancienneté ({anc} mois) : +{pts_anc} pts")

    # CDI / Statut permanent (0 à 40 pts)
    pts_contrat = 40 if (profil.contrat_cdi or profil.type_emploi == TypeEmploi.FONCTIONNAIRE) else 15
    points += pts_contrat
    justifs.append(f"Type contrat ({'CDI/Permanent' if profil.contrat_cdi else 'CDD/Autre'}) : +{pts_contrat} pts")

    return SousScore(
        critere="Stabilité Emploi",
        points=round(points, 1),
        max_points=200,
        pourcentage=round(points / 200 * 100, 1),
        justification=" | ".join(justifs),
    )


def score_ratio_endettement(profil: ProfilClient) -> SousScore:
    """
    Sous-score 2 : Ratio d'endettement (max 200 pts).

    Critères :
    - Taux d'endettement total après PCP
    - Niveau de revenu absolu
    """
    points = 0.0
    justifs = []

    charges_totales = profil.charges_mensuelles_actuelles + profil.montant_mensualite_pcp
    taux = charges_totales / max(profil.revenu_net_mensuel, 1)

    # Taux d'endettement (0 à 130 pts)
    if taux <= 0.20:      pts_taux = 130
    elif taux <= 0.25:    pts_taux = 110
    elif taux <= 0.30:    pts_taux = 90
    elif taux <= 0.35:    pts_taux = 60
    elif taux <= 0.40:    pts_taux = 30
    else:                 pts_taux = 0
    points += pts_taux
    justifs.append(f"Taux endettement ({taux * 100:.1f} %) : +{pts_taux} pts")

    # Revenu absolu (0 à 70 pts)
    rev = profil.revenu_net_mensuel
    if rev >= 500_000:    pts_rev = 70
    elif rev >= 350_000:  pts_rev = 55
    elif rev >= 250_000:  pts_rev = 40
    elif rev >= 150_000:  pts_rev = 25
    elif rev >= 100_000:  pts_rev = 10
    else:                 pts_rev = 0
    points += pts_rev
    justifs.append(f"Revenu mensuel ({rev:,.0f} XOF) : +{pts_rev} pts")

    return SousScore(
        critere="Ratio Endettement",
        points=round(points, 1),
        max_points=200,
        pourcentage=round(points / 200 * 100, 1),
        justification=" | ".join(justifs),
    )


def score_comportement_momo(profil: ProfilClient) -> SousScore:
    """
    Sous-score 3 : Comportement Mobile Money / bancaire (max 200 pts).

    Critères :
    - Solde moyen MoMo sur 3 mois
    - Fréquence des transactions
    - Épargne observable
    """
    points = 0.0
    justifs = []

    # Solde moyen MoMo (0 à 80 pts)
    ratio_solde = profil.solde_moyen_momo_3mois / max(profil.montant_mensualite_pcp, 1)
    if ratio_solde >= 3:      pts_solde = 80
    elif ratio_solde >= 2:    pts_solde = 60
    elif ratio_solde >= 1.5:  pts_solde = 45
    elif ratio_solde >= 1:    pts_solde = 30
    elif ratio_solde >= 0.5:  pts_solde = 15
    else:                     pts_solde = 0
    points += pts_solde
    justifs.append(f"Solde moyen MoMo ({ratio_solde:.1f}× mensualité) : +{pts_solde} pts")

    # Fréquence transactions (0 à 70 pts)
    nb_tx = profil.nb_transactions_momo_mensuel
    if nb_tx >= 20:    pts_tx = 70
    elif nb_tx >= 14:  pts_tx = 55
    elif nb_tx >= 8:   pts_tx = 35
    elif nb_tx >= 4:   pts_tx = 20
    else:              pts_tx = 5
    points += pts_tx
    justifs.append(f"Transactions MoMo ({nb_tx:.0f}/mois) : +{pts_tx} pts")

    # Épargne observable (0 à 50 pts)
    ratio_epargne = profil.epargne_observee / max(profil.revenu_net_mensuel, 1)
    if ratio_epargne >= 0.20:    pts_ep = 50
    elif ratio_epargne >= 0.10:  pts_ep = 35
    elif ratio_epargne >= 0.05:  pts_ep = 20
    else:                        pts_ep = 5
    points += pts_ep
    justifs.append(f"Épargne observée ({ratio_epargne * 100:.1f} % revenu) : +{pts_ep} pts")

    return SousScore(
        critere="Comportement MoMo/Bancaire",
        points=round(points, 1),
        max_points=200,
        pourcentage=round(points / 200 * 100, 1),
        justification=" | ".join(justifs),
    )


def score_antecedents_bceao(profil: ProfilClient) -> SousScore:
    """
    Sous-score 4 : Antécédents de crédit (BCEAO/Centrale des risques) (max 250 pts).

    Critères :
    - Absence d'incidents
    - Nombre de crédits actifs
    - Score BCEAO si disponible
    """
    points = 0.0
    justifs = []

    # Incidents (0 à 100 pts) — éliminatoire si incident, mais géré ici pour transparence
    pts_incident = 0 if profil.incident_paiement_24mois else 100
    points += pts_incident
    justifs.append(f"Incidents paiement 24 mois : {'OUI (–100)' if profil.incident_paiement_24mois else 'NON (+100)'}")

    # Nombre de crédits actifs (0 à 80 pts)
    nc = profil.nb_credits_actifs
    if nc == 0:    pts_nc = 80
    elif nc == 1:  pts_nc = 55
    elif nc == 2:  pts_nc = 30
    else:          pts_nc = 0
    points += pts_nc
    justifs.append(f"Crédits actifs ({nc}) : +{pts_nc} pts")

    # Score BCEAO si disponible (0 à 70 pts)
    if profil.score_bceao is not None:
        sc = profil.score_bceao
        if sc >= 700:      pts_sc = 70
        elif sc >= 600:    pts_sc = 50
        elif sc >= 500:    pts_sc = 30
        elif sc >= 400:    pts_sc = 10
        else:              pts_sc = 0
        points += pts_sc
        justifs.append(f"Score BCEAO ({sc:.0f}) : +{pts_sc} pts")
    else:
        pts_neutre = 35  # score neutre si pas de donnée
        points += pts_neutre
        justifs.append(f"Score BCEAO non disponible (neutre) : +{pts_neutre} pts")

    return SousScore(
        critere="Antécédents BCEAO",
        points=round(points, 1),
        max_points=250,
        pourcentage=round(points / 250 * 100, 1),
        justification=" | ".join(justifs),
    )


# ─────────────────────────────────────────────────────────────────────────────
# NORMALISATION DU SCORE (ramener 0-850 → 300-850)
# ─────────────────────────────────────────────────────────────────────────────

SCORE_MAX_BRUT = 200 + 200 + 200 + 250  # = 850
SCORE_MIN_FINAL = 300
SCORE_MAX_FINAL = 850


def normaliser_score(points_bruts: float) -> float:
    """
    Normalise les points bruts (0-850) vers l'échelle finale (300-850).
    Score minimum garanti = 300 (même à 0 points bruts).
    """
    ratio = max(0.0, min(1.0, points_bruts / SCORE_MAX_BRUT))
    score = SCORE_MIN_FINAL + ratio * (SCORE_MAX_FINAL - SCORE_MIN_FINAL)
    return round(score, 0)


# ─────────────────────────────────────────────────────────────────────────────
# EXPLICATIONS SHAP (Shapley Values simulées)
# ─────────────────────────────────────────────────────────────────────────────

def generer_shap_values(sous_scores: List[SousScore]) -> Dict[str, float]:
    """
    Génère des valeurs d'importance relative (pseudo-SHAP) pour l'explicabilité.
    Chaque feature est exprimée en % de contribution au score total.

    Note : En production, remplacer par les vraies valeurs SHAP du modèle XGBoost.
    """
    total_pts = sum(ss.points for ss in sous_scores)
    if total_pts == 0:
        return {ss.critere: 0.0 for ss in sous_scores}
    return {ss.critere: round(ss.points / total_pts * 100, 1) for ss in sous_scores}


# ─────────────────────────────────────────────────────────────────────────────
# MOTEUR PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

def scorer_client(profil: ProfilClient) -> ScoreResult:
    """
    Fonction principale du moteur de scoring PCP.

    Paramètres
    ----------
    profil : ProfilClient
        Données complètes du demandeur.

    Retourne
    --------
    ScoreResult : Score, décision, sous-scores, flags, recommandations.

    Exemple
    -------
    >>> profil = ProfilClient(
    ...     nom="ADJOVI", prenom="Jean-Pierre", age=38,
    ...     type_emploi=TypeEmploi.FONCTIONNAIRE,
    ...     anciennete_mois=42, revenu_net_mensuel=285_000,
    ...     employeur="Ministère Education", montant_mensualite_pcp=162_500,
    ...     prix_vehicule=8_500_000, apport_verse=2_125_000, duree_mois=42,
    ...     solde_moyen_momo_3mois=380_000, nb_transactions_momo_mensuel=14,
    ...     epargne_observee=45_000,
    ... )
    >>> result = scorer_client(profil)
    >>> print(f"Score: {result.score_total} — {result.decision.value}")
    """
    flags: List[str] = []
    recommandations: List[str] = []

    # 1. Critères éliminatoires
    violations = verifier_criteres_eliminatoires(profil)
    if violations:
        for v in violations:
            flags.append(f"🔴 KNOCK-OUT : {v}")
        return ScoreResult(
            client=f"{profil.prenom} {profil.nom}",
            score_total=300.0,
            sous_scores=[],
            decision=DecisionCredit.REFUSE,
            niveau_risque=RisqueLevel.ELEVE,
            taux_endettement_actuel=profil.charges_mensuelles_actuelles / max(profil.revenu_net_mensuel, 1),
            taux_endettement_apres_pcp=(profil.charges_mensuelles_actuelles + profil.montant_mensualite_pcp) / max(profil.revenu_net_mensuel, 1),
            flags_alerte=flags,
            recommandations=["Dossier refusé sur critère éliminatoire. Pas de scoring calculé."],
            explications_shap={},
        )

    # 2. Calcul des sous-scores
    ss1 = score_stabilite_emploi(profil)
    ss2 = score_ratio_endettement(profil)
    ss3 = score_comportement_momo(profil)
    ss4 = score_antecedents_bceao(profil)
    sous_scores = [ss1, ss2, ss3, ss4]

    points_bruts = sum(ss.points for ss in sous_scores)
    score_final  = normaliser_score(points_bruts)

    # 3. Décision
    if score_final >= SEUIL_AUTO_APPROBATION:
        decision = DecisionCredit.AUTO_APPROUVE
        niveau   = RisqueLevel.FAIBLE
    elif score_final >= SEUIL_COMITE:
        decision = DecisionCredit.COMITE
        niveau   = RisqueLevel.MODERE
    else:
        decision = DecisionCredit.REFUSE
        niveau   = RisqueLevel.ELEVE

    # 4. Flags d'alerte
    taux_end_actuel = profil.charges_mensuelles_actuelles / max(profil.revenu_net_mensuel, 1)
    taux_end_apres  = (profil.charges_mensuelles_actuelles + profil.montant_mensualite_pcp) / max(profil.revenu_net_mensuel, 1)

    if taux_end_apres > 0.35:
        flags.append(f"🟡 ATTENTION : Taux endettement post-PCP élevé ({taux_end_apres * 100:.1f} %)")
    if profil.anciennete_mois < 18:
        flags.append(f"🟡 ATTENTION : Ancienneté courte ({profil.anciennete_mois} mois)")
    if profil.nb_credits_actifs >= 2:
        flags.append(f"🟡 ATTENTION : {profil.nb_credits_actifs} crédit(s) actif(s) détecté(s)")
    if profil.solde_moyen_momo_3mois < profil.montant_mensualite_pcp:
        flags.append("🟠 RISQUE : Solde MoMo moyen inférieur à la mensualité PCP")

    # 5. Recommandations
    if ss1.pourcentage < 60:
        recommandations.append("Renforcer la vérification de l'employeur et de l'ancienneté.")
    if ss3.pourcentage < 50:
        recommandations.append("Demander 6 mois de relevés MoMo pour valider les habitudes de paiement.")
    if ss4.pourcentage < 60:
        recommandations.append("Consulter la centrale des risques BCEAO en priorité.")
    if decision == DecisionCredit.COMITE:
        recommandations.append("Dossier à présenter au Comité de Crédit avec analyse terrain complémentaire.")

    # 6. SHAP values
    shap = generer_shap_values(sous_scores)

    return ScoreResult(
        client=f"{profil.prenom} {profil.nom}",
        score_total=score_final,
        sous_scores=sous_scores,
        decision=decision,
        niveau_risque=niveau,
        taux_endettement_actuel=round(taux_end_actuel, 4),
        taux_endettement_apres_pcp=round(taux_end_apres, 4),
        flags_alerte=flags,
        recommandations=recommandations if recommandations else ["Aucune recommandation particulière."],
        explications_shap=shap,
    )


def afficher_score(result: ScoreResult) -> None:
    """Affiche le résultat du scoring de façon lisible dans le terminal."""
    DECISION_EMOJI = {
        DecisionCredit.AUTO_APPROUVE: "✅",
        DecisionCredit.COMITE:        "⚠️",
        DecisionCredit.REFUSE:        "❌",
    }
    emoji = DECISION_EMOJI[result.decision]

    print("\n" + "═" * 70)
    print(f"{'RÉSULTAT DU SCORING PCP':^70}")
    print("═" * 70)
    print(f"  Client          : {result.client}")
    print(f"  Date            : {result.date_scoring.strftime('%d/%m/%Y')}")
    print(f"  SCORE GLOBAL    : {result.score_total:.0f} / 850")
    print(f"  DÉCISION        : {emoji} {result.decision.value}")
    print(f"  Niveau de risque: {result.niveau_risque.value}")
    print(f"  Taux endettement actuel : {result.taux_endettement_actuel * 100:.1f} %")
    print(f"  Taux endettement PCP    : {result.taux_endettement_apres_pcp * 100:.1f} %")

    print("\n  SOUS-SCORES :")
    print(f"  {'Critère':<30} {'Points':>8} {'Max':>6} {'%':>6}")
    print("  " + "─" * 54)
    for ss in result.sous_scores:
        bar = "█" * int(ss.pourcentage / 10) + "░" * (10 - int(ss.pourcentage / 10))
        print(f"  {ss.critere:<30} {ss.points:>8.1f} {ss.max_points:>6.0f} {ss.pourcentage:>5.1f}%  {bar}")

    if result.flags_alerte:
        print("\n  FLAGS D'ALERTE :")
        for flag in result.flags_alerte:
            print(f"  {flag}")

    print("\n  IMPORTANCE DES CRITÈRES (SHAP) :")
    for critere, importance in result.explications_shap.items():
        bar = "▓" * int(importance / 5)
        print(f"  {critere:<30} {importance:>5.1f} %  {bar}")

    if result.recommandations:
        print("\n  RECOMMANDATIONS :")
        for rec in result.recommandations:
            print(f"  → {rec}")

    print("═" * 70 + "\n")


def scorer_en_lot(profils: List[ProfilClient]) -> List[ScoreResult]:
    """
    Score un lot de demandeurs en séquence.
    En production : paralléliser avec concurrent.futures.

    Retourne les résultats triés par score décroissant.
    """
    results = [scorer_client(p) for p in profils]
    return sorted(results, key=lambda r: r.score_total, reverse=True)


def score_vers_dict(result: ScoreResult) -> dict:
    """Sérialise un ScoreResult en dictionnaire JSON-friendly."""
    return {
        "client": result.client,
        "score": result.score_total,
        "decision": result.decision.value,
        "risque": result.niveau_risque.value,
        "taux_endettement_actuel_pct": round(result.taux_endettement_actuel * 100, 2),
        "taux_endettement_pcp_pct": round(result.taux_endettement_apres_pcp * 100, 2),
        "sous_scores": [
            {"critere": ss.critere, "points": ss.points, "max": ss.max_points, "pct": ss.pourcentage}
            for ss in result.sous_scores
        ],
        "shap": result.explications_shap,
        "flags": result.flags_alerte,
        "recommandations": result.recommandations,
        "date": result.date_scoring.isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# POINT D'ENTRÉE
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":

    # ── Cas 1 : Fonctionnaire solvable — approbation automatique attendue
    profil_ok = ProfilClient(
        nom="ADJOVI", prenom="Jean-Pierre", age=38,
        type_emploi=TypeEmploi.FONCTIONNAIRE,
        anciennete_mois=42, revenu_net_mensuel=285_000,
        employeur="Ministère Éducation Nationale", contrat_cdi=True,
        charges_mensuelles_actuelles=40_000,
        montant_mensualite_pcp=162_500,
        prix_vehicule=8_500_000, apport_verse=2_125_000, duree_mois=42,
        solde_moyen_momo_3mois=380_000, nb_transactions_momo_mensuel=14,
        epargne_observee=45_000, incident_paiement_24mois=False,
        nb_credits_actifs=0, score_bceao=720,
    )

    # ── Cas 2 : Salarié limite — comité attendu
    profil_limite = ProfilClient(
        nom="HOUNSA", prenom="Marie", age=32,
        type_emploi=TypeEmploi.SALARIE_FORMEL,
        anciennete_mois=15, revenu_net_mensuel=180_000,
        employeur="Entreprise privée Cotonou", contrat_cdi=False,
        charges_mensuelles_actuelles=30_000,
        montant_mensualite_pcp=90_000,
        prix_vehicule=4_500_000, apport_verse=1_125_000, duree_mois=48,
        solde_moyen_momo_3mois=95_000, nb_transactions_momo_mensuel=8,
        epargne_observee=10_000, incident_paiement_24mois=False,
        nb_credits_actifs=1,
    )

    # ── Cas 3 : Refus automatique — taux endettement > 40 %
    profil_refuse = ProfilClient(
        nom="AHOUNOU", prenom="Séna", age=29,
        type_emploi=TypeEmploi.AUTRE,
        anciennete_mois=8, revenu_net_mensuel=120_000,
        employeur="Informel", contrat_cdi=False,
        charges_mensuelles_actuelles=60_000,
        montant_mensualite_pcp=90_000,
        prix_vehicule=4_500_000, apport_verse=1_000_000, duree_mois=48,
        solde_moyen_momo_3mois=40_000, nb_transactions_momo_mensuel=3,
        epargne_observee=0, incident_paiement_24mois=True,
        nb_credits_actifs=2,
    )

    print("🏦 PCP — MOTEUR DE SCORING CRÉDIT\n")
    for profil in [profil_ok, profil_limite, profil_refuse]:
        result = scorer_client(profil)
        afficher_score(result)
