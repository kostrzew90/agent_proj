# Proxy Rotation

Proxy rotation jest przygotowane architekturalnie, ale nie aktywne domyślnie.

## Aktywacja

1. Ustaw w `.env`:
```
PROXY_ENABLED=true
PROXY_LIST=socks5://proxy1:1080,socks5://proxy2:1080
PROXY_ROTATION=round_robin
```

2. ProxyManager w `backend/core/proxy_manager.py` przejmie zarządzanie.

## Kiedy aktywować

- Gdy konkretne źródło zaczyna banować IP
- Obserwuj logi: `WARNING: source_name ban detected`
- Zacznij od darmowych proxy SOCKS5, potem płatne rotacyjne jeśli potrzeba

## Obsługiwane typy proxy

- `socks5://host:port`
- `http://host:port`
- `http://user:pass@host:port`
