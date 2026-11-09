#!/usr/bin/env bash
# Instalator Strażnika na hoście (Ubuntu 24.04). Uruchamiać jako root. Idempotentny.
# Nie dotyka reguł ufw ani konfiguracji SSH.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_DIR="$(dirname "$SCRIPT_DIR")"          # katalog straznik/ z repo
BOUNCER_CFG=/etc/crowdsec/bouncers/crowdsec-firewall-bouncer.yaml

[ "$(id -u)" -eq 0 ] || { echo "Uruchom jako root." >&2; exit 1; }

echo "== 1. CrowdSec (pakiety) =="
if [ ! -e /etc/apt/sources.list.d/crowdsec_crowdsec.list ] && ! ls /etc/apt/sources.list.d/ 2>/dev/null | grep -qi crowdsec; then
  curl -fsSL https://install.crowdsec.net | sh
fi
apt-get install -y crowdsec crowdsec-firewall-bouncer-iptables

echo "== 2. Kolekcje =="
cscli collections install crowdsecurity/linux crowdsecurity/sshd crowdsecurity/apache2 \
  || echo "UWAGA: cscli collections install zwrócił błąd (kolekcje mogą być już zainstalowane)"

COLS="$(cscli collections list -o json)"
for col in crowdsecurity/linux crowdsecurity/sshd crowdsecurity/apache2; do
  echo "$COLS" | grep -qF "$col" || { echo "BŁĄD: kolekcja $col nie jest zainstalowana" >&2; exit 1; }
done

echo "== 2b. Allowlista (blokuje też decyzje CAPI i ręczne) =="
if ! cscli allowlists --help >/dev/null 2>&1; then
  echo "BŁĄD: ta wersja CrowdSec nie ma 'cscli allowlists' (wymagana >= 1.6.8). Zaktualizuj pakiet crowdsec i uruchom ponownie." >&2
  exit 1
fi
cscli allowlists inspect straznik >/dev/null 2>&1   || cscli allowlists create straznik -d "Strażnik: Tailscale, localhost, Docker"
cscli allowlists add straznik 100.64.0.0/10 127.0.0.0/8 172.16.0.0/12 fd7a:115c:a1e0::/48 ::1/128   || echo "UWAGA: cscli allowlists add zwrócił błąd (wpisy mogą już istnieć) - sprawdzam niżej"
for cidr in 100.64.0.0/10 127.0.0.0/8 172.16.0.0/12 fd7a:115c:a1e0::/48 ::1/128; do
  cscli allowlists inspect straznik | grep -qF "$cidr"     || { echo "BŁĄD: brak $cidr w allowliście straznik" >&2; exit 1; }
done

echo "== 3. Konfiguracja CrowdSec =="
install -d /etc/crowdsec/acquis.d /etc/crowdsec/parsers/s02-enrich /var/lib/straznik
install -m 644 "$SCRIPT_DIR/crowdsec/acquis-korczaka.yaml" /etc/crowdsec/acquis.d/korczaka.yaml
install -m 644 "$SCRIPT_DIR/crowdsec/whitelist-straznik.yaml" /etc/crowdsec/parsers/s02-enrich/straznik-whitelist.yaml

echo "== 4. Bouncer: iptables_chains =="
[ -f "$BOUNCER_CFG" ] || { echo "Brak $BOUNCER_CFG" >&2; exit 1; }
[ -f "$BOUNCER_CFG.straznik-orig" ] || cp -p "$BOUNCER_CFG" "$BOUNCER_CFG.straznik-orig"
python3 - "$BOUNCER_CFG" "$SCRIPT_DIR/crowdsec/bouncer-override.yaml" <<'PY'
import sys, yaml
cfg_path, override_path = sys.argv[1], sys.argv[2]
with open(cfg_path) as f:
    cfg = yaml.safe_load(f)
with open(override_path) as f:
    chains = yaml.safe_load(f)["iptables_chains"]
if cfg.get("iptables_chains") != chains:
    cfg["iptables_chains"] = chains
    with open(cfg_path, "w") as f:
        yaml.safe_dump(cfg, f, default_flow_style=False, sort_keys=False)
    print("iptables_chains ustawione:", chains)
else:
    print("iptables_chains bez zmian:", chains)
PY

echo "== 5. Przeładowanie usług =="
install -d /etc/systemd/system/crowdsec-firewall-bouncer.service.d
install -m 0644 "$SCRIPT_DIR/systemd/crowdsec-firewall-bouncer-straznik.conf"   /etc/systemd/system/crowdsec-firewall-bouncer.service.d/straznik.conf
systemctl daemon-reload
systemctl restart crowdsec
systemctl restart crowdsec-firewall-bouncer

echo "== 6. Pakiet do /opt/straznik =="
install -d /opt/straznik
rm -rf /opt/straznik/straznik
tar -C "$PKG_DIR" --exclude=tests --exclude=__pycache__ --exclude=pytest.ini --exclude=deploy --exclude='*.pyc' -cf - . \
  | tar -C /opt/straznik -xf -

echo "== 7. systemd =="
for u in "$SCRIPT_DIR"/systemd/straznik-*.service "$SCRIPT_DIR"/systemd/straznik-*.timer; do
  install -m 644 "$u" /etc/systemd/system/
done
systemctl daemon-reload
# straznik-update.timer tylko instalujemy - włączenie po przejrzeniu `python3 -m straznik.updater --dry-run`
systemctl enable --now straznik-watch.timer straznik-report.timer straznik-scan.timer

echo
echo "== Weryfikacja =="
cscli version || true
cscli allowlists inspect straznik || true
cscli collections list || true
cscli bouncers list || true
systemctl is-active crowdsec crowdsec-firewall-bouncer || true
iptables -S DOCKER-USER | head || true
ip6tables -S DOCKER-USER | head || true
systemctl list-timers 'straznik-*' || true
