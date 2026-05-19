"""
=============================================================================
Module : eligibility_checker.py
Description : Vérification des critères d'éligibilité d'un demandeur PCP.
Auteur : Équipe Technique PCP | Version : 1.0.0
=============================================================================
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Tuple

@dataclass
class CritereEligibilite:
    """Un critère d'éligibilité PCP."""
    nom: str
    valeur_client: float
    seuil_requis: float
    operateur: str          # ">=", "<=", "=="
    passe: bool
    message: str
    eliminatoire: bool = True


def verifier_eligibilite(
    revenu_net: float,
    anciennete_mois: int,
    taux_endettement_apres_pcp: float,
    apport_verse: float,
    prix_vehicule: float,
    age: int,
    duree_mois: int,
    incident_bceao: bool = False,
    nb_credits_actifs: int = 0,
) -> Tuple[bool, List[CritereEligibilite], str]:
    """
    Vérifie l'ensemble des critères d'éligibilité PCP.

    Retourne
    --------
    Tuple[eligible, criteres, message_global]
    """
    apport_min = prix_vehicule * 0.25

    criteres = [
        CritereEligibilite("Âge minimum", age, 21, ">=",
            age >= 21, f"Âge {age} ans {'✅' if age >= 21 else '❌ — min 21 ans'}", True),
        CritereEligibilite("Âge maximum + durée", age + duree_mois / 12, 65, "<=",
            age + duree_mois / 12 <= 65, f"Fin crédit à {age + duree_mois/12:.0f} ans {'✅' if age + duree_mois/12 <= 65 else '❌ — max 65 ans'}", True),
        CritereEligibilite("Ancienneté professionnelle (mois)", anciennete_mois, 12, ">=",
            anciennete_mois >= 12, f"{anciennete_mois} mois {'✅' if anciennete_mois >= 12 else '❌ — min 12 mois'}", True),
        CritereEligibilite("Taux endettement post-PCP (%)", taux_endettement_apres_pcp * 100, 40, "<=",
            taux_endettement_apres_pcp <= 0.40, f"{taux_endettement_apres_pcp*100:.1f}% {'✅' if taux_endettement_apres_pcp<=0.40 else '❌ — max 40%'}", True),
        CritereEligibilite("Apport (25 % du prix)", apport_verse, apport_min, ">=",
            apport_verse >= apport_min * 0.98, f"{apport_verse:,.0f} XOF vs {apport_min:,.0f} XOF min {'✅' if apport_verse>=apport_min*0.98 else '❌'}", True),
        CritereEligibilite("Absence incident BCEAO 24 mois", 0 if not incident_bceao else 1, 0, "==",
            not incident_bceao, "Aucun incident ✅" if not incident_bceao else "Incident détecté ❌", True),
        CritereEligibilite("Nombre crédits actifs", nb_credits_actifs, 3, "<=",
            nb_credits_actifs <= 2, f"{nb_credits_actifs} crédit(s) {'✅' if nb_credits_actifs <= 2 else '❌ — max 2'}", False),
        CritereEligibilite("Revenu minimum", revenu_net, 100_000, ">=",
            revenu_net >= 100_000, f"{revenu_net:,.0f} XOF {'✅' if revenu_net>=100_000 else '❌ — min 100 000 XOF'}", True),
    ]

    eliminatoires_ko = [c for c in criteres if c.eliminatoire and not c.passe]
    eligible = len(eliminatoires_ko) == 0

    if eligible:
        msg = "✅ CLIENT ÉLIGIBLE — Tous les critères sont satisfaits."
    else:
        motifs = ", ".join(c.nom for c in eliminatoires_ko)
        msg = f"❌ CLIENT NON ÉLIGIBLE — Critère(s) manquant(s) : {motifs}."

    return eligible, criteres, msg


def afficher_eligibilite(eligible: bool, criteres: List[CritereEligibilite], msg: str) -> None:
    print("\n" + "─" * 60)
    print("  VÉRIFICATION ÉLIGIBILITÉ PCP")
    print("─" * 60)
    for c in criteres:
        icon = "✅" if c.passe else ("❌" if c.eliminatoire else "⚠️")
        print(f"  {icon} {c.nom:<38} {c.message}")
    print("─" * 60)
    print(f"  RÉSULTAT : {msg}")
    print("─" * 60 + "\n")