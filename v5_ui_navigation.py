from __future__ import annotations


PAGE_ORDER = [
    "Today",
    "Match Detail",
    "All Markets",
    "Performance",
    "Model Health",
    "Matchup Lab",
]


def page_registry() -> dict[str, str]:
    """Return stable UI page identifiers in presentation order.

    The registry deliberately contains no model callbacks. The host app owns
    orchestration; this module only defines the product navigation contract.
    """
    return {
        "Today": "today",
        "Match Detail": "match_detail",
        "All Markets": "all_markets",
        "Performance": "performance",
        "Model Health": "model_health",
        "Matchup Lab": "matchup_lab",
    }
