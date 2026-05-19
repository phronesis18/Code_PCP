"""
=============================================================================
PCP — PHRONESIS CAPITAL PARTNERS
Module : recover_bot.py
Description : Séquenceur automatique de recouvrement des créances en retard.
              Gère l'escalade progressive (SMS → WhatsApp → appel → coupe-moteur → terrain).
Auteur : Équipe Technique PCP
Version : 1.0.0
=============================================================================

PROTOCOLE DE RECOUVREMENT PCP :

  J-5  → SMS préventif avant échéance
  J+1  → SMS retard #1
  J+3  → WhatsApp + lien de paiement
  J+7  → SMS retard #2 + appel automatique
  J+10 → WhatsApp formel (ton urgent)
  J+15 → Coupe-moteur ACTIVÉ + SMS notification
  J+20 → Appel gestionnaire humain
  J+30 → Mise en demeure formelle
  J+60 → Récupération physique véhicule
"""

from __future__ import annotations
import json
from dataclasses import dataclass, field
from typing import List, Optional, Callable, Dict
from enum import Enum
from datetime import date, timedelta


# ─────────────────────────────────────────────────────────────────────────────
# ÉNUMÉRATIONS
# ─────────────────────────────────────────────────────────────────────────────

class CanalContact(str, Enum):
    SMS         = "sms"
    WHATSAPP    = "whatsapp"
    APPEL_AUTO  = "appel_automatique"
    APPEL_HUMAN = "appel_gestionnaire"
    EMAIL       = "email"
    COURRIER    = "mise_en_demeure"
    TERRAIN     = "intervention_terrain"


class ActionGPS(str, Enum):
    AUCUNE           = "aucune"
    ALERTE_SEULEMENT = "alerte_seulement"
    COUPE_MOTEUR     = "coupe_moteur"
    REACTIVER        = "reactiver_moteur"


class StatutRecouvrement(str, Enum):
    EN_COURS    = "en_cours"
    REGULARISE  = "régularisé"
    CONTENTIEUX = "contentieux"
    PERTE       = "perte_finale"


# ─────────────────────────────────────────────────────────────────────────────
# DATACLASSES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ActionRecouvrement:
    """Une action de recouvrement planifiée ou exécutée."""
    jour_retard: int          # J+X depuis la date d'échéance
    canal: CanalContact
    message_template: str
    action_gps: ActionGPS = ActionGPS.AUCUNE
    requiert_humain: bool = False
    penalite_xof: float = 0.0
    executee: bool = False
    date_execution: Optional[date] = None
    resultat: Optional[str] = None


@dataclass
class DossierRetard:
    """Dossier d'un contrat en situation de retard de paiement."""
    contrat_id: str
    client_nom: str
    client_telephone: str
    mensualite_due: float       # XOF
    date_echeance: date         # date d'échéance non honorée
    jours_retard: int           # calculé à la date d'aujourd'hui
    capital_restant_du: float   # XOF
    nb_echeances_manquees: int = 1
    montant_total_du: float = 0.0  # mensualités + pénalités cumulées
    gps_actif: bool = True
    coupe_moteur_active: bool = False
    historique_actions: List[ActionRecouvrement] = field(default_factory=list)
    statut: StatutRecouvrement = StatutRecouvrement.EN_COURS

    def __post_init__(self):
        if self.montant_total_du == 0.0:
            self.montant_total_du = self.mensualite_due * self.nb_echeances_manquees


# ─────────────────────────────────────────────────────────────────────────────
# TEMPLATES DE MESSAGES
# ─────────────────────────────────────────────────────────────────────────────

def template_sms(client: str, montant: float, date_ech: date, lien: str = "") -> str:
    return (
        f"[PCP] Bonjour {client}, votre échéance de {montant:,.0f} XOF "
        f"était due le {date_ech.strftime('%d/%m/%Y')}. "
        f"Régularisez maintenant : {lien or 'phronesis-capital.com/payer'} "
        f"ou contactez-nous au +229 97 10 20 30."
    )


