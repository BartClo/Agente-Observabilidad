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
from domain.aiops_core.modelos import AccionEjecutada, Estado, Incidente, Severidad
from domain.aiops_core.observabilidad import ObservabilidadPort
from domain.aiops_core.politicas import Politica, Veredicto


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
    ) -> None:
        self._obs = observabilidad
        self._backend = backend
        self.politica = politica
        self.auditoria = auditoria
        self._reloj = reloj
        self._incidentes: dict[str, Incidente] = {}

    # --- consulta -----------------------------------------------------------------

    def incidentes(self) -> list[Incidente]:
        return list(self._incidentes.values())

    def incidente(self, incidente_id: str) -> Incidente:
        try:
            return self._incidentes[incidente_id]
        except KeyError:
            raise ErrorCiclo(f"Incidente {incidente_id!r} no existe") from None

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
        base_id = f"INC-{alerta_id}"
        existente = self._incidentes.get(base_id)
        if existente is not None and existente.estado not in self._ESTADOS_TERMINALES:
            return existente
        alerta = next((a for a in self._obs.alertas_activas() if a.id == alerta_id), None)
        if alerta is None:
            raise ErrorCiclo(f"Alerta {alerta_id!r} no esta activa")
        incidente_id = base_id
        if existente is not None:
            n = 2
            while f"{base_id}-{n}" in self._incidentes:
                n += 1
            incidente_id = f"{base_id}-{n}"
        inc = Incidente(id=incidente_id, alerta=alerta, abierto_en=self._reloj())
        self._incidentes[incidente_id] = inc
        self.auditoria.registrar(incidente_id, "abierto", alerta=alerta.nombre)
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
        valor = self._obs.metrica(inc.alerta.servicio, senal.metrica)
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
        valor = self._obs.metrica(inc.alerta.servicio, senal.metrica)
        if valor is None:
            detalle = f"sin datos de {senal.metrica}: recuperacion no comprobable"
            inc.verificado = False
        else:
            inc.verificado = senal.cumple(valor)
            detalle = f"{senal.metrica}={valor:g}; exigido {senal.describir()} -> " + (
                "recuperado" if inc.verificado else "NO recuperado"
            )
        self.auditoria.registrar(incidente_id, "verificacion", ok=inc.verificado, detalle=detalle)
        return inc.verificado, detalle

    def cerrar(self, incidente_id: str) -> Incidente:
        inc = self.incidente(incidente_id)
        if not inc.verificado:
            raise ErrorCiclo(
                "No se puede cerrar como resuelto sin recuperacion verificada: verificar o escalar"
            )
        inc.estado = Estado.RESUELTO
        inc.cerrado_en = self._reloj()
        self.auditoria.registrar(
            incidente_id, "cerrado", autonomo=inc.resuelto_autonomo, acciones=len(inc.acciones)
        )
        return inc

    def descartar(self, incidente_id: str) -> Incidente:
        inc = self.incidente(incidente_id)
        if inc.anomalia_confirmada:
            raise ErrorCiclo("La anomalia esta confirmada: no es un falso positivo")
        inc.estado = Estado.DESCARTADO
        self.auditoria.registrar(incidente_id, "descartado")
        return inc

    def escalar(self, incidente_id: str, motivo: str) -> str:
        """Siempre permitido (ni siquiera el kill switch lo bloquea). Devuelve el paquete
        de traspaso para L2/SRE con evidencia y acciones realizadas."""
        inc = self.incidente(incidente_id)
        inc.estado = Estado.ESCALADO
        inc.intervencion_humana = True
        inc.motivo_escalamiento = motivo
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
        self.auditoria.registrar(inc.id, "accion", accion=accion, ok=ok, resultado=resultado)
        estado = "ejecutada" if ok else "FALLO"
        return ResultadoEjecucion(
            decision.veredicto, f"Accion {accion} {estado}: {resultado}. Falta verificar.", ok
        )
