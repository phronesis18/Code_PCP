"""
=============================================================================
PCP — PHRONESIS CAPITAL PARTNERS
Module : risk_metrics.py
Description : Calcul des métriques de risque du portefeuille PCP.
              NPL, LGD, Recovery Rate, Expected Loss, stress tests.
Auteur : Équipe Technique PCP
Version : 1.0.0
=============================================================================
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from enum import Enum
from datetime import date
import statistics


# ─────────────────────────────────────────────────────────────────────────────
# ÉNUMÉRATIONS
# ─────────────────────────────────────────────────────────────────────────────

class StatutContrat(str, Enum):
    ACTIF        = "actif"
    NPL_30       = "npl_30"       # 30-60 jours retard
    NPL_60       = "npl_60"       # 60-90 jours retard
    NPL_90       = "npl_90"       # > 90 jours — défaut formel
    RECOUVRE     = "recouvré"     # véhicule récupéré, en cours de revente
    SOLDE        = "soldé"        # remboursé intégralement
    PERTE        = "perte_finale" # irrécupérable


class ScenarioStress(str, Enum):
    BASE     = "base"
    DEGRADE  = "dégradé"
    CHOC     = "choc"


# ─────────────────────────────────────────────────────────────────────────────
# DATACLASSES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Contrat:
    """Représentation d'un contrat actif dans le portefeuille PCP."""
    id: str
    montant_initial: float       # XOF — montant financé à l'origine
    capital_restant_du: float    # XOF — capital restant à date
    mensualite: float            # XOF / mois
    valeur_vehicule_actuelle: float  # XOF — valeur de revente estimée
    jours_retard: int = 0
    statut: StatutContrat = StatutContrat.ACTIF
    gps_actif: bool = True
    assurance_valide: bool = True
    date_debut: Optional[date] = None


@dataclass
class PortefeuilleMetrics:
    """Métriques agrégées du portefeuille PCP."""
    # Volume
    nb_contrats_total: int
    nb_contrats_actifs: int
    encours_total: float          # XOF
    encours_npl: float            # XOF — montant des contrats en défaut

    # Ratios de qualité
    npl_ratio: float              # %
    taux_retard_30j: float        # %
    taux_retard_60j: float        # %

    # Perte estimée
    expected_loss: float          # XOF
    lgd_moyen: float              # %
    recovery_rate_moyen: float    # %

    # Rentabilité
    revenu_interets_mensuel: float
    cout_risque_mensuel: float
    produit_net_financier_mensuel: float

    # GPS
    taux_gps_actif: float         # %
    nb_coupes_moteur_actifs: int

    date_calcul: date = field(default_factory=date.today)


@dataclass
class StressTestResult:
    """Résultat d'un stress test sur le portefeuille."""
    scenario: ScenarioStress
    npl_rate: float
    recovery_rate: float
    lgd_net: float
    cout_risque_total: float
    impact_sur_rne: float        # variation du résultat net
    fonds_viable: bool
    tri_estime: float
    commentaire: str


# ─────────────────────────────────────────────────────────────────────────────
# MÉTRIQUES INDIVIDUELLES
# ─────────────────────────────────────────────────────────────────────────────

def determiner_statut(jours_retard: int) -> StatutContrat:
    """Classe un contrat selon son nombre de jours de retard."""
    if jours_retard == 0:   return StatutContrat.ACTIF
    if jours_retard <= 30:  return StatutContrat.NPL_30
    if jours_retard <= 60:  return StatutContrat.NPL_60
    return StatutContrat.NPL_90