def template_whatsapp_urgent(client: str, montant: float, jours: int) -> str:
    return (
        f"⚠️ *PHRONESIS CAPITAL PARTNERS — URGENT*\n\n"
        f"Bonjour {client},\n\n"
        f"Votre compte accuse un retard de *{jours} jours* pour un montant de *{montant:,.0f} XOF*.\n\n"
        f"Sans régularisation dans les 24h, votre véhicule sera immobilisé à distance "
        f"(coupe-moteur GPS).\n\n"
        f"💳 Payer maintenant : https://phronesis-capital.com/payer\n"
        f"📞 Appeler : +229 97 10 20 30\n\n"
        f"*Phronesis Capital Partners — Votre partenaire mobilité*"
    )


def template_mise_en_demeure(client: str, montant: float, contrat_id: str) -> str:
    return (
        f"MISE EN DEMEURE\n\n"
        f"Monsieur/Madame {client},\n\n"
        f"Par la présente, Phronesis Capital Partners (PCP) vous met en demeure "
        f"de régler la somme de {montant:,.0f} XOF due au titre du contrat {contrat_id}, "
        f"dans un délai de 72 heures à compter de la réception de ce message.\n\n"
        f"À défaut, PCP procédera à la récupération du véhicule, propriété du fonds, "
        f"sans préjudice de toute action judiciaire pour le recouvrement du solde.\n\n"
        f"PCP — Service Recouvrement"
    )


# ─────────────────────────────────────────────────────────────────────────────
# SÉQUENCEUR D'ACTIONS
# ─────────────────────────────────────────────────────────────────────────────

TAUX_PENALITE_PAR_MOIS = 0.02  # 2 % du montant dû par mois de retard


def calculer_penalites(montant_du: float, jours_retard: int) -> float:
    """
    Calcule les pénalités de retard.
    Taux : 2 % du montant dû par mois de retard.
    """
    mois_retard = jours_retard / 30
    return round(montant_du * TAUX_PENALITE_PAR_MOIS * mois_retard, 0)


def generer_sequence_actions(dossier: DossierRetard) -> List[ActionRecouvrement]:
    """
    Génère la séquence complète d'actions de recouvrement pour un dossier.
    Les actions déjà passées (jours_retard > seuil) sont marquées comme dues.

    Paramètres
    ----------
    dossier : DossierRetard
        Dossier du contrat en retard.

    Retourne
    --------
    List[ActionRecouvrement] : Séquence ordonnée d'actions.
    """
    j       = dossier.jours_retard
    client  = dossier.client_nom
    montant = dossier.montant_total_du
    ech     = dossier.date_echeance
    cid     = dossier.contrat_id

    sequence: List[ActionRecouvrement] = [
        ActionRecouvrement(
            jour_retard=-5,
            canal=CanalContact.SMS,
            message_template=f"[PCP] Rappel : votre échéance de {montant:,.0f} XOF est dans 5 jours. Préparez votre paiement. phronesis-capital.com",
            penalite_xof=0,
        ),
        ActionRecouvrement(
            jour_retard=1,
            canal=CanalContact.SMS,
            message_template=template_sms(client, montant, ech),
            penalite_xof=0,
        ),
        ActionRecouvrement(
            jour_retard=3,
            canal=CanalContact.WHATSAPP,
            message_template=template_sms(client, montant, ech, "phronesis-capital.com/payer"),
            penalite_xof=0,
        ),
        ActionRecouvrement(
            jour_retard=7,
            canal=CanalContact.SMS,
            message_template=f"[PCP URGENT] {client} — {montant:,.0f} XOF en retard depuis 7 jours. Pénalités appliquées. Réglez sur phronesis-capital.com/payer",
            penalite_xof=calculer_penalites(montant, 7),
        ),
        ActionRecouvrement(
            jour_retard=10,
            canal=CanalContact.WHATSAPP,
            message_template=template_whatsapp_urgent(client, montant, 10),
            action_gps=ActionGPS.ALERTE_SEULEMENT,
            penalite_xof=calculer_penalites(montant, 10),
        ),
        ActionRecouvrement(
            jour_retard=15,
            canal=CanalContact.SMS,
            message_template=f"[PCP] {client} — Coupe-moteur activé. Votre véhicule est immobilisé. Réglez {montant:,.0f} XOF pour le débloquer : +229 97 10 20 30",
            action_gps=ActionGPS.COUPE_MOTEUR,
            penalite_xof=calculer_penalites(montant, 15),
        ),
        ActionRecouvrement(
            jour_retard=20,
            canal=CanalContact.APPEL_HUMAN,
            message_template=f"Appeler {client} ({dossier.client_telephone}) — Retard {j}j — Proposer échéancier si situation temporaire",
            requiert_humain=True,
            penalite_xof=calculer_penalites(montant, 20),
        ),
        ActionRecouvrement(
            jour_retard=30,
            canal=CanalContact.COURRIER,
            message_template=template_mise_en_demeure(client, montant, cid),
            requiert_humain=True,
            penalite_xof=calculer_penalites(montant, 30),
        ),
        ActionRecouvrement(
            jour_retard=60,
            canal=CanalContact.TERRAIN,
            message_template=f"RÉCUPÉRATION PHYSIQUE — {cid} — {client} — Déployer équipe terrain pour récupérer le véhicule",
            action_gps=ActionGPS.COUPE_MOTEUR,
            requiert_humain=True,
            penalite_xof=calculer_penalites(montant, 60),
        ),
    ]

    # Marquer les actions passées comme dues
    today = date.today()
    for action in sequence:
        seuil_date = dossier.date_echeance + timedelta(days=action.jour_retard)
        if today >= seuil_date:
            action.executee = False  # pas encore envoyée mais due

    return sequence


