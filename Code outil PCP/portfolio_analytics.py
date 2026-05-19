"""
=============================================================================
PCP — PHRONESIS CAPITAL PARTNERS
Module : portfolio_analytics.py
Description : Analytics en temps réel du portefeuille PCP.
              KPIs investisseurs, projections, reporting automatique.
Auteur : Équipe Technique PCP | Version : 1.0.0
=============================================================================
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict
from datetime import date


@dataclass
class KPIsDashboard:
    """KPIs temps réel pour le dashboard investisseur et gestionnaire."""
    date_calcul: date

    # Volume
    encours_total_xof: float
    nb_contrats_actifs: int
    nb_contrats_total: int
    capital_leve_total_xof: float

    # Qualité
    npl_ratio_pct: float
    taux_remboursement_heure_pct: float
    lgd_moyen_pct: float
    recovery_rate_pct: float

    # Rentabilité
    ca_ytd_xof: float                # Chiffre d'affaires year-to-date
    rne_ytd_xof: float               # Résultat net year-to-date
    roe_ytd_pct: float               # ROE annualisé
    marge_nette_pct: float

    # Opérations
    taux_gps_actif_pct: float
    nb_coupe_moteur_actifs: int
    delai_moyen_approbation_heures: float

    # Investisseur
    tri_estime_pct: float
    moic_estime: float
    prochaine_distribution_xof: float
    prochaine_distribution_date: date


def generer_kpis(
    encours: float,
    nb_actifs: int,
    nb_total: int,
    capital_leve: float,
    npl_pct: float,
    taux_remb: float,
    lgd_pct: float,
    ca_ytd: float,
    rne_ytd: float,
    fonds_propres: float,
    gps_actif_pct: float,
    nb_coupes: int,
    tri: float,
    moic: float,
    distrib_prochain: float,
    date_distrib: date,
) -> KPIsDashboard:
    """Génère les KPIs complets du dashboard PCP."""
    roe = (rne_ytd / max(fonds_propres, 1)) * 100
    marge = (rne_ytd / max(ca_ytd, 1)) * 100

    return KPIsDashboard(
        date_calcul=date.today(),
        encours_total_xof=encours,
        nb_contrats_actifs=nb_actifs,
        nb_contrats_total=nb_total,
        capital_leve_total_xof=capital_leve,
        npl_ratio_pct=npl_pct,
        taux_remboursement_heure_pct=taux_remb,
        lgd_moyen_pct=lgd_pct,
        recovery_rate_pct=100 - lgd_pct,
        ca_ytd_xof=ca_ytd,
        rne_ytd_xof=rne_ytd,
        roe_ytd_pct=round(roe, 2),
        marge_nette_pct=round(marge, 2),
        taux_gps_actif_pct=gps_actif_pct,
        nb_coupe_moteur_actifs=nb_coupes,
        delai_moyen_approbation_heures=36.5,  # à alimenter depuis la BDD
        tri_estime_pct=tri,
        moic_estime=moic,
        prochaine_distribution_xof=distrib_prochain,
        prochaine_distribution_date=date_distrib,
    )


def afficher_dashboard(kpi: KPIsDashboard) -> None:
    """Affiche le dashboard PCP dans le terminal."""
    print("\n" + "═" * 70)
    print(f"{'📊 DASHBOARD PCP — ' + kpi.date_calcul.strftime('%d/%m/%Y'):^70}")
    print("═" * 70)

    sections = [
        ("📦 PORTEFEUILLE", [
            ("Encours total",          f"{kpi.encours_total_xof:>18,.0f} XOF"),
            ("Contrats actifs",        f"{kpi.nb_contrats_actifs:>22}"),
            ("Capital levé (cumulé)",  f"{kpi.capital_leve_total_xof:>18,.0f} XOF"),
        ]),
        ("⚠️  QUALITÉ CRÉDIT", [
            ("NPL Ratio",              f"{kpi.npl_ratio_pct:>21.2f} %"),
            ("Remboursement à l'heure",f"{kpi.taux_remboursement_heure_pct:>21.1f} %"),
            ("LGD moyen",              f"{kpi.lgd_moyen_pct:>21.2f} %"),
            ("Recovery Rate",          f"{kpi.recovery_rate_pct:>21.2f} %"),
        ]),
        ("💰 RENTABILITÉ", [
            ("CA year-to-date",        f"{kpi.ca_ytd_xof:>18,.0f} XOF"),
            ("RNE year-to-date",       f"{kpi.rne_ytd_xof:>18,.0f} XOF"),
            ("ROE annualisé",          f"{kpi.roe_ytd_pct:>21.2f} %"),
            ("Marge nette",            f"{kpi.marge_nette_pct:>21.2f} %"),
        ]),
        ("🗺️  OPÉRATIONS", [
            ("GPS actifs",             f"{kpi.taux_gps_actif_pct:>21.1f} %"),
            ("Coupe-moteur actifs",    f"{kpi.nb_coupe_moteur_actifs:>22}"),
            ("Délai moyen approbation",f"{kpi.delai_moyen_approbation_heures:>19.1f} h"),
        ]),
        ("📈 INVESTISSEUR", [
            ("TRI estimé",             f"{kpi.tri_estime_pct:>21.1f} %"),
            ("MOIC estimé",            f"{kpi.moic_estime:>21.2f}×"),
            ("Prochaine distribution", f"{kpi.prochaine_distribution_xof:>18,.0f} XOF"),
            ("Date distribution",      f"{kpi.prochaine_distribution_date.strftime('%d/%m/%Y'):>22}"),
        ]),
    ]

    for titre, lignes in sections:
        print(f"\n  {titre}")
        print("  " + "─" * 55)
        for label, valeur in lignes:
            print(f"  {label:<35} {valeur}")

    print("\n" + "═" * 70 + "\n")


def projection_encours(
    encours_actuel: float,
    nb_nouveaux_contrats_mois: int,
    panier_moyen: float,
    taux_remboursement_mensuel: float,
    nb_mois: int = 12,
) -> List[Dict]:
    """
    Projette l'évolution de l'encours sur N mois.

    Paramètres
    ----------
    encours_actuel : float
        Encours actuel (XOF).
    nb_nouveaux_contrats_mois : int
        Nouveaux contrats signés par mois.
    panier_moyen : float
        Montant moyen financé par contrat (XOF).
    taux_remboursement_mensuel : float
        Taux de remboursement mensuel du portefeuille (TEG/12).
    nb_mois : int
        Horizon de projection.

    Retourne
    --------
    List[Dict] : Projection mois par mois.
    """
    projection = []
    encours = encours_actuel

    for m in range(1, nb_mois + 1):
        remboursements = encours * taux_remboursement_mensuel
        nouvelles_creances = nb_nouveaux_contrats_mois * panier_moyen
        encours = encours - remboursements + nouvelles_creances
        revenu_mensuel = encours * (0.22 / 12)  # TEG 22%

        projection.append({
            "mois": m,
            "encours_xof": round(encours, 0),
            "nouveaux_contrats": nb_nouveaux_contrats_mois,
            "remboursements_xof": round(remboursements, 0),
            "revenu_mensuel_xof": round(revenu_mensuel, 0),
        })

    return projection