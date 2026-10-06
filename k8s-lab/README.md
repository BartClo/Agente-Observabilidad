# Laboratorio k3d (Fase 3)

Cluster Kubernetes real para el escenario `pod_fallido` del catálogo
(`domain/aiops_core/catalogo.py`). Separado de `docker-compose.yml`: k3d crea sus
propios contenedores Docker (nodos), no es un servicio de compose.

## Instalar k3d

No requiere admin ni Docker Desktop con Kubernetes activado: es un binario único.

```bash
# Windows: bajar k3d-windows-amd64.exe de https://github.com/k3d-io/k3d/releases
#   y ponerlo como k3d.exe en el PATH.
# Linux/Mac: curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | bash
k3d version   # verificado con v5.9.0 en esta sesión
```

## Crear el cluster

```bash
k3d cluster create aiops-lab --agents 1 --wait --timeout 180s
```

**Windows + Git Bash:** `kubectl` corriendo en el host (no en un contenedor) no
resuelve `host.docker.internal`. Arreglar el kubeconfig generado:

```bash
PUERTO=$(docker port k3d-aiops-lab-serverlb | grep 6443 | sed 's/.*://')
kubectl config set-cluster k3d-aiops-lab --server=https://127.0.0.1:$PUERTO
```

## Desplegar kube-state-metrics y el workload de prueba

```bash
kubectl apply -f k8s-lab/namespace.yaml
kubectl apply -f k8s-lab/kube-state-metrics/
kubectl apply -f k8s-lab/workload-api.yaml
```

`kube-state-metrics/nodeport.yaml` expone el NodePort `30080`. Mapearlo a un puerto
del host (una sola vez, sobrevive a reinicios del cluster):

```bash
k3d cluster edit aiops-lab --port-add 30080:30080@loadbalancer
curl http://127.0.0.1:30080/metrics | grep kube_pod_status_ready   # debe responder
```

`docker/prometheus/prometheus.yml` ya apunta a `host.docker.internal:30080` (el
servicio `prometheus` del compose tiene `extra_hosts: host.docker.internal:host-gateway`
para resolverlo desde Linux).

## Simular `pod_fallido`

```bash
kubectl delete pod -n aiops-lab -l app=api   # el Deployment lo recrea
# mientras el pod nuevo no está Ready, kube_pod_status_ready cae a 0
```

## Pausar/reanudar sin perder el estado

```bash
k3d cluster stop aiops-lab     # libera CPU/memoria, no borra nada
k3d cluster start aiops-lab
```

## Verificado en esta sesión (2026-10-05)

- `kube-state-metrics` responde en `127.0.0.1:30080/metrics` con la métrica exacta
  que usa `infra/observabilidad.py` (`kube_pod_status_ready{pod="api-...",condition="true"}`).
- El pipeline completo Grafana→webhook→worker→Postgres se probó contra
  `servicio_detenido` (compose). `PodFailed` también se disparó en vivo contra k3d
  (webhook 200 OK), y en la Fase 4 el agente lo resolvió de verdad (ver abajo).

## Fase 4: el agente actúa sobre el cluster

RBAC mínimo para el agente (solo `pods: list/delete` y `deployments: get/patch` en
`aiops-lab`) y su token:

```bash
kubectl apply -f k8s-lab/rbac-aiops.yaml
mkdir -p k8s-lab/.secrets   # en .gitignore
kubectl -n aiops-lab get secret aiops-agent-token -o jsonpath='{.data.token}'  | base64 -d > k8s-lab/.secrets/token
kubectl -n aiops-lab get secret aiops-agent-token -o jsonpath='{.data.ca\.crt}' | base64 -d > k8s-lab/.secrets/ca.crt
```

El worker corre en docker compose (no como pod), así que usa el token del
ServiceAccount desde afuera. Desde un contenedor, el API server es
`https://host.docker.internal:<puerto de 6443>` (el certificado de k3d incluye ese
nombre, la CA valida de verdad: no hace falta desactivar TLS).

Ciclo completo sin LLM (detectar → recrear el pod → verificar con espera → cerrar):

```bash
sh scripts/fallas/pod_fallido.sh          # pod NotReady (borra /tmp/ok)
PUERTO=$(docker port k3d-aiops-lab-serverlb | grep 6443 | sed 's/.*://')
MSYS_NO_PATHCONV=1 docker compose run --rm \
  -e AIOPS_BACKEND=prometheus -e AIOPS_PROMETHEUS_URL=http://prometheus:9090 \
  -e AIOPS_ACTIONS=k8s -e AIOPS_K8S_API=https://host.docker.internal:$PUERTO \
  -e AIOPS_K8S_TOKEN_FILE=k8s-lab/.secrets/token -e AIOPS_K8S_CA_FILE=k8s-lab/.secrets/ca.crt \
  -e AIOPS_AUTONOMY_LEVEL=3 -e AIOPS_ALLOWED_ENVS=dev \
  -e AIOPS_VERIFY_WINDOW_S=90 -e AIOPS_VERIFY_INTERVAL_S=3 \
  app uv run python -m scripts.lab_ciclo PodFailed api
```

Resultado verificado (2026-10-06): `pod_ready=0 -> recreate_pod -> 15s -> pod_ready=1
-> CERRADO resuelto_autonomo=True`.
