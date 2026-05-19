"""
=============================================================================
PCP — PHRONESIS CAPITAL PARTNERS
Module : loan_calculator.py
Description : Calcul des mensualités, tableau d'amortissement,
              TEG, seuil de rentabilité, KPIs financiers.
Auteur : Équipe Technique PCP
Version : 1.0.0
=============================================================================
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional
import math
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta


# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTES PCP
# ─────────────────────────────────────────────────────────────────────────────

TEG_ANNUEL_DEFAULT   = 0.22   # 22 % / an
APPORT_RATIO         = 0.25   # 25 % du prix véhicule
DUREES_AUTORISEES    = {36, 42, 48}  # mois
TAUX_IS              = 0.25   # 25 % OHADA
TAUX_GPS_MENSUEL     = 3_500  # XOF / véhicule / mois
TAUX_ASSURANCE_ANNUEL = 0.015 # 1,5 % de la valeur véhicule / an


# ─────────────────────────────────────────────────────────────────────────────
# DATACLASSES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class LoanParams:
    """Paramètres d'un dossier de crédit PCP."""
    prix_vehicule: float          # Prix TTC du véhicule en XOF
    duree_mois: int               # 36 ou 48
    teg_annuel: float = TEG_ANNUEL_DEFAULT
    date_signature: date = field(default_factory=date.today)
    include_assurance: bool = True
    include_gps: bool = True

    def __post_init__(self):
        if self.duree_mois not in DUREES_AUTORISEES:
            raise ValueError(f"Durée {self.duree_mois} invalide. Valeurs: {DUREES_AUTORISEES}")
        if self.prix_vehicule <= 0:
            raise ValueError("Le prix du véhicule doit être positif.")
        if not (0.01 <= self.teg_annuel <= 0.50):
            raise ValueError("TEG doit être entre 1 % et 50 %.")


@dataclass
class AmortizationRow:
    """Ligne du tableau d'amortissement."""
    mois: int
    date_echeance: date
    mensualite: float
    interets: float
    capital_rembourse: float
    capital_restant_du: float
    cumul_interets: float
    cumul_capital: float


@dataclass
class LoanSummary:
    """Résumé complet d'un prêt."""
    prix_vehicule: float
    apport: float
    montant_finance: float
    teg_annuel: float
    taux_mensuel: float
    duree_mois: int
    mensualite_hors_services: float
    prime_assurance_mensuelle: float
    frais_gps_mensuel: float
    mensualite_totale: float
    cout_total_credit: float
    total_verse_client: float
    tableau: List[AmortizationRow]
    date_premiere_echeance: date
    date_derniere_echeance: date


# ─────────────────────────────────────────────────────────────────────────────
# CALCULS CORE
# ─────────────────────────────────────────────────────────────────────────────

def calcul_mensualite(capital: float, teg_annuel: float, duree_mois: int) -> float:
    """
    Calcule la mensualité constante selon la formule d'amortissement français.

    Formule :
        M = C × [r(1+r)^n] / [(1+r)^n - 1]

    Paramètres
    ----------
    capital : float
        Montant emprunté en XOF.
    teg_annuel : float
        Taux effectif global annuel (ex: 0.22 pour 22 %).
    duree_mois : int
        Nombre de mensualités.

    Retourne
    --------
    float : Mensualité en XOF (arrondie au franc supérieur).

    Exemple
    -------
    >>> calcul_mensualite(6_375_000, 0.22, 42)
    216137.45...
    """
    r = teg_annuel / 12  # taux mensuel
    n = duree_mois
    if r == 0:
        return capital / n
    mensualite = capital * (r * (1 + r) ** n) / ((1 + r) ** n - 1)
    return round(mensualite, 2)


def calcul_apport(prix_vehicule: float, ratio: float = APPORT_RATIO) -> float:
    """Calcule l'apport initial (25 % du prix TTC)."""
    return round(prix_vehicule * ratio, 0)


def calcul_montant_finance(prix_vehicule: float, apport: Optional[float] = None) -> float:
    """Calcule le montant financé par PCP (75 % du prix TTC)."""
    if apport is None:
        apport = calcul_apport(prix_vehicule)
    return round(prix_vehicule - apport, 0)


