COMPOSE_FILE := docker-compose.ai-repo.yml
PROJECT_DIR := $(shell cd "$(dir $(lastword $(MAKEFILE_LIST)))" && pwd)

.PHONY: ai-up ai-down ai-migrate ai-index ai-api ai-query ai-graph ai-logs

# === Infrastructure ===

ai-up:
	docker compose -f $(COMPOSE_FILE) up -d
	@echo "Waiting for Postgres to be ready..."
	@sleep 3
	@echo "AI Repo Postgres is up on port 5435"

ai-down:
	docker compose -f $(COMPOSE_FILE) down

ai-migrate:
	@echo "Migrations are auto-applied on container init via /docker-entrypoint-initdb.d/"
	@echo "To force re-migrate, run: make ai-down && docker volume rm kontekst-ai_ai_repo_pgdata && make ai-up"

ai-logs:
	docker compose -f $(COMPOSE_FILE) logs -f

# === Application ===

ai-index:
	python -m ai_repo index $(ARGS)

ai-api:
	python -m ai_repo serve

ai-query:
	python -m ai_repo query $(ARGS)

ai-graph:
	python -m ai_repo graph $(ARGS)

# === Shortcuts ===

ai-reset: ai-down
	docker volume rm kontekst-ai_ai_repo_pgdata 2>/dev/null || true
	$(MAKE) ai-up
