#!/usr/bin/env bash
# One-time setup on a fresh Ubuntu 24.04 VM. Run from inside the cloned repo: deploy/setup.sh
# Needs a .env first (cp .env.example .env, then fill in the Alpaca keys and NTFY_TOPIC).
set -euo pipefail
cd "$(dirname "$0")/.."
repo="$PWD"

[ -f .env ] || { echo "Create .env first: cp .env.example .env, then fill it in."; exit 1; }
chmod 600 .env

# the cron schedule is in local time, so the VM's clock has to be New York time
sudo timedatectl set-timezone America/New_York
sudo apt-get update -q
sudo apt-get install -y -q python3-venv python3-pip git cron curl

python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
.venv/bin/pip install -q -e .

mkdir -p logs
chmod +x deploy/run.sh
git config user.name "algosystem-vm"
git config user.email "algosystem-vm@users.noreply.github.com"

# replaces this user's whole crontab -- fine on a VM that only runs the bot
sed "s#__REPO__#$repo#g" deploy/crontab.txt | crontab -
echo "Installed crontab:"
crontab -l
echo "Timezone: $(timedatectl show -p Timezone --value)   Now: $(date)"
