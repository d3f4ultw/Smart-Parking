"""Limitacion de solicitudes de activacion por ventana deslizante."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from threading import RLock

VENTANA_RATE_LIMIT_SEGUNDOS = 5 * 60
MAXIMO_INTENTOS_POR_ORIGEN = 30
MAXIMO_INTENTOS_POR_TOKEN = 5
MAXIMO_INTENTOS_POR_CORREO = 5


class LimitadorVentanaDeslizante:
    """Controla intentos aceptados de cada clave dentro de una ventana."""

    def __init__(
        self,
        limite: int,
        *,
        ventana_segundos: float = VENTANA_RATE_LIMIT_SEGUNDOS,
        reloj: Callable[[], float] | None = None,
    ) -> None:
        if limite <= 0:
            raise ValueError("El limite debe ser positivo.")
        if ventana_segundos <= 0:
            raise ValueError("La ventana debe ser positiva.")

        self.limite = limite
        self.ventana_segundos = ventana_segundos
        self._reloj = time.monotonic if reloj is None else reloj
        self._intentos: dict[str, deque[float]] = {}
        self._bloqueo = RLock()

    def permitir(self, clave: str, *, ahora: float | None = None) -> bool:
        """Registra un intento y devuelve si sigue dentro del limite."""

        instante = self._obtener_tiempo(ahora)
        limite_inferior = instante - self.ventana_segundos
        with self._bloqueo:
            self._limpiar_expiradas(limite_inferior)
            intentos = self._intentos.setdefault(clave, deque())
            if len(intentos) >= self.limite:
                return False

            intentos.append(instante)
            return True

    def limpiar(self, *, ahora: float | None = None) -> None:
        """Elimina las claves que ya no tienen intentos vigentes."""

        instante = self._obtener_tiempo(ahora)
        with self._bloqueo:
            self._limpiar_expiradas(instante - self.ventana_segundos)

    def reiniciar(self) -> None:
        """Vacía el estado del limiter, principalmente para pruebas aisladas."""

        with self._bloqueo:
            self._intentos.clear()

    def cantidad_claves(self) -> int:
        """Devuelve cuantas claves conservan intentos en memoria."""

        with self._bloqueo:
            return len(self._intentos)

    def _obtener_tiempo(self, ahora: float | None) -> float:
        return self._reloj() if ahora is None else ahora

    def _limpiar_expiradas(self, limite_inferior: float) -> None:
        for clave, intentos in tuple(self._intentos.items()):
            while intentos and intentos[0] <= limite_inferior:
                intentos.popleft()
            if not intentos:
                del self._intentos[clave]


class LimitadorActivaciones:
    """Aplica limites independientes por origen y huella SHA-256 del token.

    El estado es local a cada proceso de la API y se reinicia al reiniciar esa
    instancia. No se introduce almacenamiento compartido para este sprint.
    """

    def __init__(
        self,
        *,
        ventana_segundos: float = VENTANA_RATE_LIMIT_SEGUNDOS,
        limite_origen: int = MAXIMO_INTENTOS_POR_ORIGEN,
        limite_token: int = MAXIMO_INTENTOS_POR_TOKEN,
        reloj: Callable[[], float] | None = None,
    ) -> None:
        self._por_origen = LimitadorVentanaDeslizante(
            limite_origen,
            ventana_segundos=ventana_segundos,
            reloj=reloj,
        )
        self._por_token = LimitadorVentanaDeslizante(
            limite_token,
            ventana_segundos=ventana_segundos,
            reloj=reloj,
        )

    def permitir(
        self,
        origen: str,
        huella_token: str,
        *,
        ahora: float | None = None,
    ) -> bool:
        """Registra un intento usando solo el origen y la huella del token."""

        origen_permitido = self._por_origen.permitir(origen, ahora=ahora)
        if not origen_permitido:
            return False

        return self._por_token.permitir(huella_token, ahora=ahora)

    def reiniciar(self) -> None:
        """Vacía ambos limites para aislar una instancia o una prueba."""

        self._por_origen.reiniciar()
        self._por_token.reiniciar()


class LimitadorAutenticacion:
    """Aplica limites independientes por origen y huella de correo."""

    def __init__(
        self,
        *,
        ventana_segundos: float = VENTANA_RATE_LIMIT_SEGUNDOS,
        limite_origen: int = MAXIMO_INTENTOS_POR_ORIGEN,
        limite_correo: int = MAXIMO_INTENTOS_POR_CORREO,
        reloj: Callable[[], float] | None = None,
    ) -> None:
        self._por_origen = LimitadorVentanaDeslizante(
            limite_origen,
            ventana_segundos=ventana_segundos,
            reloj=reloj,
        )
        self._por_correo = LimitadorVentanaDeslizante(
            limite_correo,
            ventana_segundos=ventana_segundos,
            reloj=reloj,
        )

    def permitir(
        self,
        origen: str,
        huella_correo: str,
        *,
        ahora: float | None = None,
    ) -> bool:
        """Registra un intento usando solo el origen y la huella del correo."""

        origen_permitido = self._por_origen.permitir(origen, ahora=ahora)
        if not origen_permitido:
            return False

        return self._por_correo.permitir(huella_correo, ahora=ahora)

    def reiniciar(self) -> None:
        """Vacía ambos limites para aislar una instancia o una prueba."""

        self._por_origen.reiniciar()
        self._por_correo.reiniciar()


limitador_activaciones = LimitadorActivaciones()
limitador_autenticacion = LimitadorAutenticacion()


__all__ = [
    "MAXIMO_INTENTOS_POR_ORIGEN",
    "MAXIMO_INTENTOS_POR_CORREO",
    "MAXIMO_INTENTOS_POR_TOKEN",
    "LimitadorAutenticacion",
    "VENTANA_RATE_LIMIT_SEGUNDOS",
    "LimitadorActivaciones",
    "LimitadorVentanaDeslizante",
    "limitador_activaciones",
    "limitador_autenticacion",
]
