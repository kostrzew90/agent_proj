# Strażnik — instalacja na hoście

`install.sh` (jako root, można uruchamiać wielokrotnie):

1. dodaje repozytorium CrowdSec i instaluje `crowdsec` oraz `crowdsec-firewall-bouncer-iptables`;
2. instaluje kolekcje `linux`, `sshd`, `apache2`;
3. kopiuje acquis Korczaki (`/etc/crowdsec/acquis.d/korczaka.yaml`) i białą listę (`s02-enrich/straznik-whitelist.yaml`);
4. ustawia w konfiguracji bouncera `iptables_chains: [INPUT, DOCKER-USER]` (kopia oryginału: `<plik>.straznik-orig`);
5. restartuje `crowdsec` i `crowdsec-firewall-bouncer`;
6. kopiuje pakiet do `/opt/straznik`;
7. instaluje jednostki systemd i włącza 3 timery (`watch`, `report`, `scan`); `straznik-update.timer` tylko instaluje - po przejrzeniu `--dry-run`: `systemctl enable --now straznik-update.timer`.

Tworzy allowlistę CrowdSec `straznik` (Tailscale, localhost, Docker; chroni też przed decyzjami z CAPI i ręcznymi) - cofnięcie: `cscli allowlists delete straznik`. Wymaga CrowdSec >= 1.6.8. Dodaje też drop-in bouncera (start po dockerze, restart przy błędzie) - cofnięcie: usuń `/etc/systemd/system/crowdsec-firewall-bouncer.service.d/straznik.conf`.

Nie zmienia reguł ufw ani konfiguracji SSH.

## Cofnięcie

```bash
systemctl disable --now straznik-{watch,report,update,scan}.timer
rm /etc/systemd/system/straznik-*.{service,timer} && systemctl daemon-reload
cp /etc/crowdsec/bouncers/crowdsec-firewall-bouncer.yaml.straznik-orig /etc/crowdsec/bouncers/crowdsec-firewall-bouncer.yaml
apt-get remove crowdsec crowdsec-firewall-bouncer-iptables
rm -rf /opt/straznik
```
