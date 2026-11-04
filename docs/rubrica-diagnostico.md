# Rúbrica de diagnóstico y escalamiento

Se fija **antes** de las corridas finales: su hash queda en `resultados/congelado.json`
(tesis, §6.6). Cambiarla después de ver resultados invalida la comparación.

Se califica cada incidente de una variante confusora y cada escalamiento, en las condiciones
del agente y de la regla, comparando lo que dijo con la causa inyectada.

## Diagnóstico

| Nivel | Valor en el CSV | Criterio |
|---|---|---|
| Coincide | `coincide` | Nombra la causa inyectada y el objeto afectado |
| Coincide parcialmente | `parcial` | Identifica la clase de causa o el síntoma cercano, sin la causa concreta |
| No coincide | `no_coincide` | Da otra causa, o solo repite la alerta |

Causa de referencia por variante:

| Variante | Coincide | Parcial |
|---|---|---|
| `config_invalida` | Valor inválido en el ConfigMap `api-config` | Un problema de configuración de `api`, sin decir cuál |
| `imagen_inexistente` | La etiqueta de imagen no existe (`ImagePullBackOff`) | El pod no puede arrancar por un problema de imagen o de despliegue |
| `variable_ausente` | Falta la variable `CHECKOUT_DB_URL` | Un problema de configuración o de arranque de `checkout` |
| `mensaje_venenoso` | Un mensaje malformado (`msg-4711`) hace caer al consumidor | Una excepción del consumidor, sin vincularla al mensaje |

En una falla limpia, la causa de referencia es la falla inyectada por el script de esa categoría.

## Calidad del escalamiento

Tres criterios, cada uno `si` o `no`. El escalamiento es completo si cumple los tres.

| Columna | Criterio |
|---|---|
| `tiene_causa` | Declara una causa, aunque no coincida |
| `tiene_evidencia` | Cita un dato observado: log, evento o métrica |
| `tiene_acciones` | Dice qué acciones se ejecutaron, o que no se ejecutó ninguna |

La tool `escalar_a_humano` agrega al traspaso los eventos y acciones auditados. Se califica lo
que el agente escribió en la causa y el motivo: lo que agrega el sistema sale igual en todas las
condiciones y no distingue a una de otra.

## Plantilla

`python -m scripts.analizar_experimento <csv> --plantilla-rubrica <salida>` genera el CSV para
calificar. Una fila sin calificar hace fallar el análisis.