def calcul_lgd_contrat(
    capital_restant: float,
    valeur_vehicule: float,
    gps_actif: bool = True,
    assurance_valide: bool = True,
    frais_recuperation: float = 50_000,
) -> Tuple[float, float, float]:
    """
    Calcule le Loss Given Default (LGD) d'un contrat en défaut.

    Méthodologie PCP :
    - Récupération du véhicule grâce au GPS + propriété légale
    - Revente du véhicule avec décote de marché
    - Déduction des frais de récupération et de vente

    Paramètres
    ----------
    capital_restant : float
        Capital restant dû (exposition au défaut = EAD).
    valeur_vehicule : float
        Valeur de revente estimée du véhicule.
    gps_actif : bool
        Le boîtier GPS fonctionne (facilite la récupération).
    assurance_valide : bool
        L'assurance est valide (couvre les sinistres).
    frais_recuperation : float
        Frais fixes de récupération et remise en état (XOF).

    Retourne
    --------
    Tuple[recovery_amount, lgd_xof, lgd_pct]
    """
    # Décote selon disponibilité GPS
    decote_marche = 0.15 if gps_actif else 0.25
    valeur_nette_revente = valeur_vehicule * (1 - decote_marche) - frais_recuperation

    # Bonus assurance si sinistre couvert
    bonus_assurance = min(capital_restant * 0.30, valeur_vehicule * 0.20) if assurance_valide else 0.0

    recovery_amount = min(valeur_nette_revente + bonus_assurance, capital_restant)
    recovery_amount = max(0.0, recovery_amount)

    lgd_xof = max(0.0, capital_restant - recovery_amount)
    lgd_pct  = lgd_xof / capital_restant if capital_restant > 0 else 0.0

    return round(recovery_amount, 0), round(lgd_xof, 0), round(lgd_pct, 4)


def calcul_expected_loss(
    encours: float,
    pd: float,       # Probability of Default
    lgd: float,      # Loss Given Default (ratio 0-1)
    ead_ratio: float = 1.0,  # Exposure at Default ratio
) -> float:
    """
    Expected Loss = PD × LGD × EAD
    Formule standard Bâle II / IFRS 9.

    Paramètres
    ----------
    encours : float
        Encours total (XOF).
    pd : float
        Probabilité de défaut (ex: 0.08 = 8 %).
    lgd : float
        Taux de perte en cas de défaut (ex: 0.15 = 15 %).
    ead_ratio : float
        Ratio d'exposition au défaut (généralement 1.0).

    Retourne
    --------
    float : Perte attendue en XOF.
    """
    ead = encours * ead_ratio
    return round(ead * pd * lgd, 0)


# ─────────────────────────────────────────────────────────────────────────────
# MÉTRIQUES AGRÉGÉES DU PORTEFEUILLE
# ─────────────────────────────────────────────────────────────────────────────

def calculer_metriques_portefeuille(
    contrats: List[Contrat],
    teg_annuel: float = 0.22,
    pd_historique: float = 0.08,
    lgd_cible: float = 0.15,
) -> PortefeuilleMetrics:
    """
    Calcule l'ensemble des métriques du portefeuille PCP.

    Paramètres
    ----------
    contrats : List[Contrat]
        Liste de tous les contrats actifs et en défaut.
    teg_annuel : float
        TEG moyen du portefeuille.
    pd_historique : float
        Probabilité de défaut estimée.
    lgd_cible : float
        LGD cible (15 % grâce au dispositif PCP).

    Retourne
    --------
    PortefeuilleMetrics
    """
    if not contrats:
        raise ValueError("Le portefeuille est vide.")

    actifs = [c for c in contrats if c.statut == StatutContrat.ACTIF]
    npl_30 = [c for c in contrats if c.statut == StatutContrat.NPL_30]
    npl_60 = [c for c in contrats if c.statut == StatutContrat.NPL_60]
    npl_90 = [c for c in contrats if c.statut == StatutContrat.NPL_90]
    npl_all = npl_90  # NPL formel = 90j+

    encours_total   = sum(c.capital_restant_du for c in contrats if c.statut not in [StatutContrat.SOLDE, StatutContrat.PERTE])
    encours_npl     = sum(c.capital_restant_du for c in npl_all)
    npl_ratio       = encours_npl / encours_total if encours_total > 0 else 0.0

    # LGD et recovery calculés sur les NPL 90j
    lgd_values = []
    for c in npl_all:
        _, _, lgd_pct = calcul_lgd_contrat(
            c.capital_restant_du, c.valeur_vehicule_actuelle,
            c.gps_actif, c.assurance_valide
        )
        lgd_values.append(lgd_pct)
    lgd_moyen        = statistics.mean(lgd_values) if lgd_values else lgd_cible
    recovery_moyen   = 1 - lgd_moyen

    # Expected Loss (mensuelle)
    el_mensuel       = calcul_expected_loss(encours_total, pd_historique / 12, lgd_moyen)

    # Revenus d'intérêts (mensuel = encours × TEG / 12)
    rev_interets_mensuel = encours_total * teg_annuel / 12
    pnf_mensuel          = rev_interets_mensuel - el_mensuel

    # GPS
    nb_gps_actifs     = sum(1 for c in actifs if c.gps_actif)
    taux_gps_actif    = nb_gps_actifs / max(len(actifs), 1)
    nb_coupes_actifs  = sum(1 for c in npl_60 + npl_90 if not c.gps_actif is False)

    return PortefeuilleMetrics(
        nb_contrats_total=len(contrats),
        nb_contrats_actifs=len(actifs),
        encours_total=round(encours_total, 0),
        encours_npl=round(encours_npl, 0),
        npl_ratio=round(npl_ratio * 100, 2),
        taux_retard_30j=round(len(npl_30) / max(len(contrats), 1) * 100, 2),
        taux_retard_60j=round(len(npl_60) / max(len(contrats), 1) * 100, 2),
        expected_loss=el_mensuel,
        lgd_moyen=round(lgd_moyen * 100, 2),
        recovery_rate_moyen=round(recovery_moyen * 100, 2),
        revenu_interets_mensuel=round(rev_interets_mensuel, 0),
        cout_risque_mensuel=round(el_mensuel, 0),
        produit_net_financier_mensuel=round(pnf_mensuel, 0),
        taux_gps_actif=round(taux_gps_actif * 100, 2),
        nb_coupes_moteur_actifs=nb_coupes_actifs,
    )


