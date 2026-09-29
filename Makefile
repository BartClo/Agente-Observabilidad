COMPOSE = docker compose
RUN = $(COMPOSE) run --rm app

.PHONY: build lock check lint format typecheck test coverage evals run shell down logs \
	rag-init-db rag-ingest rag-query

build:
	$(COMPOSE) build

# Genera/actualiza uv.lock dentro del contenedor (unico lugar con uv). Correr tras
# tocar pyproject.toml y commitear el uv.lock resultante.
lock:
	$(RUN) uv lock

check: lint typecheck test coverage

lint:
	$(RUN) uv run ruff check .

format:
	$(RUN) uv run ruff format .

typecheck:
	$(RUN) uv run mypy .

test:
	$(RUN) uv run pytest -m "not eval"

# Regla del framework: domain/ (logica de negocio) exige >=90% de cobertura.
coverage:
	$(RUN) uv run pytest domain --cov=domain --cov-report=term-missing --cov-fail-under=90

evals:
	$(RUN) uv run pytest -m eval

run:
	$(COMPOSE) up app postgres

shell:
	$(RUN) bash

down:
	$(COMPOSE) down -v

# Ver rag/README.md. Ej: make rag-ingest COLLECTION=demo SRC=agents/_template/skills
rag-init-db:
	$(RUN) uv run python -m rag.cli init-db

rag-ingest:
	$(RUN) uv run python -m rag.cli ingest $(COLLECTION) $(SRC)

rag-query:
	$(RUN) uv run python -m rag.cli query $(COLLECTION) "$(Q)"
