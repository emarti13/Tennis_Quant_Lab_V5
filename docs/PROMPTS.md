# Command list: how to prompt Claude for this project

Copy a prompt and fill in the brackets. Every result Claude reports should follow
`docs/RESEARCH_REPORTING.md`; if one does not, say "Report per RESEARCH_REPORTING.md".

## Status

| You want | Prompt |
|---|---|
| Is the server healthy? | "Read market_history/vm_status.md on data/vm-logs and tell me what's broken." |
| How are the forward tests doing? | "Show the registered forward tests' running results (status page and docs/registrations/README.md)." |
| How is the paper trader doing? | "Settle and summarise the paper trader from data/vm-logs: earning the spread vs holding, by period." |
| What happened since last time? | "Summarise what changed since [date]: commits, results, open PRs, anything waiting on me." |

## Research

| You want | Prompt |
|---|---|
| Test an idea | "Test [idea]. Pre-register the rule first, use research_kit with all checks, report the money at executable prices with fees, the minimum detectable effect and one label." |
| New ideas | "Run idea-scout and give me the top 5 with data sources and test designs." |
| Check a result | "Run research-auditor on [test or write-up] and give me its report unedited." |
| Challenge a 'no' | "What could this test have detected? List the slices with \|residual\| ≥ 2 pts or ROI ≥ 3%, and any errors that would hide an edge." |
| Combine signals | "Add [signal] to the blend and re-run it with checks." |
| Turn a candidate into a test | "Register [rule] as a forward test: build the paper tracker on the server, write the registration, open the PR." |

## Server (run these on the server, at the `ubuntu@tquant1` prompt)

| You want | Command |
|---|---|
| Connect from Cloud Shell | `ssh -i tql.key ubuntu@129.159.175.246` |
| Fix pasting (`^[[200~`) | type: `bind 'set enable-bracketed-paste off'` |
| Health check | `cd ~/tql && bash ops/check.sh` |
| Run the daily job now | `sudo systemctl start tql-daily.service` |
| Reinstall after an update | `cd ~/tql && bash ops/bootstrap.sh` |
| Watch the live logger | `journalctl -u tql-live -f` (Ctrl+C to stop) |
| Stop everything | `sudo systemctl disable --now tql-paper tql-live tql-daily.timer` |

## GitHub

| You want | Prompt |
|---|---|
| What needs merging? | "List my open PRs and which are ready to merge." |
| Something failed | "A run failed on GitHub: find it, fix it, open a PR." |
| Clean up branches | "Add merged branches to manual_cleanup/README.md." (then delete them on github.com) |

## Rules Claude follows here (so you don't have to repeat them)

- **Rules are written before results are read.** An idea counts only on a forward window after it
  was registered (`docs/registrations/`).
- **Money is measured at prices you can bet,** with fees, and no cost is counted twice.
- **Every "no" says what the test could have detected.** "Closed" only means ruled out above a
  small size.
- **Results that change a decision get an independent audit** before they are treated as settled.
- **No real money** until a registered test passes, the checks pass, and a second forward window
  agrees.