def calcul_prime_assurance_mensuelle(
    prix_vehicule: float,
    taux_annuel: float = TAUX_ASSURANCE_ANNUEL
) -> float:
    """Prime d'assurance mensuelle (1,5 % du prix véhicule / an / 12)."""
    return round(prix_vehicule * taux_annuel / 12, 0)


def calcul_frais_gps_mensuel() -> float:
    """Frais GPS SaaS mensuel fixe par véhicule."""
    return TAUX_GPS_MENSUEL


# ─────────────────────────────────────────────────────────────────────────────
# TABLEAU D'AMORTISSEMENT
# ─────────────────────────────────────────────────────────────────────────────

def generer_tableau_amortissement(params: LoanParams) -> LoanSummary:
    """
    Génère le tableau d'amortissement complet d'un prêt PCP.

    Paramètres
    ----------
    params : LoanParams
        Paramètres du prêt.

    Retourne
    --------
    LoanSummary : Résumé complet avec tableau ligne par ligne.

    Exemple
    -------
    >>> p = LoanParams(prix_vehicule=8_500_000, duree_mois=42)
    >>> summary = generer_tableau_amortissement(p)
    >>> print(f"Mensualité: {summary.mensualite_totale:,.0f} XOF")
    """
    apport          = calcul_apport(params.prix_vehicule)
    capital         = calcul_montant_finance(params.prix_vehicule, apport)
    r               = params.teg_annuel / 12
    n               = params.duree_mois
    mensualite_base = calcul_mensualite(capital, params.teg_annuel, n)

    # Services inclus
    prime_assurance = calcul_prime_assurance_mensuelle(params.prix_vehicule) if params.include_assurance else 0.0
    frais_gps       = calcul_frais_gps_mensuel() if params.include_gps else 0.0
    mensualite_totale = mensualite_base + prime_assurance + frais_gps

    tableau: List[AmortizationRow] = []
    capital_restant  = capital
    cumul_interets   = 0.0
    cumul_capital    = 0.0
    date_echeance    = params.date_signature + relativedelta(months=1)

    for mois in range(1, n + 1):
        interets = round(capital_restant * r, 2)
        cap_rembourse = round(mensualite_base - interets, 2)

        # Dernière échéance : ajustement pour éviter résidu d'arrondis
        if mois == n:
            cap_rembourse = capital_restant
            mensualite_base_adj = cap_rembourse + interets
        else:
            mensualite_base_adj = mensualite_base

        capital_restant -= cap_rembourse
        capital_restant  = max(0.0, round(capital_restant, 2))
        cumul_interets  += interets
        cumul_capital   += cap_rembourse

        tableau.append(AmortizationRow(
            mois=mois,
            date_echeance=date_echeance,
            mensualite=round(mensualite_base_adj + prime_assurance + frais_gps, 2),
            interets=interets,
            capital_rembourse=cap_rembourse,
            capital_restant_du=capital_restant,
            cumul_interets=round(cumul_interets, 2),
            cumul_capital=round(cumul_capital, 2),
        ))
        date_echeance += relativedelta(months=1)

    cout_total_credit = round(cumul_interets, 0)
    total_verse       = round(apport + sum(r.mensualite for r in tableau), 0)

    return LoanSummary(
        prix_vehicule=params.prix_vehicule,
        apport=apport,
        montant_finance=capital,
        teg_annuel=params.teg_annuel,
        taux_mensuel=r,
        duree_mois=n,
        mensualite_hors_services=mensualite_base,
        prime_assurance_mensuelle=prime_assurance,
        frais_gps_mensuel=frais_gps,
        mensualite_totale=round(mensualite_totale, 0),
        cout_total_credit=cout_total_credit,
        total_verse_client=total_verse,
        tableau=tableau,
        date_premiere_echeance=tableau[0].date_echeance,
        date_derniere_echeance=tableau[-1].date_echeance,
    )