# ─────────────────────────────────────────────────────────────────────────────
# STRESS TESTS
# ─────────────────────────────────────────────────────────────────────────────

SCENARIOS_PARAMS: Dict[ScenarioStress, Dict] = {
    ScenarioStress.BASE: {
        "npl_rate": 0.08, "recovery_rate": 0.90, "ca_growth": 0.22,
        "commentaire": "Conditions normales. Modèle PCP opérant selon les projections.",
    },
    ScenarioStress.DEGRADE: {
        "npl_rate": 0.15, "recovery_rate": 0.75, "ca_growth": 0.08,
        "commentaire": "Détérioration macroéconomique modérée. Chômage en hausse. Inflation > 5 %.",
    },
    ScenarioStress.CHOC: {
        "npl_rate": 0.25, "recovery_rate": 0.50, "ca_growth": 0.00,
        "commentaire": "Choc systémique (récession, crise politique). Scénario extrême improbable.",
    },
}


def stress_test(
    encours: float,
    teg_annuel: float = 0.22,
    charges_fixes_annuelles: float = 820_000,
    charges_variables_ratio: float = 0.25,
) -> List[StressTestResult]:
    """
    Exécute les 3 scénarios de stress test sur le portefeuille PCP.

    Paramètres
    ----------
    encours : float
        Encours total du portefeuille (XOF).
    teg_annuel : float
        TEG moyen du portefeuille.
    charges_fixes_annuelles : float
        Charges fixes annuelles (XOF).
    charges_variables_ratio : float
        Part des charges variables dans le CA.

    Retourne
    --------
    List[StressTestResult]
    """
    ca_annuel = encours * teg_annuel
    results = []

    for scenario, params in SCENARIOS_PARAMS.items():
        npl_rate      = params["npl_rate"]
        recovery_rate = params["recovery_rate"]
        lgd_net       = 1 - recovery_rate
        ca_growth     = params["ca_growth"]

        # Coût du risque
        cout_risque = calcul_expected_loss(encours, npl_rate, lgd_net)

        # Charges variables
        charges_var  = ca_annuel * charges_variables_ratio
        charges_totales = charges_fixes_annuelles + charges_var

        # EBITDA et RNE estimés
        pnf         = ca_annuel - cout_risque
        ebitda      = pnf - charges_totales
        rne         = ebitda * (1 - 0.25)  # IS 25 %

        # Viabilité
        fonds_viable = rne > 0

        # TRI simplifié (estimation linéaire)
        tri_est = (rne / encours) if encours > 0 else 0.0

        results.append(StressTestResult(
            scenario=scenario,
            npl_rate=round(npl_rate * 100, 1),
            recovery_rate=round(recovery_rate * 100, 1),
            lgd_net=round(lgd_net * 100, 1),
            cout_risque_total=round(cout_risque, 0),
            impact_sur_rne=round(rne, 0),
            fonds_viable=fonds_viable,
            tri_estime=round(tri_est * 100, 1),
            commentaire=params["commentaire"],
        ))

    return results


