---
name: tarifario
description: Como estan armadas las zonas y vigencias del tarifario de envios.
---

# Tarifario

Zonas: `NORTE`, `CENTRO`, `SUR` (ver `domain/cotizador_core/zonas.py` para el
mapeo ciudad -> zona). Cada zona tiene tarifas vigentes por rango de fechas
(`domain/cotizador_core/tarifario.py`): tarifa base + costo por kg.

Si una fecha no cae dentro de ninguna vigencia, `cotizar_envio` devuelve un
error explicito. No hay que inventar un monto en ese caso, ni "aproximar" con
la tarifa mas cercana.
