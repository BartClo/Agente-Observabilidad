#!/usr/bin/env sh
export MSYS_NO_PATHCONV=1  # Git Bash convierte /paths a rutas de Windows; no aplica en Linux/Mac
# Escenario cola_detenida: no hay consumidores de la cola. rabbitmq_queue_consumers = 0
# -> QueueStalled. Como el laboratorio no tiene consumidor, la regla ya queda activa
# con el stack levantado; este script solo confirma el estado.
set -e
docker compose exec -T rabbitmq rabbitmqctl list_queues name consumers
echo "cola sin consumidores. Revisar QueueStalled en Grafana."
