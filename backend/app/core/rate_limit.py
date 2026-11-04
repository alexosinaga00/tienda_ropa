"""Limiter compartido de slowapi. Vive acá (no en main.py) para que los
routers puedan importarlo y decorar sus propios endpoints sin depender de
app.main (evita import circular)."""

import math
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable

from fastapi import Request
from slowapi import Limiter

from app.core.config import get_settings


def _direccion_cliente(request: Request) -> str:
    """En producción (Railway) la app corre detrás de un proxy: sin esto,
    request.client.host es la IP del proxy, no la del cliente real, y todos
    los clientes comparten el mismo balde de rate limit. `X-Forwarded-For`
    trae la IP real como primer valor -- pero solo se confía en ese header
    fuera de 'local', donde no hay proxy y cualquiera podría falsificarlo
    para evadir el límite (B-9 de la auditoría)."""
    if get_settings().environment != "local":
        adelantada = request.headers.get("x-forwarded-for")
        if adelantada:
            return adelantada.split(",")[0].strip()
    if not request.client or not request.client.host:
        return "127.0.0.1"
    return request.client.host


# Nombre público de la misma función, para quien la reutiliza fuera de este
# módulo (la auditoría guarda la IP real del cliente).
direccion_cliente = _direccion_cliente

limiter = Limiter(key_func=_direccion_cliente)


class LimitadorIntentos:
    """Bloqueo por cuenta de los intentos fallidos de inicio de sesion, en
    memoria y seguro entre hilos. Complementa al `limiter` (que cuenta por IP).

    Guarda, por clave, los instantes de los fallos recientes. Con
    `max_intentos` fallos dentro de la ventana la clave queda bloqueada hasta
    que el mas viejo salga de ella; un acierto la limpia. La clave NO depende
    de que la cuenta exista, asi que bloquear no revela nada.

    Limitacion conocida: vale con un solo worker (Railway corre uno) y se
    reinicia con cada despliegue; con varios habria que moverlo a la base o a
    Redis. La memoria esta acotada: se descartan las claves vencidas en cada
    operacion y, pasadas `max_claves`, las mas antiguas."""

    def __init__(
        self,
        max_claves: int = 10_000,
        reloj=time.monotonic,
        limites: Callable[[], tuple[int, int]] | None = None,
    ) -> None:
        """`limites` devuelve (máximo, ventana en segundos); por defecto los del inicio de sesión. Otra instancia
        con sus propios límites sirve para contar otra cosa por cuenta (p. ej. solicitudes de recuperación)."""
        self._fallos: OrderedDict[str, deque[float]] = OrderedDict()
        self._max_claves = max_claves
        self._reloj = reloj
        self._cerrojo = threading.Lock()
        self._limites = limites or self._limites_de_login

    @staticmethod
    def _limites_de_login() -> tuple[int, int]:
        ajustes = get_settings()
        return ajustes.login_max_intentos, ajustes.login_ventana_segundos

    def _purgar(self, ahora: float, ventana: int) -> None:
        # Las claves van ordenadas por su ultimo fallo (registrar_fallo las
        # mueve al final): si la del frente ya vencio, vencio todo su deque.
        while self._fallos:
            clave = next(iter(self._fallos))
            instantes = self._fallos[clave]
            while instantes and ahora - instantes[0] >= ventana:
                instantes.popleft()
            if instantes:
                break
            del self._fallos[clave]

    def bloqueado(self, clave: str) -> int | None:
        """Segundos que faltan para poder reintentar, o `None` si no esta
        bloqueada."""
        maximo, ventana = self._limites()
        with self._cerrojo:
            ahora = self._reloj()
            self._purgar(ahora, ventana)
            instantes = self._fallos.get(clave)
            if instantes is None:
                return None
            # Una clave con fallos viejos mezclados: solo cuentan los de la ventana.
            vigentes = [t for t in instantes if ahora - t < ventana]
            if len(vigentes) < maximo:
                return None
            return max(1, math.ceil(vigentes[0] + ventana - ahora))

    def registrar_fallo(self, clave: str) -> None:
        maximo, ventana = self._limites()
        with self._cerrojo:
            ahora = self._reloj()
            self._purgar(ahora, ventana)
            instantes = self._fallos.setdefault(clave, deque())
            instantes.append(ahora)
            while len(instantes) > maximo:  # mas alla del maximo no aporta nada
                instantes.popleft()
            self._fallos.move_to_end(clave)
            while len(self._fallos) > self._max_claves:
                self._fallos.popitem(last=False)

    def limpiar(self, clave: str) -> None:
        with self._cerrojo:
            self._fallos.pop(clave, None)

    def reiniciar(self) -> None:
        with self._cerrojo:
            self._fallos.clear()


limitador_intentos = LimitadorIntentos()


def _limites_de_recuperacion() -> tuple[int, int]:
    ajustes = get_settings()
    return ajustes.recuperar_max_solicitudes, ajustes.recuperar_ventana_segundos


# Solicitudes de recuperación de contraseña por cuenta (empresa + correo). Cuenta TODAS las solicitudes (no son
# "fallos"), existan o no la empresa y el correo: así el límite no revela nada.
limitador_recuperacion = LimitadorIntentos(limites=_limites_de_recuperacion)
