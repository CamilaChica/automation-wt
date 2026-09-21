from services.prompt_evaluation import (
    SIMULATION_PROFILES,
    audit_all_agents,
    compare_all_agents,
)


def test_prompt_audit_covers_every_registered_agent():
    audits = audit_all_agents()

    assert len(audits) == 9
    assert all(1 <= audit.score.average <= 5 for audit in audits)
    assert all(audit.final_system_prompt for audit in audits)
    assert all(len(audit.edge_cases) >= 5 for audit in audits)


def test_user_simulation_profiles_cover_clean_noisy_and_adversarial_inputs():
    assert {profile.name for profile in SIMULATION_PROFILES} == {
        "expert_clean_user",
        "imperfect_noisy_user",
        "adversarial_boundary_user",
    }


def test_prompt_comparison_reports_tuning_changes_for_every_agent():
    comparisons = compare_all_agents()

    assert len(comparisons) == 9
    assert all(comparison.tuned_prompt for comparison in comparisons)
    assert all(comparison.changes for comparison in comparisons)
    assert all("schema" in comparison.tuned_prompt.lower() for comparison in comparisons)