def actions_requises_maintenant(dossier: DossierRetard) -> List[ActionRecouvrement]:
    """
    Filtre les actions qui doivent être exécutées MAINTENANT
    (seuil de jours de retard atteint, action pas encore exécutée).
    """
    sequence = generer_sequence_actions(dossier)
    return [
        a for a in sequence
        if a.jour_retard <= dossier.jours_retard and not a.executee
    ]


def prochaine_action(dossier: DossierRetard) -> Optional[ActionRecouvrement]:
    """Retourne la prochaine action planifiée non encore exécutée."""
    sequence = generer_sequence_actions(dossier)
    for action in sorted(sequence, key=lambda a: a.jour_retard):
        if action.jour_retard > dossier.jours_retard and not action.executee:
            return action
    return None


# ─────────────────────────────────────────────────────────────────────────────
# INTERFACE DE SIMULATION / LOG
# ─────────────────────────────────────────────────────────────────────────────

def afficher_plan_recouvrement(dossier: DossierRetard) -> None:
    """Affiche le plan de recouvrement d'un dossier."""
    sequence = generer_sequence_actions(dossier)
    action_imm = actions_requises_maintenant(dossier)
    proch = prochaine_action(dossier)
    penalites = calculer_penalites(dossier.montant_total_du, dossier.jours_retard)

    print("\n" + "═" * 75)
    print(f"{'PLAN DE RECOUVREMENT — PCP RECOVER BOT':^75}")
    print("═" * 75)
    print(f"  Contrat       : {dossier.contrat_id}")
    print(f"  Client        : {dossier.client_nom}")
    print(f"  Retard actuel : {dossier.jours_retard} jours")
    print(f"  Montant dû    : {dossier.montant_total_du:,.0f} XOF")
    print(f"  Pénalités     : {penalites:,.0f} XOF")
    print(f"  Total à régler: {dossier.montant_total_du + penalites:,.0f} XOF")
    print(f"  GPS/Coupe-mot.: {'🔴 ACTIVÉ' if dossier.coupe_moteur_active else '🟢 Normal'}")
    print("─" * 75)
    print(f"  {'J+':>4}  {'Canal':<22}  {'GPS':<18}  {'Humain':>8}  {'Pénalités':>12}")
    print("─" * 75)

    CANAL_ICONS = {
        CanalContact.SMS: "📱 SMS",
        CanalContact.WHATSAPP: "💬 WhatsApp",
        CanalContact.APPEL_AUTO: "🤖 Appel auto",
        CanalContact.APPEL_HUMAN: "👤 Appel humain",
        CanalContact.EMAIL: "📧 Email",
        CanalContact.COURRIER: "📨 Mise en demeure",
        CanalContact.TERRAIN: "🚗 Terrain",
    }
    GPS_LABELS = {
        ActionGPS.AUCUNE: "—",
        ActionGPS.ALERTE_SEULEMENT: "📍 Alerte",
        ActionGPS.COUPE_MOTEUR: "🔴 Coupe-moteur",
        ActionGPS.REACTIVER: "🟢 Réactiver",
    }

    for action in sequence:
        due = "⚡ DÛ" if action.jour_retard <= dossier.jours_retard else "  "
        hum = "OUI" if action.requiert_humain else "auto"
        print(f"  {due}{action.jour_retard:>+3}  {CANAL_ICONS.get(action.canal, action.canal.value):<22}  "
              f"{GPS_LABELS.get(action.action_gps, '—'):<18}  {hum:>8}  {action.penalite_xof:>12,.0f}")

    print("─" * 75)
    if action_imm:
        print(f"\n  ⚡ ACTIONS IMMÉDIATES REQUISES ({len(action_imm)}) :")
        for a in action_imm:
            print(f"     → {a.canal.value.upper()} : {a.message_template[:80]}...")
    if proch:
        jours_avant = proch.jour_retard - dossier.jours_retard
        print(f"\n  ⏱  PROCHAINE ACTION dans {jours_avant} jour(s) : {proch.canal.value}")
    print("═" * 75 + "\n")


