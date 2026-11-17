# Docker: el proceso del contenedor muere (SIGKILL, codigo 137). Sin restart policy queda Exited.
set -e
docker kill ia-factory-lab-web >/dev/null
echo "ia-factory-lab-web detenido (kill)."
