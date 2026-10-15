# Player registry (2026)

Date: 2026-10-13 · Rebuild plan Step 2 · Spec: `docs/superpowers/specs/2026-10-13-player-identity-design.md`.
No model or price change; no market benchmark applies. Production does not read these tables yet.

Reproduce: `python scripts/build_player_registry.py --year 2026 --as-of 2026-10-13` (about 45 s).

## Players from TennisMyLife (2010–2026)

- 6,155 TennisMyLife ids (plus id-less rows) → **6,035 players**; 95 players hold more than
  one id (almost all the 2026 WTA second id scheme, joined by career overlap because their
  ages are broken).
- Only 62 folded names appear under more than one id. Birth dates from recorded ages show
  three of them are two different people (David Warren, Diogo Rocha, Quentin Robert); an
  earlier name-and-country rule had merged them.
- Review (7): Harshana Godamanna (SRI/ECU, same birth date), Julio Cesar Porras (ARG/ESP),
  Marc-Andrea Huesler vs a row under John Millman's id, Pol Wattanakul's id with another
  name, two id-less players.
- A Monday-to-Sunday week wrongly put Bad Homburg (dated Sunday June 21) in the same week
  as the event before it; tennis weeks now start Monday and weekend dates roll forward.

## OddsPapi participants seen in 2026 (2,471)

| status | count | meaning |
|---|---|---|
| confirmed | 1,023 | 2+ shared matches agree |
| auto | 608 | 1 shared match, or a unique exact name |
| review | 21 | a person decides; no price |
| no_history | 789 | no candidate in our history; never a rating |
| placeholder | 30 | draw slots (WQF1, Qf3, R16P14) |

Checks on known cases: de Minaur, De Jong, Van de Zandschulp, Ruse, Kessler, Tomljanovic,
Kasatkina, Shuai Zhang resolve to one player; Maria Carle, Pietro Fellin, Tai Sach, Rafael De
Alba, Martin Damm (Jr), Cezar Cretu (2001) and Pyotr/Petr Nesterov link by results; Katarina
Kuzmova is no_history (her results are ITF). After the fixes below, no link joins two names
that share no word.

Problems found and fixed while building: id-less rows were pooled into one node (NaN ids);
one match aligned by draw order produced about 10 wrong links (now: draw order needs a
shared name word and never stands alone); draw-order noise made 40 players look
contradictory (gone once draw order needs a shared word). The no_history players are
mostly WTA 125 and Challenger qualifiers whose earlier results are ITF, which we do not
collect; that matters for the WTA 125 pricing decision.

A second build gives byte-identical tables (player ids are stable).
