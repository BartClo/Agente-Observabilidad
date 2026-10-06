"""Ciclo de vida de un incidente L1: abrir -> confirmar -> clasificar -> diagnosticar ->
ejecutar -> verificar -> cerrar o escalar.

Es el "estado del incidente" que el agente mantiene. Las invariantes de seguridad se
imponen aca y no en el prompt: la politica se evalua en cada ejecucion y un incidente
solo se cierra como resuelto si la recuperacion fue verificada.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from domain.aiops_core.acciones import AccionNoPermitida, BackendAcciones, ejecutar_accion
from domain.aiops_core.auditoria import Auditoria
from domain.aiops_core.catalogo import CATALOGO, CategoriaL1, categoria_para_alerta
from domain.aiops_core.modelos import (
    AccionEjecutada,
    Alerta,
    Aprobacion,
    Estado,
    Incidente,
    Severidad,
)
from domain.aiops_core.observabilidad import ObservabilidadPort
from domain.aiops_core.politicas import Politica, Veredicto
from domain.aiops_core.repositorio import RepositorioIncidentes, RepositorioIncidentesMemoria


class ErrorCiclo(ValueError):
    """Operacion invalida para el estado actual del incidente."""


@dataclass(frozen=True)
class ResultadoEjecucion:
    veredicto: Veredicto
    mensaje: str
    ejecutada: bool


class Ciclo:
    def __init__(
        self,
        observabilidad: ObservabilidadPort,
        backend: BackendAcciones,
        politica: Politica,
        auditoria: Auditoria,
        reloj: Callable[[], float] = time.time,
        repositorio: RepositorioIncidentes | None = None,
        verificacion_ventana_s: float = 0.0,
        verificacion_intervalo_s: float = 5.0,
        dormir: Callable[[float], None] = time.sleep,
        confirmacion_ventana_s: float = 0.0,
    ) -> None:
        self._obs = observabilidad
        self._backend = backend
        self.politica = politica
        self.auditoria = auditoria
        self._reloj = reloj
        # Verificacion con espera (Fase 4): una accion real (recrear un pod) no recupera
        # al instante. Ventana 0 = una sola lectura, igual que antes.
        self._ventana = verificacion_ventana_s
        self._intervalo = verificacion_intervalo_s
        self._dormir = dormir
        # Fase 6: confirmar reintenta ante "sin datos" hasta esta ventana (0 = una lectura).
        self._ventana_confirmacion = confirmacion_ventana_s
        # Default: en memoria, se pierde al reiniciar (igual que antes de la Fase 1).
        # infra.incidentes_postgres.RepositorioIncidentesPostgres sobrevive reinicios.
        self._repo = repositorio if repositorio is not None else RepositorioIncidentesMemoria()

    # --- consulta -----------------------------------------------------------------

    def incidentes(self) -> list[Incidente]:
        return self._repo.listar()

    def incidente(self, incidente_id: str) -> Incidente:
        inc = self._repo.obtener(incidente_id)
        if inc is None:
            raise ErrorCiclo(f"Incidente {incidente_id!r} no existe")
        return inc

    def _guardar(self, inc: Incidente) -> Incidente:
        """Persiste el incidente tras cada mutacion. Con el repositorio en memoria es
        redundante (el dataclass ya es mutable in-place), pero con Postgres es lo unico
        que hace el cambio visible entre reinicios/procesos (ver docs/plan-aiops.md Fase 1)."""
        self._repo.guardar(inc)
        return inc

    def _categoria(self, inc: Incidente) -> CategoriaL1:
        if inc.categoria_id is None:
            raise ErrorCiclo("Primero clasificar el incidente")
        return CATALOGO[inc.categoria_id]

    def alertas_activas(self) -> list[str]:
        return [
            f"{a.id} | {a.nombre} | servicio={a.servicio} entorno={a.entorno} "
            f"severidad={a.severidad} | {a.resumen}"
            for a in self._obs.alertas_activas()
        ]

    def logs(self, incidente_id: str, lineas: int) -> list[str]:
        inc = self.incidente(incidente_id)
        salida = self._obs.logs(inc.alerta.servicio, max(1, min(lineas, 200)))
        self.auditoria.registrar(incidente_id, "consulta_logs", lineas=len(salida))
        return salida

    # --- ciclo --------------------------------------------------------------------

    _ESTADOS_TERMINALES = (Estado.RESUELTO, Estado.ESCALADO, Estado.DESCARTADO)

    def abrir(self, alerta_id: str) -> Incidente:
        """Abre el incidente de una alerta activa, o recupera el que ya esta en curso
        para esa alerta. Si el ultimo incidente de esta alerta ya quedo en un estado
        terminal (resuelto/escalado/descartado), un disparo recurrente crea uno nuevo
        en vez de reabrir el viejo: evita que se lea como ya resuelto algo que volvio
        a fallar (ver docs/plan-aiops.md Fase 0.5)."""
        existente = self._repo.obtener(f"INC-{alerta_id}")
        if existente is not None and existente.estado not in self._ESTADOS_TERMINALES:
            return existente
        alerta = next((a for a in self._obs.alertas_activas() if a.id == alerta_id), None)
        if alerta is None:
            raise ErrorCiclo(f"Alerta {alerta_id!r} no esta activa")
        return self._abrir_o_reusar(alerta, origen="pull")

    def abrir_desde_alerta(self, alerta: Alerta) -> Incidente:
        """Como `abrir`, pero para una alerta que llega por push (webhook de Grafana,
        Fase 2) en vez de por pull (`alertas_activas()`): la alerta ya viene completa,
        no hay que buscarla. Mismo invariante: no reabre un incidente terminal."""
        existente = self._repo.obtener(f"INC-{alerta.id}")
        if existente is not None and existente.estado not in self._ESTADOS_TERMINALES:
            return existente
        return self._abrir_o_reusar(alerta, origen="webhook")

    def notificar_resuelta_en_origen(self, alerta: Alerta) -> None:
        """El webhook de Grafana manda `status: resolved` para esta alerta. Se audita
        como evidencia, pero no cierra nada: solo el agente cierra, y solo tras
        `verificar`. Sin incidente abierto para esta alerta, no hace nada."""
        inc = self._repo.obtener(f"INC-{alerta.id}")
        if inc is not None and inc.estado not in self._ESTADOS_TERMINALES:
            self.auditoria.registrar(inc.id, "alerta_resuelta_en_origen")

    def _abrir_o_reusar(self, alerta: Alerta, *, origen: str) -> Incidente:
        base_id = f"INC-{alerta.id}"
        incidente_id = base_id
        if self._repo.obtener(base_id) is not None:
            n = 2
            while self._repo.obtener(f"{base_id}-{n}") is not None:
                n += 1
            incidente_id = f"{base_id}-{n}"
        inc = Incidente(id=incidente_id, alerta=alerta, abierto_en=self._reloj())
        self._guardar(inc)
        self.auditoria.registrar(incidente_id, "abierto", alerta=alerta.nombre, origen=origen)
        return inc

    def confirmar_anomalia(self, incidente_id: str) -> tuple[bool, str]:
        """Contrasta la alerta con la senal sana de su categoria. Sin dato = sin evidencia."""
        inc = self.incidente(incidente_id)
        categoria = categoria_para_alerta(inc.alerta.nombre)
        if categoria is None:
            detalle = f"alerta {inc.alerta.nombre!r} fuera del catalogo L1: sin criterio, escalar"
            self.auditoria.registrar(
                incidente_id, "confirmacion", confirmada=False, detalle=detalle
            )
            return False, detalle
        senal = categoria.senal_sana
        # Reintenta solo mientras NO hay datos (p. ej. Prometheus sin scrapes recientes):
        # una lectura sana ya es evidencia y no se espera a que aparezca la falla.
        limite = self._reloj() + self._ventana_confirmacion
        while (valor := self._obs.metrica(inc.alerta.servicio, senal.metrica)) is None:
            if self._reloj() >= limite:
                break
            self._dormir(self._intervalo)
        if valor is None:
            detalle = f"sin datos de {senal.metrica}: evidencia insuficiente, escalar"
            confirmada = False
        else:
            confirmada = not senal.cumple(valor)
            detalle = f"{senal.metrica}={valor:g}; sano si {senal.describir()} -> " + (
                "anomalia confirmada" if confirmada else "comportamiento normal"
            )
        inc.anomalia_confirmada = confirmada
        if confirmada:
            inc.estado = Estado.CONFIRMADO
        self._guardar(inc)
        self.auditoria.registrar(
            incidente_id, "confirmacion", confirmada=confirmada, detalle=detalle
        )
        return confirmada, detalle

    def clasificar(self, incidente_id: str) -> tuple[CategoriaL1 | None, bool, list[str]]:
        inc = self.incidente(incidente_id)
        if not inc.anomalia_confirmada:
            raise ErrorCiclo("Primero confirmar la anomalia con evidencia")
        categoria = categoria_para_alerta(inc.alerta.nombre)
        motivos: list[str] = []
        if categoria is None:
            motivos.append("categoria fuera del catalogo L1")
        else:
            inc.categoria_id = categoria.id
            if not categoria.remediable:
                motivos.append("categoria de solo deteccion: sin accion autorizada")
        if inc.alerta.severidad is Severidad.CRITICA:
            motivos.append("severidad critica")
        inc.elegible = not motivos
        inc.estado = Estado.CLASIFICADO
        self._guardar(inc)
        self.auditoria.registrar(
            incidente_id,
            "clasificacion",
            categoria=inc.categoria_id,
            elegible=inc.elegible,
            motivos=motivos,
        )
        return categoria, inc.elegible, motivos

    def registrar_diagnostico(
        self, incidente_id: str, causa: str, confianza: float, runbook_id: str
    ) -> None:
        inc = self.incidente(incidente_id)
        categoria = self._categoria(inc)
        if not 0.0 <= confianza <= 1.0:
            raise ErrorCiclo("confianza debe estar entre 0 y 1")
        if runbook_id != categoria.runbook_id:
            raise ErrorCiclo(
                f"Runbook {runbook_id!r} incompatible con {categoria.id} "
                f"(corresponde {categoria.runbook_id})"
            )
        inc.causa, inc.confianza, inc.runbook_id = causa, confianza, runbook_id
        inc.estado = Estado.DIAGNOSTICADO
        self._guardar(inc)
        self.auditoria.registrar(
            incidente_id, "diagnostico", causa=causa, confianza=confianza, runbook=runbook_id
        )

    def ejecutar_remediacion(self, incidente_id: str, *, aprobada: bool) -> ResultadoEjecucion:
        inc = self.incidente(incidente_id)
        categoria = self._categoria(inc)
        if inc.estado in (Estado.RESUELTO, Estado.ESCALADO, Estado.DESCARTADO):
            raise ErrorCiclo(f"Incidente en estado {inc.estado}: no admite acciones")
        if categoria.accion is None:
            return self._decidir_sin_ejecutar(inc, "sin accion autorizada para esta categoria")
        return self._ejecutar(inc, categoria.accion, es_rollback=False, aprobada=aprobada)

    def aprobar(self, incidente_id: str, usuario: str) -> None:
        """Registra en el dominio que `usuario` aprobo la remediacion pendiente.
        `ejecutar_remediacion(aprobada=True)` exige que esto se haya llamado antes:
        no alcanza con que el framework haya pausado el grafo (ver Aprobacion)."""
        inc = self.incidente(incidente_id)
        inc.aprobacion = Aprobacion(usuario, self._reloj(), "aprobado")
        self._guardar(inc)
        self.auditoria.registrar(incidente_id, "aprobacion", usuario=usuario, veredicto="aprobado")

    def rechazar(self, incidente_id: str, usuario: str, motivo: str) -> str:
        """Registra el rechazo y escala de inmediato: un rechazo siempre termina en
        intervencion humana, nunca reintenta la accion por su cuenta."""
        inc = self.incidente(incidente_id)
        inc.aprobacion = Aprobacion(usuario, self._reloj(), "rechazado")
        self._guardar(inc)
        self.auditoria.registrar(
            incidente_id, "aprobacion", usuario=usuario, veredicto="rechazado", motivo=motivo
        )
        return self.escalar(incidente_id, f"aprobacion rechazada por {usuario}: {motivo}")

    def registrar_costo_llm(self, incidente_id: str, *, entrada: int, salida: int) -> None:
        """Suma (no reemplaza) los tokens que gasto el LLM en este incidente: un job
        reintentado vuelve a gastar y tiene que contar."""
        if entrada < 0 or salida < 0:
            raise ErrorCiclo("los tokens no pueden ser negativos")
        inc = self.incidente(incidente_id)
        inc.tokens_entrada += entrada
        inc.tokens_salida += salida
        self._guardar(inc)
        self.auditoria.registrar(incidente_id, "costo_llm", entrada=entrada, salida=salida)

    def revertir(self, incidente_id: str) -> ResultadoEjecucion:
        inc = self.incidente(incidente_id)
        categoria = self._categoria(inc)
        if categoria.rollback is None:
            return self._decidir_sin_ejecutar(inc, "no existe rollback seguro: escalar")
        if not any(a.ok and not a.es_rollback for a in inc.acciones):
            raise ErrorCiclo("No hay accion previa que revertir")
        return self._ejecutar(inc, categoria.rollback, es_rollback=True, aprobada=False)

    def verificar(self, incidente_id: str) -> tuple[bool, str]:
        inc = self.incidente(incidente_id)
        categoria = self._categoria(inc)
        if not inc.acciones:
            raise ErrorCiclo("No se ejecuto ninguna accion: nada que verificar")
        senal = categoria.senal_sana
        limite = self._reloj() + self._ventana
        lecturas = 0
        while True:
            valor = self._obs.metrica(inc.alerta.servicio, senal.metrica)
            lecturas += 1
            if (valor is not None and senal.cumple(valor)) or self._reloj() >= limite:
                break
            self._dormir(self._intervalo)
        if valor is None:
            detalle = f"sin datos de {senal.metrica}: recuperacion no comprobable"
            inc.verificado = False
        else:
            inc.verificado = senal.cumple(valor)
            detalle = f"{senal.metrica}={valor:g}; exigido {senal.describir()} -> " + (
                "recuperado" if inc.verificado else "NO recuperado"
            )
        self._guardar(inc)
        self.auditoria.registrar(
            incidente_id, "verificacion", ok=inc.verificado, detalle=detalle, lecturas=lecturas
        )
        return inc.verificado, detalle

    def cerrar(self, incidente_id: str) -> Incidente:
        inc = self.incidente(incidente_id)
        if not inc.verificado:
            raise ErrorCiclo(
                "No se puede cerrar como resuelto sin recuperacion verificada: verificar o escalar"
            )
        inc.estado = Estado.RESUELTO
        inc.cerrado_en = self._reloj()
        self._guardar(inc)
        self.auditoria.registrar(
            incidente_id, "cerrado", autonomo=inc.resuelto_autonomo, acciones=len(inc.acciones)
        )
        return inc

    def descartar(self, incidente_id: str) -> Incidente:
        inc = self.incidente(incidente_id)
        if inc.anomalia_confirmada:
            raise ErrorCiclo("La anomalia esta confirmada: no es un falso positivo")
        inc.estado = Estado.DESCARTADO
        self._guardar(inc)
        self.auditoria.registrar(incidente_id, "descartado")
        return inc

    def escalar(self, incidente_id: str, motivo: str) -> str:
        """Siempre permitido (ni siquiera el kill switch lo bloquea). Devuelve el paquete
        de traspaso para L2/SRE con evidencia y acciones realizadas."""
        inc = self.incidente(incidente_id)
        inc.estado = Estado.ESCALADO
        inc.intervencion_humana = True
        inc.motivo_escalamiento = motivo
        self._guardar(inc)
        self.auditoria.registrar(incidente_id, "escalado", motivo=motivo)
        eventos = "\n".join(
            f"  - {e.tipo}: {e.datos}" for e in self.auditoria.de_incidente(incidente_id)
        )
        acciones = "\n".join(
            f"  - {a.nombre} ({'ok' if a.ok else 'fallo'}): {a.resultado}" for a in inc.acciones
        )
        a = inc.alerta
        return (
            f"ESCALADO {inc.id} a L2/SRE\n"
            f"Motivo: {motivo}\n"
            f"Servicio: {a.servicio} ({a.entorno}) | alerta: {a.nombre}\n"
            f"Categoria: {inc.categoria_id} | causa: {inc.causa} | confianza: {inc.confianza}\n"
            f"Acciones realizadas:\n{acciones or '  (ninguna)'}\n"
            f"Evidencia/eventos:\n{eventos}"
        )

    # --- internos -----------------------------------------------------------------

    def _decidir_sin_ejecutar(self, inc: Incidente, razon: str) -> ResultadoEjecucion:
        self.auditoria.registrar(inc.id, "decision_politica", veredicto="denegar", razones=[razon])
        return ResultadoEjecucion(Veredicto.DENEGAR, f"DENEGADO: {razon}. Escalar.", False)

    def _ejecutar(
        self, inc: Incidente, accion: str, *, es_rollback: bool, aprobada: bool
    ) -> ResultadoEjecucion:
        if aprobada and not (inc.aprobacion is not None and inc.aprobacion.veredicto == "aprobado"):
            raise ErrorCiclo(
                "aprobada=True sin una aprobacion registrada en el dominio: "
                "llamar Ciclo.aprobar(incidente_id, usuario) antes de ejecutar"
            )
        decision = self.politica.evaluar(
            inc, self._categoria(inc), accion, es_rollback=es_rollback, aprobada=aprobada
        )
        self.auditoria.registrar(
            inc.id,
            "decision_politica",
            accion=accion,
            veredicto=decision.veredicto,
            razones=list(decision.razones),
        )
        razones = "; ".join(decision.razones)
        if decision.veredicto is Veredicto.DENEGAR:
            return ResultadoEjecucion(decision.veredicto, f"DENEGADO: {razones}. Escalar.", False)
        if decision.veredicto is Veredicto.APROBACION:
            return ResultadoEjecucion(
                decision.veredicto,
                f"REQUIERE APROBACION HUMANA: {razones}. Usar la tool con aprobacion.",
                False,
            )
        try:
            resultado = ejecutar_accion(self._backend, accion, inc.alerta.servicio)
            ok = True
        except (AccionNoPermitida, RuntimeError, OSError, TimeoutError) as exc:
            resultado, ok = f"{type(exc).__name__}: {exc}", False
        inc.acciones.append(
            AccionEjecutada(accion, inc.alerta.servicio, resultado, ok, es_rollback)
        )
        if aprobada:
            inc.intervencion_humana = True  # una aprobacion humana no cuenta como autonoma
        inc.verificado = False  # cualquier accion invalida una verificacion previa
        inc.estado = Estado.ACCION_EJECUTADA
        self._guardar(inc)
        self.auditoria.registrar(inc.id, "accion", accion=accion, ok=ok, resultado=resultado)
        estado = "ejecutada" if ok else "FALLO"
        return ResultadoEjecucion(
            decision.veredicto, f"Accion {accion} {estado}: {resultado}. Falta verificar.", ok
        )
