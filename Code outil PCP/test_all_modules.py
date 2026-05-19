"""
=============================================================================
PCP — PHRONESIS CAPITAL PARTNERS
Module : tests/test_all_modules.py
Description : Tests unitaires pour tous les modules Python PCP.
              Exécuter avec : python -m pytest tests/ -v
Auteur : Équipe Technique PCP | Version : 1.0.0
=============================================================================
"""

import sys
import os
import math
from datetime import date, timedelta

# Ajout des chemins
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'ai'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'ops'))


# ════════════════════════════════════════════════════════════════════════════
# TESTS — loan_calculator
# ════════════════════════════════════════════════════════════════════════════

def test_calcul_mensualite_standard():
    """Mensualité standard : 6 375 000 XOF / 22 % / 42 mois ≈ 216 000 XOF."""
    from loan_calculator import calcul_mensualite
    m = calcul_mensualite(6_375_000, 0.22, 42)
    assert 210_000 <= m <= 220_000, f"Mensualité attendue ~216 000 XOF, obtenu {m}"


def test_calcul_mensualite_taux_zero():
    """Si taux = 0, mensualité = capital / durée."""
    from loan_calculator import calcul_mensualite
    m = calcul_mensualite(1_000_000, 0.0, 10)
    assert abs(m - 100_000) < 1, f"Attendu 100 000, obtenu {m}"


def test_apport_25_pourcent():
    """Apport = 25 % du prix TTC."""
    from loan_calculator import calcul_apport
    assert calcul_apport(8_500_000) == 2_125_000


def test_montant_finance_75_pourcent():
    """Montant financé = 75 % du prix."""
    from loan_calculator import calcul_montant_finance
    assert calcul_montant_finance(8_500_000) == 6_375_000


def test_tableau_amortissement_solde_zero():
    """Le capital restant dû doit être 0 après la dernière mensualité."""
    from loan_calculator import LoanParams, generer_tableau_amortissement
    params = LoanParams(prix_vehicule=4_500_000, duree_mois=36)
    summary = generer_tableau_amortissement(params)
    assert summary.tableau[-1].capital_restant_du == 0.0, "Capital restant dû ≠ 0 en fin de contrat."


def test_tableau_longueur_correcte():
    """Le tableau doit avoir exactement N lignes (durée en mois)."""
    from loan_calculator import LoanParams, generer_tableau_amortissement
    for duree in [36, 48]:
        params = LoanParams(prix_vehicule=6_000_000, duree_mois=duree)
        summary = generer_tableau_amortissement(params)
        assert len(summary.tableau) == duree, f"Tableau {len(summary.tableau)} lignes pour {duree} mois attendues."


def test_tableau_cumul_interets_positif():
    """Les intérêts cumulés doivent être positifs."""
    from loan_calculator import LoanParams, generer_tableau_amortissement
    params = LoanParams(prix_vehicule=8_500_000, duree_mois=42)
    summary = generer_tableau_amortissement(params)
    assert summary.tableau[-1].cumul_interets > 0


def test_duree_invalide_leve_erreur():
    """Durée non autorisée doit lever une ValueError."""
    from loan_calculator import LoanParams
    try:
        LoanParams(prix_vehicule=5_000_000, duree_mois=24)
        assert False, "Doit lever ValueError"
    except ValueError:
        pass


def test_seuil_rentabilite_calcul():
    """Seuil = CF / TMCV."""
    from loan_calculator import calcul_seuil_rentabilite
    sr = calcul_seuil_rentabilite(charges_fixes=820_000, charges_variables_ratio=0.25)
    assert abs(sr["seuil_ca_xof"] - 820_000 / 0.75) < 1000


def test_tri_calcul():
    """TRI doit être compris entre 0 % et 100 % pour des flux réalistes."""
    from loan_calculator import calcul_tri
    flux = [-100_000, 15_000, 20_000, 25_000, 30_000, 35_000]
    tri = calcul_tri(flux)
    assert 0.0 < tri < 1.0, f"TRI inattendu : {tri}"


def test_moic_calcul():
    """MOIC = valeur finale / capital investi."""
    from loan_calculator import calcul_moic
    assert calcul_moic(10_000_000, 19_000_000) == 1.90


