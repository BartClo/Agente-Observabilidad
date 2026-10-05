# Plantilla de agente

Para crear un agente nuevo:

1. Copiar esta carpeta a `agents/<tu-agente>/`.
2. Editar `agent.yaml` (`name`, `description`, `model`, `require_approval`).
3. Reescribir `prompt.md`.
4. Reemplazar las tools en `tools.py` (deben ser funciones planas; la logica de
   negocio real vive en `domain/`, no aqui).
5. Reemplazar/borrar `skills/`.
6. Escribir evals en `evals/` con `@pytest.mark.eval`.

No hace falta tocar nada en `app/`: `app/loader.py` descubre la carpeta sola en el
proximo arranque (`make run`).

Ver `docs/CREATING_AN_AGENT.md` (etapa 5) para la guia completa.
