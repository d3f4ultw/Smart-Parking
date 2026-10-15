"""Cliente HTTP minimo para sincronizar Vision con la API canonica."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

from temporal_validation import OccupancyState, ZoneSnapshot

_FORMATO_TOKEN = re.compile(r"[A-Za-z0-9_-]{43,}\Z")
INTERVALO_HEARTBEAT_SEGUNDOS = 10
INTERVALO_OBSERVACION_SEGUNDOS = 20


class VisionAPIError(RuntimeError):
    """Error remoto sin cabeceras, cuerpos ni credenciales en su representacion."""

    def __init__(self, status_code: int | None) -> None:
        self.status_code = status_code
        super().__init__(
            "Vision API no disponible"
            if status_code is None
            else f"Vision API devolvio HTTP {status_code}"
        )


@dataclass(frozen=True, slots=True)
class ConfiguracionRemota:
    revision: int
    next_c_number: int
    zones: tuple[dict[str, Any], ...]


def ruta_estado_vision() -> Path:
    """Devuelve una ruta externa al codigo para caché y ajustes locales."""

    configurada = os.environ.get("VISION_STATE_PATH")
    if configurada:
        return Path(configurada).expanduser()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
        return base / "SmartParking" / "Vision"
    return Path.home() / ".local" / "state" / "smart-parking-vision"


def ruta_cache_zonas() -> Path:
    return ruta_estado_vision() / "zones.json"


class SmartParkingClient:
    """Carga calibracion, guarda snapshots y publica estados estabilizados."""

    def __init__(self, api_url: str, token: str | None = None, timeout: float = 5.0) -> None:
        bearer = token if token is not None else os.environ.get("VISION_BEARER_TOKEN", "")
        if not _FORMATO_TOKEN.fullmatch(bearer):
            raise ValueError("VISION_BEARER_TOKEN no esta configurado correctamente.")
        self.api_url = api_url.rstrip("/")
        self._token = bearer
        self.timeout = timeout
        self.configuracion: ConfiguracionRemota | None = None
        self.session_id: UUID | None = None
        self.sequence = 0
        self._pending_request_id: UUID | None = None
        self._pending_digest: str | None = None
        self._ultimo_estado_publicado: tuple[tuple[str, str], ...] | None = None
        self._ultima_observacion_monotona = 0.0

    def _request(self, method: str, path: str, body: object | None = None) -> dict[str, Any]:
        datos = None if body is None else json.dumps(body, separators=(",", ":")).encode()
        peticion = Request(
            f"{self.api_url}{path}",
            data=datos,
            method=method,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/json",
                **({"Content-Type": "application/json"} if datos is not None else {}),
            },
        )
        try:
            with urlopen(peticion, timeout=self.timeout) as respuesta:
                valor = json.loads(respuesta.read().decode("utf-8"))
        except HTTPError as error:
            raise VisionAPIError(error.code) from None
        except (URLError, TimeoutError, OSError, json.JSONDecodeError, UnicodeDecodeError):
            raise VisionAPIError(None) from None
        if not isinstance(valor, dict):
            raise VisionAPIError(None)
        return valor

    def cargar_configuracion(self) -> ConfiguracionRemota:
        valor = self._request("GET", "/api/vision/configuration")
        try:
            zonas = tuple(valor["zones"])
            configuracion = ConfiguracionRemota(
                revision=int(valor["revision"]),
                next_c_number=int(valor["next_c_number"]),
                zones=zonas,
            )
            for zona in zonas:
                UUID(zona["vision_zone_id"])
                if int(zona["numero"]) < 1 or not isinstance(zona["polygon"], list):
                    raise ValueError
        except (KeyError, TypeError, ValueError):
            raise VisionAPIError(None) from None
        self.configuracion = configuracion
        self._guardar_cache(configuracion)
        return configuracion

    def _guardar_cache(self, configuracion: ConfiguracionRemota) -> None:
        datos = {
            "version": 2,
            "coordinate_system": "normalized_0_to_1",
            "next_c_number": configuracion.next_c_number,
            "metadata": {"source_type": "api"},
            "zones": [
                {
                    "id": f"C{zona['numero']}",
                    "vision_zone_id": zona["vision_zone_id"],
                    "polygon": zona["polygon"],
                }
                for zona in configuracion.zones
            ],
        }
        destino = ruta_cache_zonas()
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporal: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=destino.parent,
                prefix=f".{destino.name}.",
                suffix=".tmp",
                delete=False,
            ) as archivo:
                temporal = Path(archivo.name)
                json.dump(datos, archivo, ensure_ascii=False, indent=2)
                archivo.write("\n")
            os.replace(temporal, destino)
        finally:
            if temporal is not None and temporal.exists():
                temporal.unlink()

    def guardar_configuracion(self, calibracion: object) -> ConfiguracionRemota:
        zonas = getattr(calibracion, "zonas")
        identidades = getattr(calibracion, "vision_zone_ids")
        if self.configuracion is None:
            self.cargar_configuracion()
        assert self.configuracion is not None
        canonicas = {zona["vision_zone_id"]: zona for zona in self.configuracion.zones}
        instantanea = [
            {
                "vision_zone_id": str(identidades[identificador]),
                "numero": canonicas[str(identidades[identificador])]["numero"]
                if str(identidades[identificador]) in canonicas
                else None,
                "polygon": [[round(x, 8), round(y, 8)] for x, y in zona.polygon],
            }
            for identificador, zona in zonas.items()
        ]
        cuerpo = {
            "expected_revision": self.configuracion.revision,
            "zones": instantanea,
        }
        representacion = json.dumps(cuerpo, sort_keys=True, separators=(",", ":"))
        if representacion != self._pending_digest:
            self._pending_request_id = uuid4()
            self._pending_digest = representacion
        cuerpo["request_id"] = str(self._pending_request_id)
        valor = self._request("PUT", "/api/vision/configuration", cuerpo)
        configuracion = self._parsear_configuracion(valor)
        self.configuracion = configuracion
        self._pending_request_id = None
        self._pending_digest = None
        self.session_id = None
        self._guardar_cache(configuracion)
        return configuracion

    @staticmethod
    def _parsear_configuracion(valor: dict[str, Any]) -> ConfiguracionRemota:
        try:
            zonas = tuple(valor["zones"])
            resultado = ConfiguracionRemota(
                revision=int(valor["revision"]),
                next_c_number=int(valor["next_c_number"]),
                zones=zonas,
            )
            for zona in zonas:
                UUID(zona["vision_zone_id"])
                if int(zona["numero"]) < 1 or not isinstance(zona["polygon"], list):
                    raise ValueError
        except (KeyError, TypeError, ValueError):
            raise VisionAPIError(None) from None
        return resultado

    def iniciar_sesion(self) -> None:
        valor = self._request("POST", "/api/vision/sessions")
        try:
            self.session_id = UUID(valor["session_id"])
            revision = int(valor["revision"])
        except (KeyError, TypeError, ValueError):
            raise VisionAPIError(None) from None
        if self.configuracion is None or revision != self.configuracion.revision:
            self.cargar_configuracion()
            self.iniciar_sesion()
            return
        self.sequence = 0
        self._ultimo_estado_publicado = None

    def _siguiente_secuencia(self) -> tuple[UUID, int]:
        if self.session_id is None:
            self.iniciar_sesion()
        assert self.session_id is not None
        self.sequence += 1
        return self.session_id, self.sequence

    def heartbeat(self) -> None:
        session_id, sequence = self._siguiente_secuencia()
        self._request(
            "POST",
            "/api/vision/heartbeat",
            {
                "request_id": str(uuid4()),
                "session_id": str(session_id),
                "sequence": sequence,
            },
        )

    def publicar_observaciones(self, snapshots: tuple[ZoneSnapshot, ...]) -> bool:
        if self.configuracion is None:
            self.cargar_configuracion()
        assert self.configuracion is not None
        estados = {snapshot.identifier: snapshot.state for snapshot in snapshots}
        identificadores = tuple(f"C{zona['numero']}" for zona in self.configuracion.zones)
        if not identificadores:
            return False
        if set(estados) != set(identificadores):
            return False
        if any(not snapshot.is_ready for snapshot in snapshots):
            return False
        if any(
            estados[identificador] not in {OccupancyState.LIBRE, OccupancyState.OCUPADO}
            for identificador in identificadores
        ):
            return False
        firma = tuple(
            (identificador, estados[identificador].value)
            for identificador in identificadores
        )
        ahora_monotono = time.monotonic()
        if (
            firma == self._ultimo_estado_publicado
            and ahora_monotono - self._ultima_observacion_monotona
            < INTERVALO_OBSERVACION_SEGUNDOS
        ):
            return False

        session_id, sequence = self._siguiente_secuencia()
        valor = self._request(
            "POST",
            "/api/vision/observations",
            {
                "request_id": str(uuid4()),
                "session_id": str(session_id),
                "revision": self.configuracion.revision,
                "sequence": sequence,
                "observations": [
                    {
                        "vision_zone_id": zona["vision_zone_id"],
                        "numero": zona["numero"],
                        "estado": estados[f"C{zona['numero']}"].value,
                    }
                    for zona in self.configuracion.zones
                ],
            },
        )
        if valor.get("accepted") is not True:
            raise VisionAPIError(None)
        self._ultimo_estado_publicado = firma
        self._ultima_observacion_monotona = ahora_monotono
        return True

    def servir(self, intervalo: float = INTERVALO_HEARTBEAT_SEGUNDOS) -> int:
        if not math_is_positive(intervalo):
            raise ValueError("El intervalo de heartbeat debe ser positivo.")
        while True:
            try:
                self.cargar_configuracion()
                self.iniciar_sesion()
                print("Vision conectado; la ocupacion sigue marcada como desactualizada sin observaciones.")
                while True:
                    self.heartbeat()
                    time.sleep(intervalo)
            except KeyboardInterrupt:
                return 0
            except VisionAPIError as error:
                if error.status_code == 409:
                    self.session_id = None
                    self._ultimo_estado_publicado = None
                print(f"{error}; reintento en {intervalo:g}s.", file=sys.stderr)
                time.sleep(intervalo)


def math_is_positive(valor: float) -> bool:
    return math.isfinite(valor) and valor > 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("serve",))
    parser.add_argument(
        "--api-url",
        default=os.environ.get("VISION_API_BASE_URL", "http://127.0.0.1:8000"),
    )
    parser.add_argument("--heartbeat-seconds", type=float, default=INTERVALO_HEARTBEAT_SEGUNDOS)
    args = parser.parse_args()
    try:
        client = SmartParkingClient(args.api_url)
        return client.servir(args.heartbeat_seconds)
    except (ValueError, VisionAPIError) as error:
        print(f"No se pudo iniciar Vision ({type(error).__name__}): {error}", file=sys.stderr)
        return 1


__all__ = [
    "ConfiguracionRemota",
    "SmartParkingClient",
    "VisionAPIError",
    "main",
    "ruta_cache_zonas",
    "ruta_estado_vision",
]


if __name__ == "__main__":
    raise SystemExit(main())
