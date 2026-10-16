from __future__ import annotations


ALLOWANCE_MINUTES = 3000
# Keep recurring automation below 70% so PR verification, recovery runs and
# occasional model acceptance work have real monthly capacity.
GUARDRAIL_FRACTION = 0.70
DAYS_PER_BUDGET_MONTH = 30
WEEKS_PER_BUDGET_MONTH = DAYS_PER_BUDGET_MONTH / 7.0

# Conservative planning minutes. Heavy history/model work is expected once/day.
# The two later recovery windows short-circuit after checkout/setup when that
# day's artifact is already healthy, but their runner time is budgeted explicitly.
# Research/acceptance workflows are manual-only and excluded from recurring burn.
# The old engine's daily heavy forecast (v5_daily_predictions.yml: 20 min + 2 x 3 min
# probes a day, ~780 min/month) is paused until rebuild Step 4 (user decision 2026-10-16).
RECURRING_JOBS = {
    "live_market_repricing": {"runs_per_day": 1, "minutes_per_run": 3},
    "player_ratings": {"runs_per_day": 1, "minutes_per_run": 14},  # includes ~1.5 min identity refresh
    "player_refresh_recovery_probes": {"runs_per_day": 2, "minutes_per_run": 3},
    "daily_settlement": {"runs_per_day": 1, "minutes_per_run": 3},
    # Manual-only today (workflow_dispatch); budgeted so an occasional run fits.
    "historical_backfill": {"runs_per_week": 1, "minutes_per_run": 45},
}

# Every workflow with a cron schedule, and how many cron lines it has. A new
# scheduled workflow must be added here and to RECURRING_JOBS (CLAUDE.md:
# no new scheduled jobs without a budget note); tests enforce this.
SCHEDULED_WORKFLOWS = {
    "oddspapi_normalized_daily_v2.yml": {"crons": 1, "jobs": ("live_market_repricing",)},
    "v5_player_ratings_refresh.yml": {"crons": 3, "jobs": ("player_ratings", "player_refresh_recovery_probes")},
    "v5_automatic_settlement.yml": {"crons": 1, "jobs": ("daily_settlement",)},
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
        "headroom_to_allowance": int(round(ALLOWANCE_MINUTES - total)),
        "reserved_for_ci_recovery_and_acceptance": int(round(ALLOWANCE_MINUTES - total)),
        "jobs": jobs,
    }
