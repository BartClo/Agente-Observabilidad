# Cerrar las brechas entre la tesis y el experimento

**Objetivo:** que `scripts/experimento.py` y el análisis produzcan lo que prometen los §6.1,
§6.2, §6.5 y §6.6 de la tesis, y que puedan apuntar a un clúster real.

**Restricciones:** rama `master`; sin push; sin levantar nada mientras se implementa; las
corridas (M6) y el congelado (M7) quedan fuera. Lo que necesite clúster queda declarado como
no probado.

## M2. Variantes confusoras (§6.2, Tabla 13)
- `scripts/fallas/var_*.sh` y `rev_*.sh`: configuración inválida, imagen inexistente, variable
  obligatoria ausente y mensaje venenoso; cada inyección tiene su reversión completa.
- `k8s-lab/`: ConfigMap de `api`, `strategy: Recreate` en `api` (si no, el pod viejo sigue sano
  y no hay alerta), variable obligatoria en `checkout`, «cola» persistente en `worker`.
- `experimento.VARIANTES` y `--variantes`, 3 corridas por variante.
- `Corrida.variante`: fuera del denominador de la TRA.
- Prueba: los scripts existen y el análisis no cuenta variantes como elegibles.

## M3. Rigor y entorno real (§6.1, §6.5, §6.6)
- `plan_corridas`: bloques sorteados con `--semilla`; la semilla va en el CSV.
- Estabilidad de 60 s con el servicio sano antes de cada corrida; seguimiento de 15 min.
- Marcas t0–t5. t5 sale de un verificador externo: consulta la señal **sana** (no la ausencia
  de anomalía, que también se da sin datos) y exige dos lecturas seguidas.
- `mttr_s` = t5 − t2; el cierre interno va en `cierre_interno_s`.
- `--modo reglas`: `domain/aiops_core/reglas.py`, también en el worker con
  `AIOPS_ATENDEDOR=reglas`.
- Entorno real: `EXP_NAMESPACE` con lista declarada y etiqueta en el namespace,
  `EXP_K8S_API`, `EXP_WORKER_EXTERNO`, filtro de namespace en las consultas.

## M4. Métricas (§6.5, §6.6)
- `ResultadoAccion` (Tabla 15) calculado por corrida; `accion_incorrecta` son los tres primeros.
- H1 en dos niveles; H2 con media por escenario pareado; H3 separando limpios y variantes, con
  k de n y Wilson.
- Remediación ineficaz, abstención correcta, tiempo hasta el escalamiento, indicadores agente
  contra regla (`--regla`).

## M5. Rúbrica (§6.6)
- `docs/rubrica-diagnostico.md`, con su hash en `congelar.py` junto con los criterios.
- Plantilla de calificación generada desde el CSV; `--calificaciones` la usa en el análisis.

## Fuera de este plan
- M6 (validación en vivo) y M7 (congelado).
- Texto de la tesis.
