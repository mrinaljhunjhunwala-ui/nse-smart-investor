#!/usr/bin/env bash
# deploy/oracle-relay/setup.sh — install or update the Angel One price relay on an
# Ubuntu 22.04 / 24.04 VM. Safe to run again any time (it is how you update too).
#
#   REF=<commit-sha>   # pin a reviewed commit, not main
#   curl -fsSLo setup.sh https://raw.githubusercontent.com/mrinaljhunjhunwala-ui/nse-smart-investor/$REF/deploy/oracle-relay/setup.sh
#   less setup.sh            # read it before running as root
#   sudo bash setup.sh
#
# What it does: installs git + python3-venv, clones / updates the repo in
# /opt/nse-smart-investor, makes a small virtualenv with only what the relay needs,
# adds swap on a 1 GB VM, creates the service user, installs the systemd units (relay + EOD download timer), and
# creates /etc/nse-price-relay.env (chmod 600) from the template if it is missing.
# It never overwrites your secrets file. It restarts the relay only if secrets exist.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/mrinaljhunjhunwala-ui/nse-smart-investor.git}"
BRANCH="${BRANCH:-main}"
APP_DIR=/opt/nse-smart-investor
VENV="$APP_DIR/.venv-relay"
ENV_FILE=/etc/nse-price-relay.env
UNIT=/etc/systemd/system/nse-price-relay.service
SVC_USER=nserelay

if [ "$(id -u)" -ne 0 ]; then
  echo "Please run with sudo:  sudo bash $0" >&2
  exit 1
fi

echo "==> Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y -qq
apt-get install -y -qq git python3 python3-venv python3-pip ca-certificates >/dev/null

echo "==> Service user '$SVC_USER'"
id -u "$SVC_USER" >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$SVC_USER"

echo "==> Code in $APP_DIR ($BRANCH)"
if [ -d "$APP_DIR/.git" ]; then
  git config --global --add safe.directory "$APP_DIR" || true
  git -C "$APP_DIR" fetch --quiet origin "$BRANCH"
  git -C "$APP_DIR" checkout --quiet "$BRANCH"
  git -C "$APP_DIR" reset --quiet --hard "origin/$BRANCH"
else
  git clone --quiet --depth 50 --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
chown -R "$SVC_USER:$SVC_USER" "$APP_DIR"

echo "==> Python virtualenv (relay requirements only)"
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$APP_DIR/deploy/oracle-relay/requirements.txt"
chown -R "$SVC_USER:$SVC_USER" "$VENV"

# Angel's instrument list is a large JSON file; a 1 GB VM needs swap to parse it.
MEM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
if [ "$MEM_MB" -lt 2000 ] && ! swapon --show | grep -q /swapfile; then
  echo "==> Adding a 2 GB swap file (this VM has ${MEM_MB} MB RAM)"
  [ -f /swapfile ] || { fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048; }
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "==> Secrets file $ENV_FILE"
if [ ! -f "$ENV_FILE" ]; then
  install -m 600 -o root -g root "$APP_DIR/deploy/oracle-relay/nse-price-relay.env.example" "$ENV_FILE"
  echo "    created from the template — fill it in:  sudo nano $ENV_FILE"
else
  chmod 600 "$ENV_FILE"
  echo "    exists — left unchanged"
fi

echo "==> systemd unit"
install -m 644 "$APP_DIR/deploy/oracle-relay/nse-price-relay.service" "$UNIT"
# NSE end-of-day downloads (NSE refuses GitHub's runners; this VM's Indian IP gets through).
install -m 644 "$APP_DIR/deploy/oracle-relay/nse-eod-refresh.service" /etc/systemd/system/nse-eod-refresh.service
install -m 644 "$APP_DIR/deploy/oracle-relay/nse-eod-refresh.timer" /etc/systemd/system/nse-eod-refresh.timer
# Keeps the Always Free VM from being reclaimed as idle (see nse-keepbusy.service).
install -m 644 "$APP_DIR/deploy/oracle-relay/nse-keepbusy.service" /etc/systemd/system/nse-keepbusy.service
install -m 644 "$APP_DIR/deploy/oracle-relay/nse-keepbusy.timer" /etc/systemd/system/nse-keepbusy.timer
systemctl daemon-reload
systemctl enable nse-price-relay >/dev/null 2>&1
systemctl enable --now nse-keepbusy.timer >/dev/null 2>&1

if grep -Eq '^ANGEL_API_KEY=.+' "$ENV_FILE" && grep -Eq '^DATABASE_URL=.+' "$ENV_FILE"; then
  systemctl restart nse-price-relay
  systemctl enable --now nse-eod-refresh.timer >/dev/null 2>&1
  echo "==> Relay (re)started; EOD download timer on (systemctl list-timers nse-eod-refresh)."
  echo "    Watch it with:  sudo journalctl -u nse-price-relay -f"
else
  echo "==> Not started yet: put your secrets in $ENV_FILE, then run"
  echo "    sudo systemctl restart nse-price-relay"
fi
# The code uses India time (IST) itself; the VM's time zone does not matter.
echo "Done."
