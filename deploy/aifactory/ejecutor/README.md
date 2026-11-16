# Ejecutor de acciones en el host (ADR-003)

El agente corre en Docker Compose **sin docker.sock**. Para reiniciar un servicio deja una
solicitud en un directorio compartido; este ejecutor (unidad systemd del host, usuario del
grupo docker) la valida con **sus propias reglas** y ejecuta `docker restart`.

```
agente (contenedor)  --escribe-->  /var/lib/aiops/solicitudes/pendientes/<id>.json
ejecutor (host)      --valida: accion, lista de permitidos, limite por hora, vencimiento
                     --docker restart --time 30 ia-factory-<servicio>
                     --escribe-->  /var/lib/aiops/solicitudes/resultados/<id>.json
agente               --lee el resultado y VERIFICA en Prometheus que el servicio volvio
```

Si el contenedor del agente se compromete, solo puede **pedir** reiniciar un servicio que el
host ya autorizo, y como mucho 3 veces por hora por servicio.

## Instalar (alguien con sudo)

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin -G docker aiops-exec
sudo install -d -o aiops-exec -g aiops-exec -m 0770 /var/lib/aiops/solicitudes
sudo install -d -m 0755 /etc/aiops
sudo cp deploy/aifactory/ejecutor/servicios-permitidos.example /etc/aiops/servicios-permitidos
sudo nano /etc/aiops/servicios-permitidos       # dejar SOLO lo que se puede reiniciar
sudo cp deploy/aifactory/ejecutor/aiops-ejecutor.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now aiops-ejecutor
journalctl -u aiops-ejecutor -f                 # debe decir "escuchando ..."
```

El contenedor del agente escribe como root en el directorio montado, y el ejecutor lee y
borra esas solicitudes porque el directorio es suyo.

## Activar en el agente

En `deploy/aifactory/aiops.env`:

```
AIOPS_ACTIONS=compose
AIOPS_AUTONOMY_LEVEL=3
AIOPS_ALLOWED_ENVS=dev          # el entorno del perfil (dev/qa)
```

En el perfil, `nivel: 3` en las categorias que puede resolver solo. Luego
`docker compose -p aiops ... up -d`.

Lo que sigue escalando aunque este activo:
- alertas de severidad **critica** (politica del agente: fuera del alcance autonomo);
- servicios que no estan en `/etc/aiops/servicios-permitidos`;
- confianza bajo el umbral (0,80) o kill switch activo.

## Probar sin el agente

```bash
id=$(python3 -c "import uuid;print(uuid.uuid4().hex)")
echo "{\"accion\":\"restart_service\",\"servicio\":\"frontend\",\"ts\":$(date +%s)}" \
  | sudo -u aiops-exec tee /var/lib/aiops/solicitudes/pendientes/$id.json
sleep 3; sudo cat /var/lib/aiops/solicitudes/resultados/$id.json
```

## Desactivar

`AIOPS_ACTIONS=ninguna` en aiops.env (el agente vuelve a nivel 1) o
`sudo systemctl stop aiops-ejecutor` (las solicitudes vencen y el agente escala).
