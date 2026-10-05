COMPOSE = docker compose
RUN = $(COMPOSE) run --rm app

.PHONY: build lock check lint format typecheck test coverage evals run shell down logs \
	rag-init-db rag-ingest rag-query aiops-ingest aiops-demo migrate migrate-down \
	falla-servicio recuperar-servicio falla-disco recuperar-disco falla-pod recuperar-pod \
	falla-cola falla-certificado

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

# Agente aiops: ver docs/aiops-agent.md
aiops-ingest:
	$(RUN) uv run python -m rag.cli ingest aiops_runbooks agents/aiops/runbooks

AIOPS_DEMO_LEVEL ?= 3
aiops-demo:
	$(COMPOSE) run --rm -e AIOPS_AUTONOMY_LEVEL=$(AIOPS_DEMO_LEVEL) app uv run python -m agents.aiops.demo

# Esquema de persistencia de aiops (ver docs/plan-aiops.md Fase 1). `migrate-down`
# revierte todo (solo para desarrollo: borra las tablas aiops_*).
migrate:
	$(RUN) uv run alembic upgrade head

migrate-down:
	$(RUN) uv run alembic downgrade base

# Laboratorio de la Fase 3 (ver k8s-lab/README.md y docs/plan-aiops.md). Requiere
# `docker compose --profile observability up -d` (y el cluster k3d para pod-*).
# Cada falla tiene su recuperacion: make falla-<tipo> / make recuperar-<tipo>.
falla-servicio:
	sh scripts/fallas/servicio_detenido.sh

recuperar-servicio:
	sh scripts/fallas/recuperar_servicio.sh

falla-disco:
	sh scripts/fallas/disco_lleno.sh

recuperar-disco:
	sh scripts/fallas/recuperar_disco.sh

falla-pod:
	sh scripts/fallas/pod_fallido.sh

recuperar-pod:
	sh scripts/fallas/recuperar_pod.sh

falla-cola:
	sh scripts/fallas/cola_detenida.sh

falla-certificado:
	sh scripts/fallas/certificado_por_vencer.sh
