# Imagen del servicio `app`: Python 3.12 + uv. Todo lint/mypy/pytest/run corre aqui adentro.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /workspace

# Capa de dependencias separada del codigo: `docker compose run` con el repo montado
# en /workspace no invalida /opt/venv, asi no se reinstala nada en cada comando.
COPY pyproject.toml ./
RUN uv sync --no-install-project

COPY . .
RUN uv sync --no-install-project

CMD ["bash"]
