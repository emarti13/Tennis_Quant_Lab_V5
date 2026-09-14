# External Court Conditions Data Notes

Initial source snapshot fields are derived from CourtSpeed.com's published tournament-year tables as of 2026-08-27.

- CPI: official ATP/TennisTV measurements where available.
- Adjusted ace rate: source cites TennisAbstract.
- Rally length: source cites Tennis Insights, IBM, and Infosys depending event.
- Relative air density: source cites Open-Meteo; indoor events intentionally have no outdoor RAD value.
- Ball type: tournament-year ball brand.
- Overall speed rating: source composite requiring at least three of CPI, ace rate, rally length, and RAD.

This is an initial provider implementation, not a permanent licensing decision. The canonical adapter deliberately isolates provider names from downstream V5 contracts so individual fields can be replaced later without changing model consumers.
