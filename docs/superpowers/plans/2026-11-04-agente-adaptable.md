# Agente adaptable a otros ambientes: plan

**Meta:** conectar el agente a otro ambiente Grafana + Prometheus + Loki + Kubernetes con un
archivo de perfil, sin tocar código. Solo en `feature/jira`; `master` (tesis) no recibe esto.

**Regla:** sin `AIOPS_PERFIL` la conducta es idéntica a la actual. El LLM nunca escribe consultas
ni comandos; la política en código sigue decidiendo.

| Tarea | Entrega |
|---|---|
| J1 | `infra/perfil.py`: YAML validado al cargar (categorías, alertas, señales, consultas, runbook, acción, nivel). Un perfil no aprobado no carga |
| J2 | Webhook con mapeo de campos del perfil; formato Grafana por defecto; misma autenticación; el entorno sale del perfil, nunca del payload |
| J3 | Con perfil, una alerta fuera de catálogo la atiende un agente con solo tools de lectura y `escalar_a_humano` |
| J4 | Encabezados de autenticación para Prometheus/Loki (Mimir, Thanos, Grafana Cloud), sin secretos en el perfil |
| J5 | Kubernetes: namespaces permitidos y mapa servicio → namespace, deployment y selector |
| J6 | Nivel por categoría (por defecto observación), con `AIOPS_AUTONOMY_LEVEL` como tope global; reanudar nivel 2 tras la aprobación |
| J7 | `scripts/conectar_ambiente.py`: borrador de perfil heurístico, `aprobado: false`, todo en observación |
| J8 | Test de extremo a extremo con Prometheus falso y nombres distintos; documentación |

**Fuera de alcance:** adaptadores de Datadog, Elastic u otros (el puerto `ObservabilidadPort`
queda disponible), backend de acciones por webhook y propuesta del perfil por LLM.

**Verificación:** tests en el host sin servicios. Nada se levanta ni se prueba en vivo en este plan.
