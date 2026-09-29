# cotizador

Agente de ejemplo del framework (no es un producto real): cotiza y confirma
envios contra un tarifario versionado por vigencia con valores `PLACEHOLDER`.

Demuestra:

- Logica de negocio en `domain/cotizador_core/` (regla 1/2), con cobertura
  de tests >= 90%.
- Tool efectiva (`confirmar_cotizacion`) detras de aprobacion humana
  (`require_approval` en `agent.yaml`, regla 6).
- Evals con resultado conocido en `evals/`.

Ver `agents/_template/README.md` para el flujo de copiar esta carpeta y
armar un agente nuevo.
