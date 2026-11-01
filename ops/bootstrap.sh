#!/usr/bin/env bash
# One-time server setup. Run from the repo clone:  bash ops/bootstrap.sh
# Installs Python packages into .venv, checks out the data branch, installs and starts the
# services. Safe to run again (it reinstalls the units and restarts them).
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"
[ -f ops/env ] || cp ops/env.example ops/env
source ops/env

sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-venv python3-pip git
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt pytest pyyaml scipy scikit-learn lightgbm openpyxl -c ops/constraints.txt

git config user.name  "tql-server"
git config user.email "tql-server@users.noreply.github.com"
git fetch -q origin "$CODE_BRANCH"
if git ls-remote --exit-code --heads origin "$DATA_BRANCH" >/dev/null; then
  git fetch -q origin "$DATA_BRANCH"
  git checkout -q -B "$DATA_BRANCH" "origin/$DATA_BRANCH"
  git merge -q --no-edit "origin/$CODE_BRANCH"
else
  git checkout -q -B "$DATA_BRANCH" "origin/$CODE_BRANCH"
  git push -q -u origin "$DATA_BRANCH"
fi

for unit in ops/systemd/*; do
  sed -e "s#@USER@#$(id -un)#g" -e "s#@DIR@#$DIR#g" "$unit" | sudo tee "/etc/systemd/system/$(basename "$unit")" >/dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable --now tql-paper.service tql-live.service tql-daily.timer
sudo systemctl restart tql-paper.service tql-live.service

echo
echo "Installed. Check it with:  bash ops/check.sh"
