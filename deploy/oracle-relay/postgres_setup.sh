#!/usr/bin/env bash
# deploy/oracle-relay/postgres_setup.sh — the app's Postgres on the relay VM (replaces Neon).
#
#   curl -fsSL https://raw.githubusercontent.com/mrinaljhunjhunwala-ui/nse-smart-investor/main/deploy/oracle-relay/postgres_setup.sh | sudo bash
#
# Why: Neon's free plan caps data transfer at ~5 GB a month and locked the database twice in
# Nov 2026. This VM is Oracle Always Free (about 10 TB a month of outbound transfer), so the
# same Postgres the app already speaks runs here instead. Keep it Always Free: nothing in this
# script needs a paid Oracle resource.
#
# Safe to run again. It installs PostgreSQL 16, creates the `nse` database and `nse_app` user
# with a generated password (kept in /etc/nse-postgres.url, root-only, never printed), accepts
# only encrypted (SSL) password logins from outside, opens port 5432 in the VM firewall, and
# installs a nightly backup timer (7 days kept in /var/backups/nse-postgres).
# Port 5432 must ALSO be opened in the Oracle console (VCN security list), see README.
set -euo pipefail

DB=nse
ROLE=nse_app
URL_FILE=/etc/nse-postgres.url
APP_DIR=/opt/nse-smart-investor
PUBLIC_IP="${PUBLIC_IP:-$(curl -fsS --max-time 5 https://ifconfig.me || true)}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Please run with sudo" >&2
  exit 1
fi

echo "==> Installing PostgreSQL"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y -qq
apt-get install -y -qq postgresql postgresql-contrib iptables-persistent >/dev/null

PGVER=$(ls /etc/postgresql | sort -V | tail -1)
CONF=/etc/postgresql/$PGVER/main

echo "==> Database '$DB' and user '$ROLE'"
if [ ! -f "$URL_FILE" ]; then
  PASS=$(openssl rand -hex 24)
  sudo -u postgres psql -qtAc "DO \$\$BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='$ROLE') THEN CREATE ROLE $ROLE LOGIN; END IF; END\$\$;"
  sudo -u postgres psql -qc "ALTER ROLE $ROLE PASSWORD '$PASS';"
  (umask 077; echo "postgresql://$ROLE:$PASS@$PUBLIC_IP:5432/$DB?sslmode=require" > "$URL_FILE")
  chmod 600 "$URL_FILE"
  unset PASS
  echo "    password generated; connection URL saved in $URL_FILE (root only)"
else
  echo "    exists — password left unchanged"
fi
sudo -u postgres psql -qtAc "SELECT 1 FROM pg_database WHERE datname='$DB'" | grep -q 1 \
  || sudo -u postgres createdb -O "$ROLE" "$DB"

echo "==> Settings (listen on all addresses, SSL, sized for this VM)"
cat > "$CONF/conf.d/nse.conf" <<'EOF'
listen_addresses = '*'
ssl = on
password_encryption = scram-sha-256
max_connections = 100
shared_buffers = 512MB
effective_cache_size = 2GB
work_mem = 8MB
maintenance_work_mem = 128MB
idle_in_transaction_session_timeout = '10min'
log_min_duration_statement = 2000
EOF
chmod 644 "$CONF/conf.d/nse.conf"
# Outside logins: SSL + password only, for the app user and database only.
HBA="$CONF/pg_hba.conf"
grep -q "nse-smart-investor" "$HBA" || cat >> "$HBA" <<EOF
# nse-smart-investor: remote app logins (SSL + scram password only)
hostssl $DB $ROLE 0.0.0.0/0 scram-sha-256
hostssl $DB $ROLE ::/0      scram-sha-256
EOF
systemctl restart postgresql

echo "==> VM firewall: allow 5432"
iptables -C INPUT -p tcp -m state --state NEW --dport 5432 -j ACCEPT 2>/dev/null \
  || iptables -I INPUT 5 -p tcp -m state --state NEW --dport 5432 -j ACCEPT
netfilter-persistent save >/dev/null

echo "==> Nightly backup timer"
install -d -m 700 -o postgres -g postgres /var/backups/nse-postgres
install -m 644 "$APP_DIR/deploy/oracle-relay/nse-pg-backup.service" /etc/systemd/system/nse-pg-backup.service
install -m 644 "$APP_DIR/deploy/oracle-relay/nse-pg-backup.timer" /etc/systemd/system/nse-pg-backup.timer
systemctl daemon-reload
systemctl enable --now nse-pg-backup.timer >/dev/null 2>&1

echo "==> Done. Postgres $PGVER is listening on 5432."
echo "    The connection URL is in $URL_FILE (sudo cat it only when you need to copy it)."