def test_roe_calcul():
    """ROE = RN / FP × 100."""
    from loan_calculator import calcul_roe
    assert abs(calcul_roe(1_005_000, 9_000_000) - 11.17) < 0.1


# ════════════════════════════════════════════════════════════════════════════
# TESTS — scoring_engine
# ════════════════════════════════════════════════════════════════════════════

def _profil_standard():
    from scoring_engine import ProfilClient, TypeEmploi
    return ProfilClient(
        nom="TEST", prenom="Client", age=38,
        type_emploi=TypeEmploi.FONCTIONNAIRE,
        anciennete_mois=42, revenu_net_mensuel=285_000,
        employeur="Ministère", contrat_cdi=True,
        charges_mensuelles_actuelles=0, montant_mensualite_pcp=100_000,
        prix_vehicule=8_500_000, apport_verse=2_125_000, duree_mois=42,
        solde_moyen_momo_3mois=380_000, nb_transactions_momo_mensuel=14,
        epargne_observee=45_000, incident_paiement_24mois=False,
        nb_credits_actifs=0, score_bceao=720,
    )


def test_scoring_approbation_auto():
    """Un fonctionnaire avec bon profil doit être approuvé automatiquement."""
    from scoring_engine import scorer_client, DecisionCredit
    result = scorer_client(_profil_standard())
    assert result.decision == DecisionCredit.AUTO_APPROUVE, f"Attendu AUTO_APPROUVÉ, obtenu {result.decision}"
    assert result.score_total >= 650


def test_scoring_refus_incident():
    """Un profil avec incident de paiement doit être refusé."""
    from scoring_engine import scorer_client, DecisionCredit, ProfilClient, TypeEmploi
    profil = ProfilClient(
        nom="REFUSE", prenom="Test", age=35,
        type_emploi=TypeEmploi.SALARIE_FORMEL,
        anciennete_mois=20, revenu_net_mensuel=200_000,
        employeur="PME", contrat_cdi=True,
        charges_mensuelles_actuelles=20_000, montant_mensualite_pcp=80_000,
        prix_vehicule=4_000_000, apport_verse=1_000_000, duree_mois=48,
        incident_paiement_24mois=True,
    )
    result = scorer_client(profil)
    assert result.decision == DecisionCredit.REFUSE


def test_scoring_refus_taux_endettement():
    """Taux endettement > 40 % → refus."""
    from scoring_engine import scorer_client, DecisionCredit, ProfilClient, TypeEmploi
    profil = ProfilClient(
        nom="ENDET", prenom="Test", age=30,
        type_emploi=TypeEmploi.SALARIE_FORMEL,
        anciennete_mois=18, revenu_net_mensuel=120_000,
        employeur="PME", contrat_cdi=True,
        charges_mensuelles_actuelles=60_000,
        montant_mensualite_pcp=90_000,  # total = 150 000 / 120 000 = 125 %
        prix_vehicule=4_500_000, apport_verse=1_125_000, duree_mois=48,
    )
    result = scorer_client(profil)
    assert result.decision == DecisionCredit.REFUSE


def test_score_dans_plage():
    """Le score doit toujours être entre 300 et 850."""
    from scoring_engine import scorer_client
    result = scorer_client(_profil_standard())
    assert 300 <= result.score_total <= 850


def test_shap_somme_100():
    """Les valeurs SHAP doivent sommer à ~100 %."""
    from scoring_engine import scorer_client
    result = scorer_client(_profil_standard())
    if result.explications_shap:
        total = sum(result.explications_shap.values())
        assert abs(total - 100.0) < 1.0, f"Somme SHAP = {total:.1f} % (attendu ~100 %)"


def test_criteres_eliminatoires_age():
    """Âge insuffisant → refus immédiat."""
    from scoring_engine import ProfilClient, TypeEmploi, verifier_criteres_eliminatoires
    profil = ProfilClient(
        nom="JEUNE", prenom="Test", age=19,
        type_emploi=TypeEmploi.FONCTIONNAIRE,
        anciennete_mois=14, revenu_net_mensuel=150_000,
        employeur="Ministère", montant_mensualite_pcp=50_000,
        prix_vehicule=3_000_000, apport_verse=750_000, duree_mois=36,
    )
    violations = verifier_criteres_eliminatoires(profil)
    assert any("âge" in v.lower() or "Âge" in v for v in violations)


