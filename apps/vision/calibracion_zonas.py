"""Administra y guarda las zonas que marcan los cajones en la imagen."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import cv2
import numpy as np

from temporal_validation import ParkingZone, point_in_polygon

VERSION_CALIBRACION = 2
SISTEMA_COORDENADAS = "normalized_0_to_1"
TAMANO_MASCARA_SOLAPAMIENTO = 512
UMBRAL_SOLAPAMIENTO_EXCESIVO = 0.20
_PATRON_ID_ZONA = re.compile(r"C([1-9][0-9]*)\Z")
Punto = tuple[float, float]


def _numero_id_zona(identificador: str) -> int:
    if not isinstance(identificador, str):
        raise ValueError(f"Identificador de zona invalido: {identificador!r}.")
    coincidencia = _PATRON_ID_ZONA.fullmatch(identificador)
    if coincidencia is None:
        raise ValueError(f"Identificador de zona invalido: {identificador!r}.")
    return int(coincidencia.group(1))


def _validar_zonas_y_asignador(
    zonas: dict[str, ParkingZone], next_c_number: object
) -> None:
    if (
        not isinstance(next_c_number, int)
        or isinstance(next_c_number, bool)
        or next_c_number < 1
    ):
        raise ValueError("next_c_number debe ser un entero positivo.")

    mayor_id = 0
    for identificador, zona in zonas.items():
        numero = _numero_id_zona(identificador)
        if not isinstance(zona, ParkingZone) or zona.identifier != identificador:
            raise ValueError(f"La zona {identificador!r} no coincide con su identificador.")
        mayor_id = max(mayor_id, numero)

    if next_c_number <= mayor_id:
        raise ValueError("next_c_number debe ser mayor que los IDs activos.")


@dataclass
class CalibracionZonas:
    """Conserva las zonas terminadas y los puntos de la zona que se está dibujando."""

    ancho: int
    alto: int
    zonas: dict[str, ParkingZone] = field(default_factory=dict)
    puntos_pendientes: list[Punto] = field(default_factory=list)
    next_c_number: int = 1
    id_seleccionado: str | None = None
    cambios_pendientes: bool = False
    vision_zone_ids: dict[str, UUID] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.ancho < 2 or self.alto < 2:
            raise ValueError("La imagen debe medir al menos dos pixeles por lado.")
        _validar_zonas_y_asignador(self.zonas, self.next_c_number)
        if set(self.vision_zone_ids) - set(self.zonas):
            raise ValueError("Las identidades Vision deben pertenecer a zonas activas.")
        if not isinstance(self.metadata, dict):
            raise ValueError("Los metadatos de calibracion deben ser un objeto.")
        for identificador in self.zonas:
            self.vision_zone_ids.setdefault(identificador, uuid4())
        if self.id_seleccionado is not None and self.id_seleccionado not in self.zonas:
            raise ValueError("La zona seleccionada debe existir en la calibracion.")
        for x, y in self.puntos_pendientes:
            if not _coordenada_normalizada_valida(x, y):
                raise ValueError("Los puntos pendientes deben estar normalizados entre 0 y 1.")

    @property
    def esta_lista(self) -> bool:
        """Indica si no hay ninguna zona a medio dibujar."""

        return not self.puntos_pendientes

    @property
    def hay_borrador(self) -> bool:
        return bool(self.puntos_pendientes)

    @property
    def cantidad_completa(self) -> int:
        return len(self.zonas)

    def seleccionar_zona(self, identificador: str) -> None:
        if identificador not in self.zonas:
            raise ValueError(f"La zona {identificador!r} no existe.")
        self.id_seleccionado = identificador

    def iniciar_nueva_zona(self) -> tuple[bool, str]:
        if self.puntos_pendientes:
            return False, "Confirma o cancela el poligono en borrador antes de iniciar otro."
        self.id_seleccionado = None
        return True, "Dibuja el siguiente poligono y pulsa Enter para confirmarlo."

    def pixel_a_normalizado(self, x: int, y: int) -> Punto:
        """Expresa la posición de un punto como proporción del tamaño de la imagen."""

        if not 0 <= x < self.ancho or not 0 <= y < self.alto:
            raise ValueError("El punto debe quedar dentro de la imagen.")
        return (x / (self.ancho - 1), y / (self.alto - 1))

    def normalizado_a_pixel(self, punto: Punto) -> tuple[int, int]:
        x, y = punto
        if not _coordenada_normalizada_valida(x, y):
            raise ValueError("La coordenada normalizada debe estar entre 0 y 1.")
        return round(x * (self.ancho - 1)), round(y * (self.alto - 1))

    def agregar_punto(self, x: int, y: int) -> tuple[bool, str]:
        """Añade un punto de la zona y guarda su posición respecto al tamaño de la imagen."""
        try:
            punto = self.pixel_a_normalizado(x, y)
        except ValueError as error:
            return False, str(error)

        self.puntos_pendientes.append(punto)
        self.cambios_pendientes = True
        return True, f"Vertice {len(self.puntos_pendientes)} agregado; pulsa Enter para confirmar."

    def confirmar_poligono(self) -> tuple[bool, str]:
        """Comprueba la forma antes de darle un nombre y una identidad para reconocerla.

        Si la forma no es válida, conserva sus puntos para corregirlos. Los nombres de
        las zonas eliminadas no vuelven a usarse.
        """
        if len(self.puntos_pendientes) < 3:
            return False, "Un poligono requiere al menos tres vertices."

        identificador = f"C{self.next_c_number}"
        try:
            zona = ParkingZone(identificador, tuple(self.puntos_pendientes))
        except (TypeError, ValueError) as error:
            return False, f"Poligono invalido: {error} El borrador se conserva."

        self.zonas[identificador] = zona
        self.vision_zone_ids[identificador] = uuid4()
        self.next_c_number += 1
        self.puntos_pendientes.clear()
        self.id_seleccionado = identificador
        self.cambios_pendientes = True
        self.invalidar_evidencia_automatica()
        return True, f"Zona {identificador} creada."

    def deshacer_punto(self) -> tuple[bool, str]:
        if not self.puntos_pendientes:
            return False, "No hay vertices pendientes."
        self.puntos_pendientes.pop()
        self.cambios_pendientes = True
        return True, "Se retiro el ultimo vertice del borrador."

    def cancelar_poligono(self) -> str:
        self.puntos_pendientes.clear()
        self.id_seleccionado = None
        return "Borrador cancelado; el siguiente ID no cambio."

    def eliminar_zona(self, identificador: str | None = None) -> str:
        """Elimina la zona elegida y su identidad sin cambiar los nombres de las demás."""
        seleccionado = identificador or self.id_seleccionado
        if seleccionado is None or seleccionado not in self.zonas:
            return "Selecciona una zona existente para eliminarla."
        del self.zonas[seleccionado]
        self.vision_zone_ids.pop(seleccionado, None)
        if self.id_seleccionado == seleccionado:
            self.id_seleccionado = None
        self.cambios_pendientes = True
        self.invalidar_evidencia_automatica()
        return f"Zona {seleccionado} eliminada; los demas IDs se mantienen."

    def reiniciar_todas(self) -> None:
        """Elimina todas las zonas y puntos sin volver a usar los nombres anteriores."""
        self.zonas.clear()
        self.vision_zone_ids.clear()
        self.puntos_pendientes.clear()
        self.id_seleccionado = None
        self.cambios_pendientes = True
        self.invalidar_evidencia_automatica()
        # El siguiente nombre continúa desde el número guardado.

    def mover_vertice(
        self, identificador: str, indice: int, x: int, y: int
    ) -> tuple[bool, str]:
        """Mueve un punto solo si la nueva forma es válida.

        Después descarta los datos de detección automática de la forma anterior.
        """
        zona = self.zonas.get(identificador)
        if zona is None:
            return False, f"La zona {identificador} no existe."
        if not 0 <= indice < len(zona.polygon):
            return False, "El indice del vertice no es valido."
        try:
            punto = self.pixel_a_normalizado(x, y)
            vertices = list(zona.polygon)
            vertices[indice] = punto
            zona_actualizada = ParkingZone(identificador, tuple(vertices))
        except (TypeError, ValueError) as error:
            return False, f"No se movio el vertice: {error}"

        self.zonas[identificador] = zona_actualizada
        self.cambios_pendientes = True
        self.invalidar_evidencia_automatica()
        return True, f"Vertice actualizado en la zona {identificador}."

    def invalidar_evidencia_automatica(self) -> None:
        """Descarta los datos de detección automática de una forma que ya cambió."""

        self.metadata.pop("confianza_zonas", None)
        self.metadata.pop("limites_zonas", None)

    def zona_en_punto(self, x: int, y: int) -> str | None:
        """Busca la zona más pequeña que contiene el punto indicado."""

        try:
            punto = self.pixel_a_normalizado(x, y)
        except ValueError:
            return None
        coincidentes = [
            zona
            for zona in self.zonas.values()
            if point_in_polygon(punto, zona.polygon)
        ]
        if not coincidentes:
            return None
        return min(
            coincidentes,
            key=lambda zona: (zona.area, _numero_id_zona(zona.identifier)),
        ).identifier

    def vertice_cercano(
        self,
        x: int,
        y: int,
        radio_px: float,
        identificador: str | None = None,
    ) -> tuple[str, int] | None:
        candidatos: list[tuple[float, int, int, str]] = []
        for id_zona, zona in self.zonas.items():
            if identificador is not None and id_zona != identificador:
                continue
            for indice, punto in enumerate(zona.polygon):
                px, py = self.normalizado_a_pixel(punto)
                distancia = float(np.hypot(px - x, py - y))
                if distancia <= radio_px:
                    candidatos.append((distancia, _numero_id_zona(id_zona), indice, id_zona))
        if not candidatos:
            return None
        _, _, indice, id_zona = min(candidatos)
        return id_zona, indice


def _coordenada_normalizada_valida(x: object, y: object) -> bool:
    return (
        isinstance(x, (int, float))
        and not isinstance(x, bool)
        and isinstance(y, (int, float))
        and not isinstance(y, bool)
        and np.isfinite(x)
        and np.isfinite(y)
        and 0.0 <= x <= 1.0
        and 0.0 <= y <= 1.0
    )


def cargar_calibracion(ruta: str | Path, ancho: int, alto: int) -> CalibracionZonas:
    """Carga las zonas guardadas en un archivo; también admite una lista vacía."""

    from configuracion_local import verificar_sin_guardado_pendiente

    archivo = Path(ruta)
    verificar_sin_guardado_pendiente(archivo)
    try:
        datos = json.loads(archivo.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError(f"No se pudo leer la calibracion {archivo}: {error}") from error
    verificar_sin_guardado_pendiente(archivo)

    if not isinstance(datos, dict) or datos.get("version") != VERSION_CALIBRACION:
        raise ValueError(f"El archivo debe usar el esquema de calibracion {VERSION_CALIBRACION}.")
    if datos.get("coordinate_system") != SISTEMA_COORDENADAS:
        raise ValueError("El archivo no usa coordenadas normalizadas de 0 a 1.")
    if not isinstance(datos.get("zones"), list):
        raise ValueError("El archivo debe contener una lista 'zones'.")
    metadata = datos.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("Los metadatos de calibracion deben ser un objeto.")
    siguiente = datos.get("next_c_number")
    if (
        not isinstance(siguiente, int)
        or isinstance(siguiente, bool)
        or siguiente < 1
    ):
        raise ValueError("next_c_number debe ser un entero positivo.")

    zonas: dict[str, ParkingZone] = {}
    identidades: dict[str, UUID] = {}
    for elemento in datos["zones"]:
        if not isinstance(elemento, dict):
            raise ValueError("Cada zona debe ser un objeto con 'id' y 'polygon'.")
        identificador = elemento.get("id")
        try:
            _numero_id_zona(identificador)
        except (TypeError, ValueError) as error:
            raise ValueError(f"Id de zona no permitido: {identificador!r}.") from error
        if identificador in zonas:
            raise ValueError(f"El id {identificador} esta duplicado.")
        vision_zone_id = elemento.get("vision_zone_id")
        try:
            identidades[identificador] = (
                UUID(vision_zone_id) if vision_zone_id is not None else uuid4()
            )
        except (AttributeError, TypeError, ValueError) as error:
            raise ValueError(f"La identidad Vision de {identificador} no es valida.") from error
        poligono = elemento.get("polygon")
        if not isinstance(poligono, list):
            raise ValueError(f"La zona {identificador} debe contener un poligono.")
        if any(not isinstance(punto, list) or len(punto) != 2 for punto in poligono):
            raise ValueError(f"La zona {identificador} tiene puntos mal formados.")
        try:
            zonas[identificador] = ParkingZone(
                identificador,
                tuple((punto[0], punto[1]) for punto in poligono),
            )
        except (IndexError, TypeError, ValueError) as error:
            raise ValueError(f"La zona {identificador} no es valida: {error}") from error

    _validar_zonas_y_asignador(zonas, siguiente)
    return CalibracionZonas(
        ancho,
        alto,
        zonas=zonas,
        next_c_number=siguiente,
        vision_zone_ids=identidades,
        metadata=dict(metadata),
    )


def advertencias_solapamiento(
    zonas: dict[str, ParkingZone],
    umbral: float = UMBRAL_SOLAPAMIENTO_EXCESIVO,
) -> list[str]:
    """Advierte cuando dos zonas se cubren demasiado, sin impedir por sí sola el guardado."""

    mascaras: dict[str, np.ndarray] = {}
    areas: dict[str, int] = {}
    for identificador, zona in zonas.items():
        mascara = np.zeros(
            (TAMANO_MASCARA_SOLAPAMIENTO, TAMANO_MASCARA_SOLAPAMIENTO),
            dtype=np.uint8,
        )
        puntos = np.array(
            [
                (
                    round(x * (TAMANO_MASCARA_SOLAPAMIENTO - 1)),
                    round(y * (TAMANO_MASCARA_SOLAPAMIENTO - 1)),
                )
                for x, y in zona.polygon
            ],
            dtype=np.int32,
        )
        cv2.fillPoly(mascara, [puntos], 1)
        mascaras[identificador] = mascara
        areas[identificador] = int(cv2.countNonZero(mascara))

    advertencias: list[str] = []
    ids = sorted(mascaras, key=_numero_id_zona)
    for indice, primero in enumerate(ids):
        for segundo in ids[indice + 1 :]:
            area_menor = min(areas[primero], areas[segundo])
            if area_menor == 0:
                continue
            interseccion = cv2.bitwise_and(mascaras[primero], mascaras[segundo])
            proporcion = cv2.countNonZero(interseccion) / area_menor
            if proporcion > umbral:
                advertencias.append(
                    f"Zonas {primero} y {segundo} se superponen en "
                    f"{proporcion:.0%} de la menor."
                )
    return advertencias


def guardar_calibracion(
    ruta: str | Path,
    calibracion: CalibracionZonas,
    tipo_fuente: str,
    metadata_adicional: dict[str, object] | None = None,
    atributos_por_zona: dict[str, dict[str, object]] | None = None,
) -> list[str]:
    """Guarda las zonas terminadas y deja fuera los puntos aún sin confirmar.

    Prepara el archivo nuevo antes de reemplazar el anterior.
    """

    _validar_zonas_y_asignador(calibracion.zonas, calibracion.next_c_number)
    if tipo_fuente not in ("image", "http", "camera"):
        raise ValueError("El tipo de fuente debe ser image, http o camera.")

    atributos_por_zona = atributos_por_zona or {}
    if set(atributos_por_zona) - set(calibracion.zonas):
        raise ValueError("Los atributos adicionales deben pertenecer a zonas existentes.")
    zonas_datos = []
    for identificador, zona in calibracion.zonas.items():
        adicionales = atributos_por_zona.get(identificador, {})
        if not isinstance(adicionales, dict) or set(adicionales) & {"id", "vision_zone_id", "polygon"}:
            raise ValueError("Los atributos adicionales no pueden reemplazar la identidad o geometria.")
        zonas_datos.append({
            **adicionales,
            "id": identificador,
            "vision_zone_id": str(calibracion.vision_zone_ids[identificador]),
            "polygon": [[round(x, 8), round(y, 8)] for x, y in zona.polygon],
        })
    metadata = dict(calibracion.metadata)
    if metadata_adicional is not None:
        metadata.update(metadata_adicional)
    metadata.update({
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_type": tipo_fuente,
        "source_width": calibracion.ancho,
        "source_height": calibracion.alto,
    })
    for campo in ("calibration_sha256", "revision_calibracion", "geometry_fingerprint"):
        metadata.pop(campo, None)
    datos = {
        "version": VERSION_CALIBRACION,
        "coordinate_system": SISTEMA_COORDENADAS,
        "next_c_number": calibracion.next_c_number,
        "metadata": metadata,
        "zones": zonas_datos,
    }
    archivo = Path(ruta)
    archivo.parent.mkdir(parents=True, exist_ok=True)
    temporal: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=archivo.parent,
            prefix=f".{archivo.name}.",
            suffix=".tmp",
            delete=False,
        ) as salida:
            temporal = Path(salida.name)
            json.dump(datos, salida, ensure_ascii=False, indent=2)
            salida.write("\n")
            salida.flush()
            os.fsync(salida.fileno())
        os.chmod(temporal, 0o600)
        os.replace(temporal, archivo)
        descriptor_directorio = os.open(archivo.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor_directorio)
        finally:
            os.close(descriptor_directorio)
    finally:
        if temporal is not None and temporal.exists():
            temporal.unlink()

    calibracion.cambios_pendientes = bool(calibracion.puntos_pendientes)
    calibracion.metadata = dict(datos["metadata"])
    return advertencias_solapamiento(calibracion.zonas)
