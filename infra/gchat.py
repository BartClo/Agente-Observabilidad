"""Cliente del webhook entrante de Google Chat (espacio de notificaciones del agente).

Decisiones de seguridad:
- La URL del webhook lleva `key` y `token`: es un SECRETO. Solo se acepta
  `https://chat.googleapis.com` (una URL cambiada no puede mandar los mensajes del agente
  a otro host) y la URL nunca aparece en excepciones ni en logs.
- El texto que llega aca puede traer contenido de alertas, logs o del LLM (no confiable):
  `limpiar()` neutraliza lo que en Google Chat dispara menciones (`<users/all>`) o
  formato inyectado.

Un hilo por incidente (`threadKey`): los avisos del mismo incidente quedan juntos.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request

_HOSTS = {"chat.googleapis.com"}
_ESQUEMAS = {"https"}
_MAX_TEXTO = 4000  # el limite de Google Chat es 4096 bytes por mensaje


class ErrorGChat(RuntimeError):
    """Entrega fallida. Nunca incluye la URL del webhook."""


def validar_url(url: str) -> str:
    partes = urllib.parse.urlsplit(url.strip())
    if partes.scheme not in _ESQUEMAS or partes.hostname not in _HOSTS:
        raise ErrorGChat(
            "URL de webhook de Google Chat invalida (solo https://chat.googleapis.com)"
        )
    return partes.geturl()


def limpiar(texto: str, maximo: int = 1200) -> str:
    """Texto no confiable -> seguro para incrustar en un mensaje."""
    texto = texto.replace("<", "‹").replace(">", "›").replace("`", "'")
    texto = re.sub(r"\s*\n\s*", " ", texto).strip()
    return texto if len(texto) <= maximo else texto[: maximo - 1] + "…"


def clave_de_hilo(incidente_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9:_-]", "_", incidente_id)[:100]


def enviar(url: str, texto: str, hilo: str | None = None, timeout_s: float = 5.0) -> None:
    """Publica `texto`. Lanza ErrorGChat si no se pudo entregar (el llamador reintenta)."""
    url = validar_url(url)
    cuerpo: dict[str, object] = {"text": texto[:_MAX_TEXTO]}
    if hilo:
        cuerpo["thread"] = {"threadKey": clave_de_hilo(hilo)}
        sep = "&" if "?" in url else "?"
        url += f"{sep}messageReplyOption=REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"
    req = urllib.request.Request(  # noqa: S310  (host validado arriba)
        url,
        data=json.dumps(cuerpo).encode(),
        method="POST",
        headers={"Content-Type": "application/json; charset=UTF-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s):  # noqa: S310
            return
    except urllib.error.HTTPError as exc:  # 429 (cuota) y 5xx son reintentables
        raise ErrorGChat(f"Google Chat respondio {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        motivo = getattr(exc, "reason", exc)
        raise ErrorGChat(f"sin conexion con Google Chat ({type(motivo).__name__})") from None