# ════════════════════════════════════════════════════════════════════════════
# TESTS — risk_metrics
# ════════════════════════════════════════════════════════════════════════════

def test_expected_loss_formule():
    """EL = PD × LGD × EAD."""
    from risk_metrics import calcul_expected_loss
    el = calcul_expected_loss(encours=10_000_000, pd=0.08, lgd=0.15)
    assert el == round(10_000_000 * 0.08 * 0.15, 0)


def test_lgd_gps_actif_inferieur_a_sans_gps():
    """LGD avec GPS doit être inférieur au LGD sans GPS."""
    from risk_metrics import calcul_lgd_contrat
    _, _, lgd_avec_gps   = calcul_lgd_contrat(5_800_000, 6_000_000, gps_actif=True)
    _, _, lgd_sans_gps   = calcul_lgd_contrat(5_800_000, 6_000_000, gps_actif=False)
    assert lgd_avec_gps < lgd_sans_gps, "GPS actif doit réduire le LGD."


def test_lgd_never_negatif():
    """LGD ne peut pas être négatif."""
    from risk_metrics import calcul_lgd_contrat
    _, lgd_xof, lgd_pct = calcul_lgd_contrat(1_000_000, 5_000_000)
    assert lgd_xof >= 0 and lgd_pct >= 0


def test_stress_test_trois_scenarios():
    """Le stress test doit retourner exactement 3 scénarios."""
    from risk_metrics import stress_test
    results = stress_test(encours=38_400_000)
    assert len(results) == 3


def test_scenario_base_viable():
    """Le scénario BASE doit être financièrement viable."""
    from risk_metrics import stress_test, ScenarioStress
    results = stress_test(encours=100_000_000, charges_fixes_annuelles=5_000_000)
    base = next(r for r in results if r.scenario == ScenarioStress.BASE)
    assert base.fonds_viable, "Le scénario BASE doit être viable."


def test_metriques_portefeuille_vide():
    """Un portefeuille vide doit lever une ValueError."""
    from risk_metrics import calculer_metriques_portefeuille
    try:
        calculer_metriques_portefeuille([])
        assert False, "Doit lever ValueError"
    except ValueError:
        pass


# ════════════════════════════════════════════════════════════════════════════
# TESTS — recover_bot
# ════════════════════════════════════════════════════════════════════════════

def test_penalites_croissantes():
    """Les pénalités doivent augmenter avec le nombre de jours."""
    from recover_bot import calculer_penalites
    p10 = calculer_penalites(200_000, 10)
    p30 = calculer_penalites(200_000, 30)
    assert p30 > p10, "Pénalités à J+30 doivent être > pénalités à J+10."


def test_coupe_moteur_dans_sequence_j15():
    """L'action coupe-moteur doit apparaître dans la séquence à J+15."""
    from recover_bot import DossierRetard, generer_sequence_actions, ActionGPS
    dossier = DossierRetard(
        contrat_id="TEST-001", client_nom="Test", client_telephone="+229",
        mensualite_due=200_000, date_echeance=date.today() - timedelta(days=20),
        jours_retard=20, capital_restant_du=5_000_000,
    )
    sequence = generer_sequence_actions(dossier)
    coupe = [a for a in sequence if a.action_gps == ActionGPS.COUPE_MOTEUR]
    assert len(coupe) >= 1, "L'action coupe-moteur doit être dans la séquence."


def test_actions_requises_j18():
    """À J+18, plusieurs actions doivent être requises (incluant coupe-moteur)."""
    from recover_bot import DossierRetard, actions_requises_maintenant
    dossier = DossierRetard(
        contrat_id="TEST-002", client_nom="Test", client_telephone="+229",
        mensualite_due=200_000, date_echeance=date.today() - timedelta(days=18),
        jours_retard=18, capital_restant_du=5_000_000, coupe_moteur_active=True,
    )
    actions = actions_requises_maintenant(dossier)
    assert len(actions) >= 3, f"Attendu ≥ 3 actions à J+18, obtenu {len(actions)}"


# ════════════════════════════════════════════════════════════════════════════
# TESTS — gps_fraud_eligibility
# ════════════════════════════════════════════════════════════════════════════

