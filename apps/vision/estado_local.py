"""Mantiene la ocupación actual y recuerda el último estado que pudo confirmarse."""

from __future__ import annotations

import time
from dataclasses import dataclass

from temporal_validation import OccupancyState, TemporalOccupancyValidator, ZoneSnapshot


@dataclass(frozen=True)
class EstadoZona:
    """Reúne la ocupación actual, la última confirmada y cuánto tiempo ha pasado desde ella."""

    snapshot: ZoneSnapshot
    efectivo: str
    ultimo: str | None
    antiguedad: float | None


class EstadoLocal:
    """Distingue lo que puede confirmarse ahora de la última ocupación conocida."""

    def __init__(self, zones, **reglas):
        self.zones = zones
        self.reglas = reglas
        self.validador = TemporalOccupancyValidator(zones, **reglas)
        self.ultimos: dict[str, tuple[str, float]] = {}
        self.verificable = False
        self.motivo = "sin observacion valida"

    def invalidar(self, motivo: str) -> None:
        """Indica que no puede confirmar la ocupación y guarda el motivo."""
        # Reinicia las observaciones incompletas para no mezclarlas con una conexión distinta.
        if self.verificable:
            self.validador = TemporalOccupancyValidator(self.zones, **self.reglas)
        self.verificable = False
        self.motivo = motivo

    def avanzar(self, detecciones, ancho: int, alto: int) -> tuple[EstadoZona, ...]:
        """Revisa lo encontrado en una imagen y recuerda las zonas que ya pueden confirmarse."""
        snapshots = self.validador.process_frame(detecciones, ancho, alto)
        self.verificable = True
        self.motivo = ""
        ahora = time.monotonic()
        for snapshot in snapshots:
            if snapshot.is_ready and snapshot.state in (OccupancyState.LIBRE, OccupancyState.OCUPADO):
                self.ultimos[snapshot.identifier] = (snapshot.state.value, ahora)
        return self.estados()

    def estados(self) -> tuple[EstadoZona, ...]:
        """Entrega el estado actual y el último confirmado de cada zona, con el tiempo transcurrido."""
        ahora = time.monotonic()
        estados = []
        for snapshot in self.validador.snapshots():
            actual = "NO_VERIFICABLE"
            if (self.verificable and snapshot.is_ready
                    and snapshot.state in (OccupancyState.LIBRE, OccupancyState.OCUPADO)):
                actual = snapshot.state.value
            conocido = self.ultimos.get(snapshot.identifier)
            estados.append(EstadoZona(snapshot, actual,
                                      conocido[0] if conocido else None,
                                      ahora - conocido[1] if conocido else None))
        return tuple(estados)
