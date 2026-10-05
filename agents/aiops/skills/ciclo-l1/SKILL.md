---
name: ciclo-l1
description: Catalogo L1, niveles de autonomia y por que una accion se deniega o escala.
---

# Ciclo de incidentes L1

## Catalogo (domain/aiops_core/catalogo.py)

| Categoria | Alerta | Runbook | Accion | Rollback | Sano si |
|---|---|---|---|---|---|
| servicio_detenido | ServiceDown | RB-001 | restart_service | - | up >= 1 |
| disco_lleno | DiskUsageHigh | RB-002 | compress_old_logs | restore_compressed_logs | disk_usage_percent <= 85 |
| pod_fallido | PodCrashLooping, PodFailed | RB-003 | recreate_pod | - | pod_ready >= 1 |
| cola_detenida | QueueStalled | RB-004 | restart_consumer | - | queue_consumers_active >= 1 |
| certificado_por_vencer | CertExpiringSoon | RB-005 | ninguna (escalar) | - | cert_days_remaining >= 14 |

## Autonomia (AIOPS_AUTONOMY_LEVEL)

- 0-1: no ejecuta nada, solo diagnostica y recomienda/escala.
- 2: ejecuta con aprobacion humana.
- 3: ejecuta sola las acciones de bajo riesgo.
- 4: ademas revierte sola (rollback).

## Motivos de denegacion frecuentes

kill switch activo, entorno o servicio no autorizado, severidad critica,
confianza bajo el umbral, runbook incompatible, limite de reintentos. En todos
los casos la respuesta correcta es `escalar_a_humano` con ese motivo.