def test_est_dans_benin_cotonou():
    """Les coordonnées de Cotonou doivent être dans le Bénin."""
    b = {"lat_min":6.22,"lat_max":12.41,"lon_min":0.77,"lon_max":3.85}
    lat,lon = 6.3556, 2.4380
    assert b["lat_min"]<=lat<=b["lat_max"] and b["lon_min"]<=lon<=b["lon_max"], "Cotonou doit être dans le Bénin."


def test_hors_benin_france():
    """Les coordonnées de Paris doivent être hors du Bénin."""
    b = {"lat_min":6.22,"lat_max":12.41,"lon_min":0.77,"lon_max":3.85}
    lat,lon = 48.8566, 2.3522
    assert not (b["lat_min"]<=lat<=b["lat_max"] and b["lon_min"]<=lon<=b["lon_max"]), "Paris ne doit pas être dans le Bénin."


def test_distance_haversine():
    """Distance Cotonou-Parakou ≈ 400 km."""
    import math
    def haversine(lat1,lon1,lat2,lon2):
        R=6371;ph1,ph2=math.radians(lat1),math.radians(lat2)
        dph=math.radians(lat2-lat1);dl=math.radians(lon2-lon1)
        a=math.sin(dph/2)**2+math.cos(ph1)*math.cos(ph2)*math.sin(dl/2)**2
        return R*2*math.atan2(math.sqrt(a),math.sqrt(1-a))
    dist = haversine(6.3556,2.4380,9.3370,2.6280)
    assert 300 <= dist <= 450, f"Distance Cotonou-Parakou ≈ 400 km, obtenu {dist:.0f} km" 


def test_fraud_detector_bulletin_ok():
    """Un bulletin valide doit avoir un risque FAIBLE ou MODÉRÉ."""
    from fraud_detector import analyser_document, TypeDocument, RisqueFraude
    bulletin = {
        "nom_employe": "ADJOVI Jean", "nom_employeur": "Ministère Education",
        "revenu_net": "285000", "periode": "janvier 2025",
        "cnss": "BJ-CNSS-123456", "cachet_detecte": "oui",
    }
    result = analyser_document(TypeDocument.BULLETIN_SALAIRE, bulletin, 285_000, 380_000)
    assert result.risque_fraude in [RisqueFraude.FAIBLE, RisqueFraude.MODERE]


def test_fraud_detector_sans_cachet():
    """Un bulletin sans cachet doit être classé MODÉRÉ ou ÉLEVÉ."""
    from fraud_detector import analyser_document, TypeDocument, RisqueFraude
    bulletin = {
        "nom_employe": "X", "nom_employeur": "Y",
        "revenu_net": "200000", "periode": "jan 2025",
        "cnss": "MAUVAIS-FORMAT", "cachet_detecte": "non",
    }
    result = analyser_document(TypeDocument.BULLETIN_SALAIRE, bulletin, 200_000, 50_000)
    assert result.risque_fraude != RisqueFraude.FAIBLE


def test_eligibilite_client_ok():
    """Un client standard PCP doit être éligible."""
    from eligibility_checker import verifier_eligibilite
    eligible, _, msg = verifier_eligibilite(
        revenu_net=285_000, anciennete_mois=42,
        taux_endettement_apres_pcp=0.358, apport_verse=2_125_000,
        prix_vehicule=8_500_000, age=38, duree_mois=42,
    )
    assert eligible, f"Client doit être éligible : {msg}"


def test_eligibilite_client_trop_jeune():
    """Un client de 19 ans ne doit pas être éligible."""
    from eligibility_checker import verifier_eligibilite
    eligible, _, _ = verifier_eligibilite(
        revenu_net=200_000, anciennete_mois=18,
        taux_endettement_apres_pcp=0.30, apport_verse=1_000_000,
        prix_vehicule=4_000_000, age=19, duree_mois=36,
    )
    assert not eligible


def test_eligibilite_incident_bceao():
    """Un client avec incident BCEAO ne doit pas être éligible."""
    from eligibility_checker import verifier_eligibilite
    eligible, _, _ = verifier_eligibilite(
        revenu_net=300_000, anciennete_mois=30,
        taux_endettement_apres_pcp=0.30, apport_verse=1_500_000,
        prix_vehicule=6_000_000, age=35, duree_mois=42,
        incident_bceao=True,
    )
    assert not eligible


