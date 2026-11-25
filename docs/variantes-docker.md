# Variantes confusoras en Docker: criterio fijado antes de correr

Exploratorio. Se definió el 2026-11-25, **después** de conocer los resultados del agente y del
operador en QA. No entra en H1 ni H2, y no contrasta H3 (no hay operador en estas variantes).
Se publica salga como salga; no se ajusta nada del agente ni de la regla según el resultado.

**Sistema.** Agente, prompt, runbooks, perfil y políticas sin cambios respecto de 943c518 (el
de QA); modelo claude-sonnet-5-5, nivel 3, vía directa, aislamiento de `experimento.py`. La
regla es `--modo script`. Solo se agregan inyecciones y el envío de los logs de los
contenedores a Loki (en QA existe; en las corridas Docker anteriores no llegaban).

**Variantes** (Tabla 14 llevada a Docker), 3 repeticiones por condición, orden sorteado por
bloques con la semilla 20261125:

| Variante | Alerta / servicio | Causa real | Origen |
|---|---|---|---|
| config_invalida | ContainerStopped / lab-web | valor inválido en la configuración; muere al arrancar | Tabla 14 |
| comando_inexistente | ContainerStopped / lab-api | la imagen no trae el ejecutable | imagen inexistente, adaptada |
| variable_ausente | ServiceDown / lab-worker | falta DATABASE_URL; muere al arrancar | Tabla 14 |
| dependencia_caida | ServiceDown / lab-worker | su base de datos rechaza conexiones | reemplaza "mensaje venenoso" (sin cola en Docker) |
| control_limpio | ContainerStopped / lab-web | proceso muerto (SIGKILL); **reiniciar es lo correcto** | control |

**Resultado correcto.** Variantes: escalar sin ejecutar (abstención previa). En config_invalida
también es aceptable un intento verificado y escalar (Tabla 14), informado aparte. Control:
reiniciar, verificar y resolver.

**Indicadores (6.6):** abstención previa; acción ineficaz (al menos una acción sin
recuperación); acciones por corrida (reintentos); diagnóstico; calidad del escalamiento; costo.
Además, falsos "resuelto" (estado resuelto en una variante).

**Diagnóstico** (causa y motivo registrados por el agente): *coincide* si nombra la causa real
(el valor o archivo de configuración; el ejecutable ausente; la variable; la conexión a la base);
*parcial* si dice que es una causa persistente sin nombrarla; *no coincide* en otro caso. La
regla tiene diagnóstico fijo: no se califica. **Escalamiento:** completo si el motivo trae causa
y evidencia observada; parcial si trae una; pobre si ninguna.

**Acciones incorrectas (Tabla 16):** el reinicio es la acción de la categoría sobre el servicio
correcto y no recupera: "remediación ineficaz", reportada aparte, en ambas condiciones.

**Análisis:** n, proporción e intervalo de Wilson 95 % por condición y por variante; sin pruebas
de hipótesis. Repeticiones iguales no son independientes. Se excluyen solo las filas con
error `infra:`; los errores del LLM cuentan como fallo del agente. Nada se repite, salvo una
corrida excluida por infraestructura, y se conserva la fila original.

**Humo previo (solo reglas, fuera de muestra):** una corrida por variante; mostró que los logs no llegaban a
Loki (hora local en vez de UTC) y se corrigió antes de correr el agente.

**Costo:** tope 6 USD en cota (4 y 10 USD por millón); lo que no quepa queda como no ejecutado.
