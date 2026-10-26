---
servicios:
tipo: guia
vigente_desde: 2026-08-01
obsoleto: false
origen_dato: sintetico
---
# Guía de guardia: severidades y escalamiento

**Severidades.**
- **Crítica:** caída total o pérdida de datos. Se avisa de inmediato a la persona de
  guardia y a la jefatura de operaciones. Nunca se resuelve sin supervisión humana.
- **Alta:** un servicio de negocio degradado o caído. Respuesta en 15 minutos.
- **Media:** degradación parcial o riesgo cercano (cola sin consumidores, certificado por
  vencer). Respuesta en 1 hora.
- **Baja:** informativa.

**Cuándo escalar a una persona.**
1. Cualquier incidente de severidad crítica.
2. La acción automática no recuperó el servicio o el problema reaparece tras actuar.
3. Hay un despliegue o cambio de configuración reciente relacionado (ver
   `cambios-recientes.md`).
4. La evidencia de las métricas y los logs no coincide con el diagnóstico probable.
5. Una dependencia (broker, base de datos, billing) también está degradada.

**Matriz de escalamiento.**
| Servicio | Primera línea | Segunda línea |
|---|---|---|
| api, worker | Guardia de Pedidos | Líder técnico de Pedidos |
| checkout, billing | Guardia de Pagos | Líder técnico de Pagos |
| gateway, certificados | Guardia de Plataforma | Jefatura de operaciones |

**Qué incluir al escalar.** Servicio y alerta, hora de inicio, qué se observó (métricas y
logs), qué se intentó y su resultado, y qué se descartó. Quien recibe el aviso no debería
tener que repetir el diagnóstico.

**Ventanas de cambio.** Los despliegues se hacen de lunes a jueves en horario laboral.
Durante un despliegue en curso no se reinician servicios sin coordinar con quien despliega.
