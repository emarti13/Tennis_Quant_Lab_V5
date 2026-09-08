from __future__ import annotations


ALLOWANCE_MINUTES = 3000
GUARDRAIL_FRACTION = 0.80
DAYS_PER_BUDGET_MONTH = 30
WEEKS_PER_BUDGET_MONTH = DAYS_PER_BUDGET_MONTH / 7.0

# Conservative planning minutes, intentionally above typical happy-path runtime.
RECURRING_JOBS = {
    "live_market_repricing": {"runs_per_day": 4, "minutes_per_run": 3},
    "player_ratings": {"runs_per_day": 1, "minutes_per_run": 12},
    "daily_heavy_forecast": {"runs_per_day": 1, "minutes_per_run": 20},
    "daily_settlement": {"runs_per_day": 1, "minutes_per_run": 5},
    "historical_backfill": {"runs_per_week": 3, "minutes_per_run": 45},
}


def configured_monthly_minutes() -> dict:
    jobs = {}
    total = 0.0
    for name, config in RECURRING_JOBS.items():
        if "runs_per_day" in config:
            runs = float(config["runs_per_day"]) * DAYS_PER_BUDGET_MONTH
        else:
            runs = float(config["runs_per_week"]) * WEEKS_PER_BUDGET_MONTH
        minutes = runs * float(config["minutes_per_run"])
        jobs[name] = {
            **config,
            "projected_runs": runs,
            "projected_minutes": minutes,
        }
        total += minutes
    guardrail = int(ALLOWANCE_MINUTES * GUARDRAIL_FRACTION)
    return {
        "allowance_minutes": ALLOWANCE_MINUTES,
        "guardrail_fraction": GUARDRAIL_FRACTION,
        "guardrail_minutes": guardrail,
        "projected_minutes": int(round(total)),
        "headroom_to_guardrail": int(round(guardrail - total)),
        "jobs": jobs,
    }
