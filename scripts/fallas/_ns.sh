#!/usr/bin/env sh
# Namespace de las fallas. Solo se inyecta en un namespace declarado de pruebas: un script de
# fallas apuntado por error a produccion es lo peor que puede hacer este repo.
NS="${EXP_NAMESPACE:-aiops-lab}"
case ",${EXP_NAMESPACES_PERMITIDOS:-aiops-lab}," in
  *",$NS,"*) ;;
  *) echo "namespace '$NS' no declarado en EXP_NAMESPACES_PERMITIDOS: no se inyecta" >&2; exit 3 ;;
esac