def afficher_tableau(summary: LoanSummary, max_lignes: int = 48) -> None:
    """Affiche un tableau d'amortissement formaté dans le terminal."""
    print("\n" + "═" * 95)
    print(f"{'TABLEAU D\'AMORTISSEMENT — PHRONESIS CAPITAL PARTNERS':^95}")
    print("═" * 95)
    print(f"  Véhicule       : {summary.prix_vehicule:>15,.0f} XOF")
    print(f"  Apport (25 %)  : {summary.apport:>15,.0f} XOF")
    print(f"  Montant financé: {summary.montant_finance:>15,.0f} XOF")
    print(f"  TEG annuel     : {summary.teg_annuel * 100:.1f} %")
    print(f"  Durée          : {summary.duree_mois} mois")
    print(f"  Mensualité     : {summary.mensualite_totale:>15,.0f} XOF/mois (assurance + GPS inclus)")
    print(f"  Coût total crédit: {summary.cout_total_credit:>13,.0f} XOF")
    print("─" * 95)
    print(f"  {'Mois':>4}  {'Échéance':>12}  {'Mensualité':>14}  {'Intérêts':>12}  {'Capital':>12}  {'Restant dû':>14}")
    print("─" * 95)
    for row in summary.tableau[:max_lignes]:
        print(f"  {row.mois:>4}  {row.date_echeance.strftime('%d/%m/%Y'):>12}  "
              f"{row.mensualite:>14,.0f}  {row.interets:>12,.0f}  "
              f"{row.capital_rembourse:>12,.0f}  {row.capital_restant_du:>14,.0f}")
    print("─" * 95)
    print(f"  {'TOTAL':>4}  {'':>12}  {sum(r.mensualite for r in summary.tableau):>14,.0f}  "
          f"{summary.tableau[-1].cumul_interets:>12,.0f}  "
          f"{summary.tableau[-1].cumul_capital:>12,.0f}  {'0':>14}")
    print("═" * 95 + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# SEUIL DE RENTABILITÉ
# ─────────────────────────────────────────────────────────────────────────────

def calcul_seuil_rentabilite(
    charges_fixes: float,
    charges_variables_ratio: float,
    ca_unitaire_annuel: Optional[float] = None,
    panier_moyen_finance: float = 6_375_000,
    teg: float = TEG_ANNUEL_DEFAULT,
) -> dict:
    """
    Calcule le seuil de rentabilité du fonds PCP.

    Paramètres
    ----------
    charges_fixes : float
        Charges fixes annuelles en XOF.
    charges_variables_ratio : float
        Part des charges variables dans le CA (ex: 0.25 = 25 %).
    ca_unitaire_annuel : float, optional
        CA généré par un contrat actif sur un an.
        Si None, calculé automatiquement depuis le panier moyen et le TEG.
    panier_moyen_finance : float
        Montant moyen financé par PCP par contrat.
    teg : float
        Taux effectif global annuel.

    Retourne
    --------
    dict avec :
        - seuil_ca_xof : CA minimum requis
        - nb_contrats_minimum : nombre de contrats nécessaires
        - tmcv : taux de marge sur coûts variables
        - charges_fixes : charges fixes annuelles
    """
    if ca_unitaire_annuel is None:
        # CA annuel par contrat ≈ encours × TEG
        ca_unitaire_annuel = panier_moyen_finance * teg

    tmcv = 1 - charges_variables_ratio
    if tmcv <= 0:
        raise ValueError("Le taux de marge sur coûts variables doit être positif.")

    seuil_ca = charges_fixes / tmcv
    nb_contrats_min = math.ceil(seuil_ca / ca_unitaire_annuel)

    return {
        "seuil_ca_xof": round(seuil_ca, 0),
        "nb_contrats_minimum": nb_contrats_min,
        "tmcv": round(tmcv * 100, 1),
        "charges_fixes": charges_fixes,
        "ca_unitaire_par_contrat": round(ca_unitaire_annuel, 0),
    }


# ─────────────────────────────────────────────────────────────────────────────
# TRI (TAUX DE RENDEMENT INTERNE) — MÉTHODE NEWTON-RAPHSON
# ─────────────────────────────────────────────────────────────────────────────

def calcul_tri(flux: List[float], precision: float = 1e-7, max_iter: int = 1000) -> float:
    """
    Calcule le Taux de Rendement Interne (TRI) d'une série de flux de trésorerie.

    Paramètres
    ----------
    flux : List[float]
        Flux annuels : flux[0] = investissement initial (négatif),
        flux[1..n] = flux nets positifs (distributions + remboursement capital).
    precision : float
        Convergence souhaitée.
    max_iter : int
        Nombre maximum d'itérations Newton-Raphson.

    Retourne
    --------
    float : TRI annuel (ex: 0.19 = 19 %).

    Exemple
    -------
    >>> flux = [-10_000_000, 1_005_000, 16_442_000, 44_036_000, 104_940_000, 299_202_000]
    >>> tri = calcul_tri(flux)
    >>> print(f"TRI : {tri * 100:.2f} %")
    """
    def van(taux: float) -> float:
        return sum(f / (1 + taux) ** i for i, f in enumerate(flux))

    def van_prime(taux: float) -> float:
        return sum(-i * f / (1 + taux) ** (i + 1) for i, f in enumerate(flux) if i > 0)

    taux = 0.15  # estimation initiale
    for _ in range(max_iter):
        v  = van(taux)
        vp = van_prime(taux)
        if abs(vp) < 1e-12:
            break
        taux_new = taux - v / vp
        if abs(taux_new - taux) < precision:
            return round(taux_new, 6)
        taux = taux_new

    return round(taux, 6)


def calcul_moic(capital_investi: float, valeur_finale: float) -> float:
    """
    Calcule le Multiple on Invested Capital (MOIC).

    MOIC = Valeur finale totale / Capital investi initial

    Exemple
    -------
    >>> calcul_moic(9_000_000, 17_000_000)
    1.89
    """
    if capital_investi <= 0:
        raise ValueError("Capital investi doit être positif.")
    return round(valeur_finale / capital_investi, 2)


def calcul_roe(resultat_net: float, fonds_propres: float) -> float:
    """Return on Equity = Résultat Net / Fonds Propres × 100."""
    return round(resultat_net / fonds_propres * 100, 2)


# ─────────────────────────────────────────────────────────────────────────────
# SIMULATEUR COMPLET (usage terminal / API)
# ─────────────────────────────────────────────────────────────────────────────

def simuler_credit(
    prix_vehicule: float,
    duree_mois: int,
    teg_annuel: float = TEG_ANNUEL_DEFAULT,
    verbose: bool = True,
) -> LoanSummary:
    """
    Point d'entrée principal pour simuler un crédit PCP.

    Paramètres
    ----------
    prix_vehicule : float
        Prix TTC du véhicule en XOF.
    duree_mois : int
        Durée du crédit (36 ou 48 mois).
    teg_annuel : float
        TEG annuel (défaut 22 %).
    verbose : bool
        Afficher le tableau si True.

    Retourne
    --------
    LoanSummary
    """
    params  = LoanParams(prix_vehicule=prix_vehicule, duree_mois=duree_mois, teg_annuel=teg_annuel)
    summary = generer_tableau_amortissement(params)
    if verbose:
        afficher_tableau(summary)
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# POINT D'ENTRÉE
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n🚗 PCP — SIMULATEUR DE CRÉDIT AUTOMOBILE\n")

    # Exemple 1 : Toyota Corolla 2021 — 8 500 000 XOF sur 42 mois
    summary = simuler_credit(prix_vehicule=8_500_000, duree_mois=36)

    # Seuil de rentabilité Phase 1
    sr = calcul_seuil_rentabilite(
        charges_fixes=820_000,
        charges_variables_ratio=0.25,
        panier_moyen_finance=6_375_000,
    )
    print(f"📊 SEUIL DE RENTABILITÉ PHASE 1")
    print(f"   CA minimum requis : {sr['seuil_ca_xof']:,.0f} XOF")
    print(f"   Contrats minimum  : {sr['nb_contrats_minimum']}")
    print(f"   TMCV              : {sr['tmcv']} %\n")

    # TRI estimé PCP sur 7 ans
    flux_7ans = [
        -9_000_000,      # AN0 : investissement Phase 1
        1_005_000,        # AN1
        16_442_000,       # AN2
        44_036_000,       # AN3
        104_940_000,      # AN4
        299_202_000,      # AN5
        554_070_000,      # AN6-7 agrégé
    ]
    tri = calcul_tri(flux_7ans)
    moic = calcul_moic(9_000_000, 9_000_000 + sum(flux_7ans[1:]))
    print(f"📈 KPIs INVESTISSEUR")
    print(f"   TRI estimé 7 ans : {tri * 100:.1f} %")
    print(f"   MOIC estimé      : {moic:.2f}×\n")
