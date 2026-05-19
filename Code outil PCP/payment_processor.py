from __future__ import annotations
"""
=============================================================================
Module : payment_processor.py
Description : Traitement des paiements Mobile Money (MTN MoMo / Moov Africa).
              Prélèvement automatique, réconciliation, webhook.
Auteur : Équipe Technique PCP | Version : 1.0.0
=============================================================================
"""
from dataclasses import dataclass, field
from typing import Optional, Dict
from enum import Enum
from datetime import datetime
import hashlib
import json
import uuid


class StatutPaiement(str, Enum):
    EN_ATTENTE  = "pending"
    SUCCES      = "success"
    ECHEC       = "failed"
    EXPIRE      = "expired"
    REMBOURSE   = "refunded"


class OperateurMoMo(str, Enum):
    MTN         = "mtn_momo"
    MOOV        = "moov_africa"
    VIREMENT    = "virement_bancaire"


@dataclass
class OrdrePrelevement:
    """Ordre de prélèvement Mobile Money."""
    id_ordre: str = field(default_factory=lambda: f"PCP-PAY-{uuid.uuid4().hex[:8].upper()}")
    contrat_id: str = ""
    client_nom: str = ""
    telephone: str = ""
    montant_xof: float = 0.0
    operateur: OperateurMoMo = OperateurMoMo.MTN
    description: str = ""
    statut: StatutPaiement = StatutPaiement.EN_ATTENTE
    date_creation: datetime = field(default_factory=datetime.now)
    date_execution: Optional[datetime] = None
    reference_operateur: Optional[str] = None
    message_erreur: Optional[str] = None


@dataclass
class ResultatPaiement:
    """Résultat d'un paiement traité."""
    id_ordre: str
    statut: StatutPaiement
    montant_xof: float
    frais_xof: float
    montant_net_xof: float
    reference_operateur: str
    horodatage: datetime
    message: str


def calculer_frais_momo(montant: float, operateur: OperateurMoMo) -> float:
    """
    Calcule les frais de transaction Mobile Money.
    Barème Bénin 2025 (estimé) :
    - MTN MoMo : 1 % du montant (min 100 XOF, max 5 000 XOF)
    - Moov Africa : 0,8 % (min 100 XOF, max 4 000 XOF)
    - Virement bancaire : forfait 500 XOF
    """
    if operateur == OperateurMoMo.VIREMENT:
        return 500.0
    elif operateur == OperateurMoMo.MTN:
        return max(100, min(5_000, montant * 0.01))
    elif operateur == OperateurMoMo.MOOV:
        return max(100, min(4_000, montant * 0.008))
    return 0.0


def creer_ordre_prelevement(
    contrat_id: str,
    client_nom: str,
    telephone: str,
    mensualite_xof: float,
    operateur: OperateurMoMo,
    mois_reference: str,
) -> OrdrePrelevement:
    """Crée un ordre de prélèvement pour une mensualité PCP."""
    return OrdrePrelevement(
        contrat_id=contrat_id,
        client_nom=client_nom,
        telephone=telephone,
        montant_xof=mensualite_xof,
        operateur=operateur,
        description=f"Mensualité PCP — Contrat {contrat_id} — {mois_reference}",
    )


def simuler_prelevement(ordre: OrdrePrelevement) -> ResultatPaiement:
    """
    Simule l'appel à l'API Mobile Money et retourne le résultat.

    En production : remplacer par l'appel API Kkiapay (MTN + Moov Bénin) :
        POST https://api.kkiapay.me/api/v1/payments
        Headers: x-private-key: <PCP_API_KEY>
        Body: { phone, amount, reason, sandbox: false }

    Retourne
    --------
    ResultatPaiement
    """
    frais = calculer_frais_momo(ordre.montant_xof, ordre.operateur)
    net   = ordre.montant_xof - frais
    ref   = hashlib.md5(f"{ordre.id_ordre}{ordre.telephone}".encode()).hexdigest()[:12].upper()

    # Simulation : 95 % de succès
    import random
    succes = random.random() < 0.95

    statut  = StatutPaiement.SUCCES if succes else StatutPaiement.ECHEC
    message = "Paiement effectué avec succès." if succes else "Échec du prélèvement. Solde insuffisant ou numéro invalide."

    ordre.statut = statut
    ordre.date_execution = datetime.now()
    ordre.reference_operateur = ref if succes else None

    return ResultatPaiement(
        id_ordre=ordre.id_ordre,
        statut=statut,
        montant_xof=ordre.montant_xof,
        frais_xof=frais,
        montant_net_xof=net if succes else 0.0,
        reference_operateur=ref if succes else "—",
        horodatage=datetime.now(),
        message=message,
    )


