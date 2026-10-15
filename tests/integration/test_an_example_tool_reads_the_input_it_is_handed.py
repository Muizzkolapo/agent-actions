"""An example's tool reads the input the run hands it, not a default (1385, 1391).

1391 is the same shape-mismatch defect 1385 fixed in contract_reviewer and
incident_triage, now in the remaining example tools. Two of them also needed an
observe fix, not just a read fix: context_scope.passthrough only re-exposes a
namespace the declaring action already has in its own input, so a field declared
there from an action never otherwise observed was unreachable under any key.
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
    # isbn/title/authors/publisher/publish_year/page_count come from source, not
    # write_description -- write_description's own output never carries them.
    result = module.format_catalog_entry(
        {
            "source": {
                "isbn": "9781234567890",
                "title": "The Great Book",
                "authors": ["Jane Doe"],
                "publisher": "Acme",
                "publish_year": 2020,
                "page_count": 300,
            },
            "write_description": {
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
                "meta_description": "An unforgettable story.",
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
    assert result["catalog_id"] == "CAT-567890"
    assert result["title"] == "The Great Book"
    assert result["authors"] == ["Jane Doe"]
    assert result["publisher"] == "Acme"
    assert result["publish_year"] == 2020
    assert result["page_count"] == 300
    assert result["primary_category"] == "Fiction / General"
    assert result["bisac_codes"] == ["FIC000000"]
    assert result["full_description"] == "x" * 120
    assert result["short_description"] == "A hook."
    assert result["key_selling_points"] == ["a", "b", "c"]
    assert result["target_audience"] == "Readers"
    assert result["seo_keywords"] == ["novel", "great book"]
    assert result["meta_title"] == "The Great Book"
    assert result["meta_description"] == "An unforgettable story."
    assert result["similar_titles"] == [
        {"isbn": "1", "title": "Other", "authors": ["X"], "relationship": "similar"}
    ]
    assert result["reading_path"] == "read this first"
    assert result["difficulty_level"] == "Advanced"
    assert result["experience_required"] == "5+"
    assert result["prerequisites"] == ["basics"]
    assert result["reading_time_hours"] == "6h"
    assert result["quality_score"] == 4.5
    assert result["publication_ready"] is True
    assert set(result["enriched_fields"]) == {
        "classification",
        "marketing_description",
        "seo_keywords",
        "recommendations",
        "reading_level",
    }


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
                "similar_titles": [
                    {"isbn": "1", "title": "Other", "authors": ["X"], "relationship": "similar"}
                ],
                "reading_path": "read this first",
                "meta_title": "The Great Book",
                "meta_description": "An unforgettable story.",
                "seo_keywords": ["novel", "great book"],
                "full_description": "A long description.",
                "short_description": "A hook.",
                "key_selling_points": ["a", "b", "c"],
            },
        }
    )
    assert result["isbn"] == "9781234567890"
    assert result["title"] == "The Great Book"
    assert result["seo_view"] == {
        "isbn": "9781234567890",
        "title": "The Great Book",
        "meta_title": "The Great Book",
        "meta_description": "An unforgettable story.",
        "seo_keywords": ["novel", "great book"],
        "target_audience": "Readers",
        "marketing_description": "A long description.",
        "hook_sentence": "A hook.",
        "key_selling_points": ["a", "b", "c"],
    }
    assert result["management_view"] == {
        "isbn": "9781234567890",
        "title": "The Great Book",
        "catalog_id": "CAT-567890",
        "quality_score": 4.2,
        "publication_ready": True,
        "primary_category": "Fiction / General",
        "target_audience": "Readers",
        "enriched_fields": ["classification"],
        "enrichment_version": "1.0.0",
        "filter_reason": "Passed all quality checks",
    }
    assert result["developer_view"] == {
        "isbn": "9781234567890",
        "title": "The Great Book",
        "bisac_codes": ["FIC000000"],
        "primary_category": "Fiction / General",
        "difficulty_level": "Advanced",
        "experience_required": "5+",
        "prerequisites": ["basics"],
        "reading_time_hours": "6h",
        "similar_titles": [
            {"isbn": "1", "title": "Other", "authors": ["X"], "relationship": "similar"}
        ],
        "reading_path": "read this first",
    }


def test_competitor_prices_are_seeded_from_the_real_current_price():
    module = _tool("product_listing_enrichment", "fetch_competitor_prices")
    # One key per observed action: generate_description.search_keywords and
    # normalize_product.{product_category,current_price}.
    base = {"normalize_product": {"current_price": 500.0, "product_category": "home_office"}}
    result = module.fetch_competitor_prices(
        {**base, "generate_description": {"search_keywords": ["standing desk"]}}
    )
    other_keywords = module.fetch_competitor_prices(
        {**base, "generate_description": {"search_keywords": ["gaming chair"]}}
    )
    assert result["average_competitor_price"] != 100.0
    assert 300 < result["average_competitor_price"] < 700
    assert result["competitor_prices"][0]["product_name"].endswith("Adjustable Standing Desk")
    # search_keywords seeds the deterministic pricing -- a different keyword set
    # must select a different result, or the keyword was never read at all.
    assert result["competitor_prices"] != other_keywords["competitor_prices"]


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
                "listing_description": "A sturdy desk.",
                "bullet_points": ["Adjustable height"],
                "search_keywords": ["desk"],
                "value_proposition": "Work better.",
            },
            "optimize_seo": {
                "optimized_title": "Best Standing Desk",
                "optimized_bullets": ["Fully adjustable height"],
                "primary_keywords": ["standing desk"],
                "long_tail_keywords": ["adjustable standing desk for home office"],
                "backend_keywords": ["desk ergonomic"],
                "seo_score_estimate": "high",
            },
            "validate_compliance": {"compliance_passed": True, "violations": []},
            "fetch_competitor_prices": {
                "competitor_prices": [{"competitor_name": "A", "price": 350}],
                "price_position": "average",
                "average_competitor_price": 350,
            },
            "generate_description": {},
        }
    )
    assert result["product_id"] == "PLE-1"
    assert result["product_name"] == "Standing Desk"
    assert result["brand"] == "DeskCo"
    assert result["price"] == 399.99
    assert result["category"] == "home_office"
    assert result["listing"] == {
        "title": "Best Standing Desk",
        "description": "A sturdy desk.",
        "bullet_points": ["Fully adjustable height"],
        "value_proposition": "Work better.",
    }
    assert result["seo"] == {
        "primary_keywords": ["standing desk"],
        "long_tail_keywords": ["adjustable standing desk for home office"],
        "backend_keywords": ["desk ergonomic"],
        "seo_score": "high",
    }
    assert result["competitive_intel"] == {
        "price_position": "average",
        "average_competitor_price": 350,
        "competitor_count": 1,
    }
    assert result["compliance"] == {"passed": True, "violations": []}


def test_the_brand_name_in_title_check_reads_the_real_brand():
    module = _tool("product_listing_enrichment", "validate_marketplace_compliance")
    # One key per observed action: write_marketing_copy.* and normalize_product.brand
    # (sibling instance of the 1391 defect, found in review of this fix).
    base_copy = {
        "listing_title": "Ergonomic Desk for Home Offices",
        "listing_description": "A sturdy, adjustable desk built for long work days.",
        "bullet_points": ["Adjustable height", "Sturdy steel frame"],
        "search_keywords": ["desk", "office"],
    }
    missing_brand = module.validate_marketplace_compliance(
        {
            "write_marketing_copy": base_copy,
            "normalize_product": {"brand": "DeskCo"},
            "seed": {"marketplace_rules": {}},
        }
    )
    assert missing_brand["compliance_passed"] is False
    assert "Title must include brand name 'DeskCo'" in missing_brand["violations"]

    with_brand = module.validate_marketplace_compliance(
        {
            "write_marketing_copy": {**base_copy, "listing_title": "DeskCo Ergonomic Desk"},
            "normalize_product": {"brand": "DeskCo"},
            "seed": {"marketplace_rules": {}},
        }
    )
    assert not any("brand name" in v for v in with_brand["violations"])


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
    assert len(listings) == 1
    listing = listings[0]
    # agent_io/staging/products.json's first record, run through normalize_product's
    # deterministic transform -- exact values, not just truthy, so a wrong-but-non-empty
    # placeholder default can't pass this the way it passed the unit test above.
    assert listing["product_id"] == "PLE-AVpfAs_-ilAP"
    assert (
        listing["product_name"]
        == "Alpha a7S II Mirrorless Digital Camera Body with Accessories Kit"
    )
    assert listing["brand"] == "Sony"
    assert listing["price"] == 4010.5
    assert listing["category"] == "electronics"