def afficher_stress_tests(results: List[StressTestResult]) -> None:
    """Affiche les résultats des stress tests."""
    print("\n" + "═" * 85)
    print(f"{'STRESS TESTS — PORTEFEUILLE PCP':^85}")
    print("═" * 85)
    print(f"  {'Scénario':<12} {'NPL':>6} {'Recovery':>10} {'LGD net':>8} {'Coût Risque':>14} {'RNE':>14} {'Viable':>8}")
    print("─" * 85)
    ICONS = {ScenarioStress.BASE: "🟢", ScenarioStress.DEGRADE: "🟠", ScenarioStress.CHOC: "🔴"}
    for r in results:
        icon = ICONS[r.scenario]
        viable_str = "✅ OUI" if r.fonds_viable else "❌ NON"
        print(f"  {icon} {r.scenario.value:<10} {r.npl_rate:>5.1f}% {r.recovery_rate:>8.1f}% "
              f"{r.lgd_net:>7.1f}% {r.cout_risque_total:>14,.0f} {r.impact_sur_rne:>14,.0f} {viable_str:>8}")
    print("─" * 85)
    for r in results:
        print(f"\n  [{r.scenario.value.upper()}] {r.commentaire}")
    print("═" * 85 + "\n")


def afficher_portefeuille(m: PortefeuilleMetrics) -> None:
    """Affiche les métriques du portefeuille."""
    print("\n" + "═" * 65)
    print(f"{'MÉTRIQUES PORTEFEUILLE PCP':^65}")
    print("═" * 65)
    print(f"  Contrats total         : {m.nb_contrats_total:>8}")
    print(f"  Contrats actifs        : {m.nb_contrats_actifs:>8}")
    print(f"  Encours total          : {m.encours_total:>14,.0f} XOF")
    print(f"  Encours NPL 90j        : {m.encours_npl:>14,.0f} XOF")
    print(f"  NPL Ratio              : {m.npl_ratio:>7.2f} %")
    print(f"  Retards 30j            : {m.taux_retard_30j:>7.2f} %")
    print(f"  LGD moyen              : {m.lgd_moyen:>7.2f} %")
    print(f"  Recovery Rate          : {m.recovery_rate_moyen:>7.2f} %")
    print(f"  Revenu intérêts/mois   : {m.revenu_interets_mensuel:>14,.0f} XOF")
    print(f"  Coût risque/mois       : {m.cout_risque_mensuel:>14,.0f} XOF")
    print(f"  Produit Net Financier  : {m.produit_net_financier_mensuel:>14,.0f} XOF/mois")
    print(f"  GPS actifs             : {m.taux_gps_actif:>7.1f} %")
    print(f"  Coupe-moteur actifs    : {m.nb_coupes_moteur_actifs:>8}")
    print("═" * 65 + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# POINT D'ENTRÉE
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("📊 PCP — MÉTRIQUES DE RISQUE PORTEFEUILLE\n")

    # Portefeuille simulé Phase 1 (6 contrats)
    contrats_demo = [
        Contrat("PCP-001", 6_375_000, 5_800_000, 216_000, 7_200_000, 0,  StatutContrat.ACTIF, True, True),
        Contrat("PCP-002", 5_200_000, 4_100_000, 175_000, 5_800_000, 0,  StatutContrat.ACTIF, True, True),
        Contrat("PCP-003", 4_800_000, 4_600_000, 162_000, 5_200_000, 0,  StatutContrat.ACTIF, True, True),
        Contrat("PCP-004", 6_375_000, 6_200_000, 216_000, 7_100_000, 18, StatutContrat.NPL_30, True, True),
        Contrat("PCP-005", 5_600_000, 5_400_000, 189_000, 6_000_000, 0,  StatutContrat.ACTIF, True, True),
        Contrat("PCP-006", 4_200_000, 4_050_000, 142_000, 4_500_000, 0,  StatutContrat.ACTIF, True, True),
    ]

    m = calculer_metriques_portefeuille(contrats_demo)
    afficher_portefeuille(m)

    # LGD sur contrat en défaut
    rec, lgd_xof, lgd_pct = calcul_lgd_contrat(6_200_000, 7_100_000, True, True)
    print(f"  LGD Contrat PCP-004 (GPS actif) :")
    print(f"  Récupéré : {rec:,.0f} XOF | LGD : {lgd_xof:,.0f} XOF ({lgd_pct*100:.1f} %)\n")

    # Stress tests sur encours AN5 estimé
    stress_results = stress_test(encours=38_400_000, charges_fixes_annuelles=820_000)
    afficher_stress_tests(stress_results)
