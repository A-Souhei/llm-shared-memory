# Biblion — Makefile
# Default port (must match docker-compose.yml and config.py)
PORT ?= 18765

.PHONY: help setup build run run-d stop logs clean run-with-qdrant run-with-ollama run-full ollama-pull

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

# ── Local (no Docker) ────────────────────────────────────────────────────────

setup: ## Install dependencies locally with uv
	uv sync

run: ## Run server locally (foreground)
	uv run biblion

# ── Docker ───────────────────────────────────────────────────────────────────

build: ## Build the Docker image
	docker compose build

run-d: ## Start biblion only (detached) — uses external Qdrant via QDRANT_URL
	docker compose up -d

run-with-qdrant: ## Start biblion + bundled Qdrant (detached)
	docker compose --profile qdrant up -d

run-with-ollama: ## Start biblion + bundled Ollama (detached)
	docker compose --profile ollama up -d

run-full: ## Start biblion + bundled Qdrant + bundled Ollama (detached)
	docker compose --profile qdrant --profile ollama up -d

up: ## Start the stack in foreground
	docker compose up

stop: ## Stop and remove containers
	docker compose down

logs: ## Tail logs from the biblion container
	docker compose logs -f biblion

clean: ## Remove containers, images, and qdrant volume
	docker compose down --rmi local --volumes --remove-orphans

# ── Helpers ──────────────────────────────────────────────────────────────────

ollama-pull: ## Pull the tinyllama model into the bundled Ollama container
	docker compose --profile ollama exec ollama ollama pull tinyllama

status: ## Check /biblion/status endpoint
	curl -s http://localhost:$(PORT)/biblion/status | python3 -m json.tool

health: ## Check /health endpoint
	curl -s http://localhost:$(PORT)/health