def rapport_recouvrement_portefeuille(dossiers: List[DossierRetard]) -> None:
    """Rapport agrégé du recouvrement sur tout le portefeuille."""
    total_du = sum(d.montant_total_du for d in dossiers)
    coupes   = sum(1 for d in dossiers if d.coupe_moteur_active)
    humains  = sum(1 for d in dossiers if d.jours_retard >= 20)

    print(f"\n📋 RAPPORT RECOUVREMENT PCP — {date.today().strftime('%d/%m/%Y')}")
    print(f"   Dossiers en retard  : {len(dossiers)}")
    print(f"   Montant total dû    : {total_du:,.0f} XOF")
    print(f"   Coupe-moteur actifs : {coupes}")
    print(f"   Intervention humaine: {humains}")
    print()
    for d in sorted(dossiers, key=lambda x: x.jours_retard, reverse=True):
        stage = "🔴" if d.jours_retard >= 30 else "🟠" if d.jours_retard >= 15 else "🟡"
        print(f"   {stage} {d.contrat_id:<12} {d.client_nom:<20} J+{d.jours_retard:<3} {d.montant_total_du:>12,.0f} XOF")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# POINT D'ENTRÉE
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("🤖 PCP — RECOVER BOT\n")

    dossier_j18 = DossierRetard(
        contrat_id="PCP-2025-0042",
        client_nom="DOSSOU Eric",
        client_telephone="+229 97 55 66 77",
        mensualite_due=216_000,
        date_echeance=date.today() - timedelta(days=18),
        jours_retard=18,
        capital_restant_du=5_800_000,
        gps_actif=True,
        coupe_moteur_active=True,
    )

    dossier_j8 = DossierRetard(
        contrat_id="PCP-2025-0051",
        client_nom="BADA Sylvie",
        client_telephone="+229 95 33 44 55",
        mensualite_due=162_500,
        date_echeance=date.today() - timedelta(days=8),
        jours_retard=8,
        capital_restant_du=4_200_000,
        gps_actif=True,
        coupe_moteur_active=False,
    )

    afficher_plan_recouvrement(dossier_j18)
    afficher_plan_recouvrement(dossier_j8)
    rapport_recouvrement_portefeuille([dossier_j18, dossier_j8])
