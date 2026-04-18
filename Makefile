# Biblion — Makefile
# Default port (must match docker-compose.yml and config.py)
PORT ?= 18765

.PHONY: help setup build build-webui rebuild rebuild-webui run run-d stop logs clean run-with-qdrant run-with-ollama run-with-redis run-with-webui run-full ollama-pull test test-biblion test-indexer logs-webui

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

# ── Local (no Docker) ────────────────────────────────────────────────────────

setup: ## Install dependencies locally with uv
	uv sync

test: test-biblion test-indexer ## Run all endpoint tests (requires live stack)

test-biblion: ## Run biblion endpoint tests against the live container
	bash tests/test_biblion.sh

test-indexer: ## Run indexer endpoint tests against the live container
	bash tests/test_indexer.sh

run: ## Run server locally (foreground)
	uv run biblion

# ── Docker ───────────────────────────────────────────────────────────────────

build: ## Build the biblion Docker image
	docker compose build biblion

build-webui: ## Build the webui Docker image
	docker compose --profile webui build webui

rebuild: ## Rebuild and restart biblion
	docker compose build biblion && docker compose up -d biblion

rebuild-webui: ## Rebuild and restart webui
	docker compose --profile webui build webui && docker compose --profile webui up -d webui

run-d: ## Start biblion only (detached) — uses external Redis via REDIS_URL
	docker compose up -d

run-with-qdrant: ## Start biblion + bundled Qdrant (detached)
	docker compose --profile qdrant up -d

run-with-ollama: ## Start biblion + bundled Ollama (detached)
	docker compose --profile ollama up -d

run-with-redis: ## Start biblion + bundled Redis (detached)
	docker compose --profile redis up -d

run-with-webui: ## Start biblion + webui (detached)
	docker compose --profile webui up -d

run-full: ## Run biblion + all optional services
	docker compose --profile qdrant --profile ollama --profile redis up -d

up: ## Start the stack in foreground
	docker compose up

stop: ## Stop and remove containers
	docker compose down

logs: ## Tail logs from the biblion container
	docker compose logs -f biblion

logs-webui: ## Tail logs from the webui container
	docker compose --profile webui logs -f webui

clean: ## Remove containers, images, and qdrant volume
	docker compose down --rmi local --volumes --remove-orphans

# ── Helpers ──────────────────────────────────────────────────────────────────

ollama-pull: ## Pull the tinyllama model into the bundled Ollama container
	docker compose --profile ollama exec ollama ollama pull tinyllama

status: ## Check /biblion/status endpoint
	curl -s http://localhost:$(PORT)/biblion/status | python3 -m json.tool

health: ## Check /health endpoint
	curl -s http://localhost:$(PORT)/health
