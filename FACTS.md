# FAKTY
- to jest mono-repo z wieloma projektami: RAG/, Selfmadeagent/, kontekst ai/, VIN OSINT/, trading-app/
- platforma: Windows 11, Docker Desktop, bash shell
- baza n8n: localhost:5432 (user: n8n, pass: n8npass)
- kazdy projekt ma wlasny CLAUDE.md z pelnym kontekstem

# OGRANICZENIA
- nie usuwaj plikow bez potwierdzenia
- nie zgaduj sciezek plikow — przeczytaj najpierw
- nie modyfikuj plikow .env (moga zawierac sekrety)
- nie pushuj do remote bez pytania

# INWARIANTY
- nie modyfikuj plikow poza workspace/
- nie uruchamiaj rm -rf
- nie usuwaj baz danych (DROP DATABASE/DROP TABLE)
- nie zmieniaj docker-compose.yml innych projektow bez pytania