# ════════════════════════════════════════════════════════════════════════════
# TESTS — analytics_payment
# ════════════════════════════════════════════════════════════════════════════

def test_frais_momo_mtn_plafond():
    """Les frais MTN MoMo doivent être plafonnés à 5 000 XOF."""
    from payment_processor import calculer_frais_momo, OperateurMoMo
    frais = calculer_frais_momo(10_000_000, OperateurMoMo.MTN)
    assert frais <= 5_000


def test_frais_virement_forfait():
    """Virement bancaire = forfait 500 XOF."""
    from payment_processor import calculer_frais_momo, OperateurMoMo
    assert calculer_frais_momo(500_000, OperateurMoMo.VIREMENT) == 500.0


def test_ordre_prelevement_id_unique():
    """Deux ordres distincts doivent avoir des IDs différents."""
    from payment_processor import creer_ordre_prelevement, OperateurMoMo
    o1 = creer_ordre_prelevement("PCP-001", "A", "+229", 216_000, OperateurMoMo.MTN, "Fév")
    o2 = creer_ordre_prelevement("PCP-002", "B", "+229", 216_000, OperateurMoMo.MTN, "Fév")
    assert o1.id_ordre != o2.id_ordre


def test_projection_encours_croissant():
    """L'encours doit croître si de nouveaux contrats sont signés."""
    from portfolio_analytics import projection_encours
    proj = projection_encours(10_000_000, 2, 6_375_000, 0.22/12, 6)
    assert proj[-1]["encours_xof"] > proj[0]["encours_xof"]


# ════════════════════════════════════════════════════════════════════════════
# RUNNER MANUEL (sans pytest)
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import traceback

    tests = [
        # loan_calculator
        test_calcul_mensualite_standard,
        test_calcul_mensualite_taux_zero,
        test_apport_25_pourcent,
        test_montant_finance_75_pourcent,
        test_tableau_amortissement_solde_zero,
        test_tableau_longueur_correcte,
        test_tableau_cumul_interets_positif,
        test_duree_invalide_leve_erreur,
        test_seuil_rentabilite_calcul,
        test_tri_calcul,
        test_moic_calcul,
        test_roe_calcul,
        # scoring_engine
        test_scoring_approbation_auto,
        test_scoring_refus_incident,
        test_scoring_refus_taux_endettement,
        test_score_dans_plage,
        test_shap_somme_100,
        test_criteres_eliminatoires_age,
        # risk_metrics
        test_expected_loss_formule,
        test_lgd_gps_actif_inferieur_a_sans_gps,
        test_lgd_never_negatif,
        test_stress_test_trois_scenarios,
        test_scenario_base_viable,
        test_metriques_portefeuille_vide,
        # recover_bot
        test_penalites_croissantes,
        test_coupe_moteur_dans_sequence_j15,
        test_actions_requises_j18,
        # gps + fraud + eligibility
        test_est_dans_benin_cotonou,
        test_hors_benin_france,
        test_distance_haversine,
        test_fraud_detector_bulletin_ok,
        test_fraud_detector_sans_cachet,
        test_eligibilite_client_ok,
        test_eligibilite_client_trop_jeune,
        test_eligibilite_incident_bceao,
        # analytics + payment
        test_frais_momo_mtn_plafond,
        test_frais_virement_forfait,
        test_ordre_prelevement_id_unique,
        test_projection_encours_croissant,
    ]

    print(f"\n{'═'*60}")
    print(f"{'🧪 PCP — SUITE DE TESTS UNITAIRES':^60}")
    print(f"{'═'*60}\n")

    passed, failed = 0, 0
    for test_fn in tests:
        try:
            test_fn()
            print(f"  ✅  {test_fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ❌  {test_fn.__name__}")
            print(f"       {type(e).__name__}: {e}")
            failed += 1

    print(f"\n{'─'*60}")
    print(f"  Résultat : {passed} passés / {passed + failed} tests")
    print(f"  Taux de réussite : {passed / (passed + failed) * 100:.0f} %")
    print(f"{'═'*60}\n")
    sys.exit(0 if failed == 0 else 1)