def traiter_lot_prelevements(ordres: list) -> Dict:
    """
    Traite un lot de prélèvements mensuels.
    En production : utiliser un job scheduler (Celery / APScheduler).

    Retourne
    --------
    Dict : Rapport de traitement (succès, échecs, montant total collecté).
    """
    succes, echecs, montant_total = [], [], 0.0

    for ordre in ordres:
        resultat = simuler_prelevement(ordre)
        if resultat.statut == StatutPaiement.SUCCES:
            succes.append(resultat)
            montant_total += resultat.montant_net_xof
        else:
            echecs.append(resultat)

    return {
        "date_traitement": datetime.now().isoformat(),
        "nb_ordres": len(ordres),
        "nb_succes": len(succes),
        "nb_echecs": len(echecs),
        "montant_collecte_xof": round(montant_total, 0),
        "taux_succes_pct": round(len(succes) / max(len(ordres), 1) * 100, 1),
        "echecs_contrats": [e.id_ordre for e in echecs],
    }


def afficher_rapport_paiements(rapport: Dict) -> None:
    """Affiche le rapport de traitement des prélèvements."""
    print(f"\n💳 RAPPORT PRÉLÈVEMENTS PCP — {rapport['date_traitement'][:10]}")
    print(f"   Ordres traités    : {rapport['nb_ordres']}")
    print(f"   Succès            : {rapport['nb_succes']} ({rapport['taux_succes_pct']} %)")
    print(f"   Échecs            : {rapport['nb_echecs']}")
    print(f"   Montant collecté  : {rapport['montant_collecte_xof']:,.0f} XOF")
    if rapport["echecs_contrats"]:
        print(f"   Contrats en échec : {', '.join(rapport['echecs_contrats'])}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# DÉMOS ANALYTICS + PAIEMENTS
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":

    # Dashboard Phase 1
    kpi = generer_kpis(
        encours=38_400_000, nb_actifs=6, nb_total=6,
        capital_leve=9_000_000, npl_pct=0.0, taux_remb=100.0,
        lgd_pct=0.0, ca_ytd=1_650_000, rne_ytd=250_000,
        fonds_propres=9_000_000, gps_actif_pct=100.0, nb_coupes=1,
        tri=18.5, moic=1.03, distrib_prochain=125_000,
        date_distrib=date(2025, 7, 15),
    )
    afficher_dashboard(kpi)

    # Projection encours Phase 1 → Phase 2
    print("📈 PROJECTION ENCOURS (12 mois)")
    proj = projection_encours(38_400_000, 2, 6_375_000, 0.22/12, 6)
    print(f"   {'Mois':>4}  {'Encours':>18}  {'Revenu/mois':>14}")
    for p in proj:
        print(f"   {p['mois']:>4}  {p['encours_xof']:>18,.0f}  {p['revenu_mensuel_xof']:>14,.0f}")

    # Prélèvement mensuel lot
    print("\n💳 SIMULATION PRÉLÈVEMENTS MENSUELS")
    ordres = [
        creer_ordre_prelevement(f"PCP-00{i}", f"Client {i}", f"+22997{i*11111:06d}", 216_000, OperateurMoMo.MTN, "Février 2025")
        for i in range(1, 7)
    ]
    rapport = traiter_lot_prelevements(ordres)
    afficher_rapport_paiements(rapport)