# Where a person's decisions live

Decided 2026-10-16 (user): decisions go in their own files. The daily rebuild
(`scripts/refresh_identity.py`) reads them and never writes them, so a decision pull
request and the bot's daily commit never edit the same file.

| File | One row per | Says |
|---|---|---|
| `master_schedule/decisions_oddspapi.csv` | OddsPapi tournament block (`tournament_id@first_date`) | `user`: this edition; `rejected`: ignore, never priced |
| `master_schedule/decisions_tennismylife.csv` | TennisMyLife tournament block | same |
| `master_schedule/overrides.csv` | edition and field | a court attribute the user changed (surface, setting, altitude, time zone…) |
| `players/decisions_oddspapi.csv` | OddsPapi participant id | `user`: this player; `rejected`: not the suggested player, no history |
| `players/decisions_tennismylife.csv` | TennisMyLife id | ids with the same `player_id` are one player |
| `players/tml_row_corrections.csv` | misfiled TennisMyLife row | move rows from one id to another (empty: own player) |
| `master_schedule/master_schedule_<year>.csv` | edition | the user's sheet itself |

Every row has a `note` saying who decided what and when. Removing a row withdraws the
decision; the next rebuild decides that item again by its rules.

The generated tables (`crosswalk_*.csv`, `players/alias_*.csv`, `players/players.csv`,
`reconciliation/`, `REPORT.md`, `identity_status.json`) are rebuilt every day. Do not
edit them by hand; an edit there is overwritten.
