"""An example's tool reads the input the run hands it, not a default (1385, 1391).

The contract_reviewer FILE tool read each record's fields under their action's name,
and the incident_triage record tools read theirs bare. Neither shape is what a tool
is handed, every `.get` fell to its default, and the run still reported success: one
contract "unknown" with every clause low, and every incident SEV3, then "Unknown".

1391 found the same defect in the remaining examples: book_catalog_enrichment's
validate_bisac_codes, search_book_catalog, format_catalog_entry, filter_by_quality
and select_for_users, and product_listing_enrichment's fetch_competitor_prices and
format_marketplace_listing. format_catalog_entry and format_marketplace_listing also
needed a config fix: both named a field in context_scope.passthrough from an action
they did not themselves observe. A passthrough only re-exposes a namespace the
declaring action already has in its own input; it never retroactively reaches into
an action's output that was never put there, so the field was unreachable under any
key, bare or namespaced. The fix observes the field directly from where it is
produced.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil

from agent_actions.storage import get_storage_backend
from tests._support.agac_cli import REPO, run_agac

EXAMPLES = REPO / "examples"


def _tool(example: str, name: str):
    source = EXAMPLES / example / "tools" / example / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_each_contract_report_names_its_contract_and_clauses(tmp_path):
    root = tmp_path / "contract_reviewer"
    shutil.copytree(EXAMPLES / "contract_reviewer", root)
    workflow = root / "agent_workflow" / "contract_reviewer"
    config = workflow / "agent_config" / "contract_reviewer.yml"
    config.write_text(
        re.sub(r"(?m)^(\s*)model_vendor: \S+", r"\1model_vendor: agac-provider", config.read_text())
    )
    contracts = json.loads((workflow / "agent_io" / "staging" / "contracts.json").read_text())

    result = run_agac(root, "run", "-a", "contract_reviewer", "--fresh")
    assert result.returncode == 0, result.stdout + result.stderr

    backend = get_storage_backend(str(workflow), "contract_reviewer")
    backend.initialize()
    try:
        (path,) = backend.list_target_files("aggregate_risk_summary")
        records = backend.read_target("aggregate_risk_summary", path)
    finally:
        backend.close()
    reports = [r["content"]["aggregate_risk_summary"] for r in records]
    reports = [r for r in reports if r is not None]
    named = [(r["contract_id"], r["contract_title"], r["parties"]) for r in reports]
    assert named == [(c["contract_id"], c["title"], c["parties"]) for c in contracts]
    assert len(contracts) > 1
    for report in reports:
        numbers = [o["clause_number"] for o in report["total_obligations"]]
        assert numbers != [] and 0 not in numbers
        assert max(numbers) <= report["total_clauses_analyzed"]
        assert all(o["clause_title"] != "Unknown" for o in report["total_obligations"])


def test_an_incident_is_routed_by_the_severity_it_was_given():
    module = _tool("incident_triage", "assign_team_based_on_impact")
    seeds = EXAMPLES / "incident_triage" / "agent_workflow" / "incident_triage" / "seed_data"
    # A record tool is handed one key per observed action, and its seeds under `seed`.
    assigned = module.assign_team_based_on_impact(
        {
            "aggregate_severity": {"final_severity": "SEV1"},
            "assess_system_impact": {"affected_services": ["database cluster"]},
            "seed": {
                "team_roster": json.loads((seeds / "team_roster.json").read_text()),
                "service_catalog": json.loads((seeds / "service_catalog.json").read_text()),
            },
        }
    )
    assert "SEV1" in assigned["response_message"]
    assert "SEV3" not in assigned["response_message"]


def test_a_triage_is_formatted_from_what_each_action_answered():
    module = _tool("incident_triage", "format_incident_triage")
    # One key per observed action; one whose guard skipped the record is there as None.
    (triage,) = module.format_incident_triage(
        {
            "extract_incident_details": {"title": "Checkout down", "affected_systems": ["api"]},
            "aggregate_severity": {"final_severity": "SEV2", "confidence_score": 0.8},
            "assess_customer_impact": {"customer_impact_level": "HIGH"},
            "assess_system_impact": {"affected_services": ["payments"]},
            "assign_response_team": {
                "assigned_teams": ["backend-oncall"],
                "requires_executive_notification": True,
            },
            "generate_response_plan": {"immediate_actions": ["roll back"]},
            "generate_executive_summary": None,
            "source": {"timestamp": "2024-05-01T10:00:00Z"},
        }
    )
    assert triage["incident"]["title"] == "Checkout down"
    assert triage["severity"] == {
        "final_severity": "SEV2",
        "confidence_score": 0.8,
        "is_split_decision": False,
        "vote_summary": "",
    }
    assert triage["impact"]["customer_impact"]["level"] == "HIGH"
    assert triage["impact"]["system_impact"]["affected_services"] == ["payments"]
    assert triage["teams"]["assigned_teams"] == ["backend-oncall"]
    assert triage["response"]["immediate_actions"] == ["roll back"]
    assert triage["metadata"]["requires_executive_notification"] is True
    assert triage["timestamp"] == "2024-05-01T10:00:00Z"
    assert triage["executive_summary"] == {}


def test_bisac_codes_are_validated_against_what_review_classification_answered():
    module = _tool("book_catalog_enrichment", "validate_bisac_codes")
    # One key per observed action: review_classification.*
    result = module.validate_bisac_codes(
        {
            "review_classification": {
                "primary_bisac_code": "ZZZ999999",
                "primary_bisac_name": "Not A Real Category",
                "secondary_bisac_codes": [],
                "classification_reasoning": "test",
            }
        }
    )
    assert result["bisac_valid"] is False
    assert "ZZZ999999" in result["validation_notes"]


def test_catalog_search_uses_the_genres_the_search_criteria_named(monkeypatch):
    module = _tool("book_catalog_enrichment", "search_book_catalog")
    seen_queries: list[str] = []

    def fake_search(query, limit=20):
        seen_queries.append(query)
        return [
            {
                "title": "Fake Match",
                "author_name": ["A"],
                "isbn": ["9999999999"],
                "subject": ["x"],
            }
        ]

    monkeypatch.setattr(module, "_search_open_library", fake_search)
    # One key per observed action: generate_search_criteria.*
    result = module.search_book_catalog(
        {
            "generate_search_criteria": {
                "genres": ["FIC000000"],
                "keywords": ["dragon"],
                "query_text": "",
                "exclude_isbn": "",
            }
        }
    )
    assert result["matching_books"] != []
    assert result["search_metadata"]["genres_searched"] == ["FIC000000"]
    assert result["search_metadata"]["keywords_searched"] == ["dragon"]
    assert any("fiction" in q for q in seen_queries)


def test_the_catalog_entry_is_formatted_from_what_each_action_produced():
    module = _tool("book_catalog_enrichment", "format_catalog_entry")
    # One key per observed action; format_entry observes each producer directly
    # rather than through score_quality's passthrough (1391).
    result = module.format_catalog_entry(
        {
            "write_description": {
                "isbn": "9781234567890",
                "title": "The Great Book",
                "authors": ["Jane Doe"],
                "publisher": "Acme",
                "publish_year": 2020,
                "page_count": 300,
                "marketing_description": "x" * 120,
                "hook_sentence": "A hook.",
                "key_benefits": ["a", "b", "c"],
                "target_audience": "Readers",
            },
            "validate_bisac": {
                "bisac_codes": ["FIC000000"],
                "bisac_names": ["Fiction / General"],
            },
            "generate_seo": {
                "primary_keywords": ["novel"],
                "long_tail_keywords": ["great book"],
                "meta_title": "The Great Book",
                "meta_description": "meta",
            },
            "generate_recommendations": {
                "similar_books": [
                    {"isbn": "1", "title": "Other", "authors": ["X"], "relationship": "similar"}
                ],
                "reading_path": "read this first",
            },
            "assess_reading_level": {
                "reading_level": "Advanced",
                "years_experience_needed": "5+",
                "prerequisites": ["basics"],
                "estimated_reading_time": "6h",
            },
            "score_quality": {"overall_score": 4.5, "ready_for_publication": True},
        }
    )
    assert result["isbn"] == "9781234567890"
    assert result["title"] == "The Great Book"
    assert result["primary_category"] == "Fiction / General"
    assert result["quality_score"] == 4.5
    assert result["publication_ready"] is True
    assert "classification" in result["enriched_fields"]


def test_quality_filter_reads_the_score_format_entry_computed():
    module = _tool("book_catalog_enrichment", "filter_by_quality")
    # One key per observed action: format_entry.*
    result = module.filter_by_quality(
        {
            "format_entry": {
                "quality_score": 4.2,
                "publication_ready": True,
                "enriched_fields": ["classification", "marketing_description", "seo_keywords"],
            }
        }
    )
    assert result["passes_filter"] is True
    assert result["filter_reason"] == "Passed all quality checks"


def test_user_views_are_built_from_what_format_entry_produced():
    module = _tool("book_catalog_enrichment", "select_for_users")
    # One key per observed action: filter_quality.* and format_entry.*
    result = module.select_for_users(
        {
            "filter_quality": {"passes_filter": True, "filter_reason": "Passed all quality checks"},
            "format_entry": {
                "isbn": "9781234567890",
                "title": "The Great Book",
                "catalog_id": "CAT-567890",
                "quality_score": 4.2,
                "publication_ready": True,
                "primary_category": "Fiction / General",
                "target_audience": "Readers",
                "enriched_fields": ["classification"],
                "enrichment_version": "1.0.0",
                "bisac_codes": ["FIC000000"],
                "difficulty_level": "Advanced",
                "experience_required": "5+",
                "prerequisites": ["basics"],
                "reading_time_hours": "6h",
                "similar_titles": [],
                "reading_path": "read this first",
                "meta_title": "The Great Book",
                "meta_description": "meta",
                "seo_keywords": ["novel"],
                "full_description": "desc",
                "short_description": "hook",
                "key_selling_points": ["a"],
            },
        }
    )
    assert result["isbn"] == "9781234567890"
    assert result["seo_view"]["title"] == "The Great Book"
    assert result["management_view"]["filter_reason"] == "Passed all quality checks"
    assert result["developer_view"]["difficulty_level"] == "Advanced"


def test_competitor_prices_are_seeded_from_the_real_current_price():
    module = _tool("product_listing_enrichment", "fetch_competitor_prices")
    # One key per observed action: generate_description.search_keywords and
    # normalize_product.{product_category,current_price}.
    result = module.fetch_competitor_prices(
        {
            "generate_description": {"search_keywords": ["standing desk"]},
            "normalize_product": {"current_price": 500.0, "product_category": "home_office"},
        }
    )
    assert result["average_competitor_price"] != 100.0
    assert 300 < result["average_competitor_price"] < 700
    assert result["competitor_prices"][0]["product_name"].endswith("Adjustable Standing Desk")


def test_the_marketplace_listing_carries_the_normalized_product_identity():
    module = _tool("product_listing_enrichment", "format_marketplace_listing")
    # format_listing observes normalize_product directly rather than through a
    # passthrough declared on an action it does not otherwise observe (1391).
    result = module.format_marketplace_listing(
        {
            "normalize_product": {
                "product_id": "PLE-1",
                "product_name": "Standing Desk",
                "brand": "DeskCo",
                "current_price": 399.99,
                "product_category": "home_office",
            },
            "write_marketing_copy": {
                "listing_title": "Great Desk",
                "listing_description": "d",
                "bullet_points": [],
                "search_keywords": [],
                "value_proposition": "v",
            },
            "optimize_seo": {},
            "validate_compliance": {"compliance_passed": True, "violations": []},
            "fetch_competitor_prices": {
                "competitor_prices": [],
                "price_position": "average",
                "average_competitor_price": 0,
            },
            "generate_description": {},
        }
    )
    assert result["product_id"] == "PLE-1"
    assert result["product_name"] == "Standing Desk"
    assert result["brand"] == "DeskCo"
    assert result["price"] == 399.99
    assert result["category"] == "home_office"


def test_the_marketplace_listing_gets_the_normalized_product_identity_end_to_end(tmp_path):
    """A real agac run, matching the contract_reviewer E2E test above: this is the
    one example in 1391 a test can drive past kickoff without a HITL in the way."""
    root = tmp_path / "product_listing_enrichment"
    shutil.copytree(EXAMPLES / "product_listing_enrichment", root)
    workflow = root / "agent_workflow" / "product_listing_enrichment"
    config = workflow / "agent_config" / "product_listing_enrichment.yml"
    text = config.read_text()
    text = re.sub(r"(?m)^(\s*)model_vendor: \S+", r"\1model_vendor: agac-provider", text)
    text = re.sub(r"(?m)^(\s*)run_mode: \S+", r"\1run_mode: online", text)
    text = re.sub(r"(?m)^(\s*)record_limit: \d+", r"\1record_limit: 1", text)
    config.write_text(text)

    result = run_agac(root, "run", "-a", "product_listing_enrichment", "--fresh")
    assert result.returncode == 0, result.stdout + result.stderr

    backend = get_storage_backend(str(workflow), "product_listing_enrichment")
    backend.initialize()
    try:
        (path,) = backend.list_target_files("format_listing")
        records = backend.read_target("format_listing", path)
    finally:
        backend.close()
    listings = [r["content"]["format_listing"] for r in records]
    assert listings
    for listing in listings:
        assert listing["product_id"]
        assert listing["product_name"]
        assert listing["brand"]
        assert listing["price"] > 0
        assert listing["category"]
