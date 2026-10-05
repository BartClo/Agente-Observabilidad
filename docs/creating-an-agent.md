# Crear un agente

1. Copiar la plantilla:
   ```bash
   cp -r agents/_template agents/mi-agente
   ```
2. `agent.yaml`: cambiar `name`, `description` (el orquestador enruta por esto),
   `model`, `tools`, `require_approval`.
3. `prompt.md`: reescribir el system prompt.
4. `tools.py`: funciones planas con docstring claro. Solo formatean entrada/salida y
   llaman a `domain/`. Referenciarlas en `agent.yaml` como `tools:mi_funcion`.
5. `domain/<nombre>_core/`: lógica de negocio con tests (cobertura >= 90%).
6. `skills/<skill>/SKILL.md`: opcional; borrar el ejemplo si no se usa.
7. `evals/`: casos con resultado conocido, marcados `@pytest.mark.eval`.

No hay que tocar `app/`: el loader descubre la carpeta en el próximo arranque.

## Opcionales en `agent.yaml`

```yaml
rag:
  collection: mi_coleccion   # ver rag/README.md
  k: 4
mcp_servers:
  mi_servidor:
    transport: stdio
    command: python
    args: ["/ruta/al/server.py"]
require_approval:
  - tool_con_efecto
```

## Verificar

```bash
make check
make evals
```

Ejemplo completo: `agents/cotizador/` con `domain/cotizador_core/`.
