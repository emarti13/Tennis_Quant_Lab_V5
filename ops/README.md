# Server runner: collect data and run tests without Claude or Actions

A free always-on server runs the long jobs:

- the Kalshi Challenger paper market-maker;
- the live score + price logger (ATP, Challenger, WTA);
- a daily settle, test, and commit job.

It commits its logs to the `data/vm-logs` branch. No workflow triggers on that branch, so it uses **no Actions minutes**. It uses **no Claude usage** either. Claude is only needed when you ask for a new build or an analysis. It then reads the data branch.

No API keys are used. Everything reads Kalshi's public market data. Nothing places orders.

## What runs

| Unit | What | When |
|---|---|---|
| `tql-paper.service` | `scripts/paper_trade_kalshi.py poll`: paper quotes on Challenger matches, fills from real trades | always (restarts daily) |
| `tql-live.service` | `scripts/log_kalshi_live.py`: score + both players' bid/ask every 10 s while a match is live | always (restarts daily) |
| `tql-daily.timer` → `ops/daily.sh` | settle paper fills; gzip yesterday's live log; commit; merge new code from `CODE_BRANCH`; run the tests (if they fail, roll back to the old code); write `market_history/vm_status.md`; push | 07:17 UTC daily |

## One-time setup (about 30 minutes, works from a phone)

### 1. Create the server (Oracle Cloud Always Free)

1. Sign up at **cloud.oracle.com**. A card is needed for identity only; Always Free resources are not charged. Pick a **US home region** (for example US East Ashburn). The home region cannot be changed later.
2. Go to Menu → Compute → Instances → **Create instance**.
   - Image: **Ubuntu 24.04**.
   - Shape: **VM.Standard.A1.Flex** with 1 OCPU and 6 GB memory if it is offered (Always Free, ARM). If it says "out of capacity", use **VM.Standard.E2.1.Micro** (Always Free, 1 GB memory). On the Micro the full test suite may be slow or short of memory; set `TESTS="tests/test_paper_trade_kalshi.py tests/test_kalshi_live_logger.py tests/test_ops_status.py -q"` in `ops/env` if the daily job's test step fails for that reason.
   - SSH keys: choose **Generate a key pair** and download both keys. On a phone, save them to Files.
   - Press Create. Wait until it shows *Running*, then note its **public IP**.
3. To connect from a phone, either:
   - use the **Cloud Shell** button (top right of the Oracle console). Upload the private key there, then run `chmod 600 key && ssh -i key ubuntu@<public-ip>`; or
   - use an SSH app such as Termius with the same key.

### 2. Give the server write access to this repo (deploy key)

On the server:

```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519 -C tql-server
cat ~/.ssh/id_ed25519.pub
```

On GitHub, go to the repo → Settings → Deploy keys → **Add deploy key**. Paste the line. Title it `tql-server` and tick **Allow write access**.

This key can push to this one repo only. Revoke it there at any time.

### 3. Clone and install

```bash
ssh -o StrictHostKeyChecking=accept-new -T git@github.com   # "successfully authenticated" is expected
git clone --filter=blob:none git@github.com:emarti13/Tennis_Quant_Lab_V5.git ~/tql
cd ~/tql && git checkout feat/vm-runner
cp ops/env.example ops/env        # edit CODE_BRANCH to main once this kit is merged
bash ops/bootstrap.sh
```

`--filter=blob:none` skips downloading old file versions; the full history is 1.7 GB.

### 4. Check it

```bash
bash ops/check.sh
```

All three units should read `active`. The live logger prints a line every 10 s, for example `{"rows": 4, "live_matches": 4, ...}`. Run the daily job once by hand to confirm the push works:

```bash
sudo systemctl start tql-daily.service && bash ops/check.sh
```

A commit should then appear on the `data/vm-logs` branch on GitHub, holding `market_history/vm_status.md`.

## Daily use

- **To see what happened:** open `market_history/vm_status.md` on the `data/vm-logs` branch in the GitHub app. It shows the services, the live-log rows and matches per day, paper results per setting, the test result, and any problems.
- **When you want Claude:** start a session and use one of the prompts below. Claude builds and tests on a branch. The server picks up the code the next morning, but only if the tests pass on the server.

### Prompt templates

- *Status:* "Read `market_history/vm_status.md` on `data/vm-logs` and tell me if anything is broken."
- *Analysis:* "Using the live score logs on `data/vm-logs`, test <idea>. Leak-free, out-of-sample, include Kalshi fees."
- *New collector or strategy:* "Build <thing> as a script plus tests, add it to the server runner (a unit in `ops/systemd/` and `bootstrap.sh`), and push to `feat/vm-runner`." Then run `bash ops/bootstrap.sh` on the server once to install the new unit.

## Maintenance

| Task | Command |
|---|---|
| Stop everything | `sudo systemctl disable --now tql-paper tql-live tql-daily.timer` |
| Watch the live logger | `journalctl -u tql-live -f` |
| Switch code to `main` after merge | edit `ops/env` (`CODE_BRANCH=main`), then wait for the next daily run |
| Disk use | `df -h ~`. Measured: the paper logs were 10 MB raw for 31 hours, and 0.4 MB gzipped. Live logs: about 370 bytes per row, so a few MB a day raw while matches are live, and a fraction of that gzipped. |

Oracle may reclaim an Always Free instance that stays idle for 7 days (under 20% CPU). If that happens, at most one day of logs is lost, because everything is pushed daily. Create a new instance and repeat steps 2–4.
