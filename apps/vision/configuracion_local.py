"""Relaciona las zonas guardadas con el origen y el tamaño de la imagen."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path


def identidad_fuente(tipo: str, valor: str | Path) -> str:
    """Reconoce el origen de la imagen sin guardar rutas ni direcciones privadas."""
    if tipo == "image":
        ruta = Path(valor).resolve()
        identidad = f"imagen:{ruta}:{hashlib.sha256(ruta.read_bytes()).hexdigest()}"
    elif tipo == "simulation":
        identidad = f"simulacion:{Path(valor).resolve()}"
    else:
        identidad = f"{tipo}:{valor}"
    return hashlib.sha256(identidad.encode()).hexdigest()


def ruta_vinculo(ruta_zonas: Path) -> Path:
    return ruta_zonas.with_name(ruta_zonas.name + ".fuente.json")


def ruta_guardado_pendiente(ruta_zonas: Path) -> Path:
    return ruta_zonas.with_name(f".{ruta_zonas.name}.guardado-pendiente")


def verificar_sin_guardado_pendiente(ruta_zonas: Path) -> None:
    """Rechaza un par que pudo quedar a mitad de una escritura interrumpida."""
    marcador = ruta_guardado_pendiente(ruta_zonas)
    try:
        marcador.lstat()
    except FileNotFoundError:
        return
    except OSError as error:
        raise ValueError("No se pudo comprobar si existe un guardado pendiente.") from error
    raise ValueError(
        f"Existe un guardado pendiente para {ruta_zonas}; conserve el respaldo y revise el par."
    )


def _sincronizar_directorio(carpeta: Path) -> None:
    descriptor = os.open(carpeta, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class _GuardadoPendiente:
    """Mantiene abierto el marcador que identifica al escritor que lo creó."""

    def __init__(self, ruta: Path, descriptor: int) -> None:
        self.ruta = ruta
        self.descriptor = descriptor

    def cerrar(self) -> None:
        if self.descriptor is not None:
            os.close(self.descriptor)
            self.descriptor = None


def _comprobar_guardado_propio(ruta_zonas: Path, guardado: _GuardadoPendiente) -> None:
    if (not isinstance(guardado, _GuardadoPendiente)
            or guardado.ruta != ruta_guardado_pendiente(ruta_zonas)
            or guardado.descriptor is None):
        raise ValueError("El escritor no posee el marcador de guardado.")
    try:
        abierto = os.fstat(guardado.descriptor)
        presente = guardado.ruta.lstat()
    except OSError as error:
        raise ValueError("No se pudo comprobar el marcador propio.") from error
    if (abierto.st_dev, abierto.st_ino) != (presente.st_dev, presente.st_ino):
        raise ValueError("El marcador de guardado ya no pertenece a este escritor.")


def _escribir_estado_guardado(
    ruta_zonas: Path, guardado: _GuardadoPendiente, fase: str, respaldo: Path | None,
) -> None:
    _comprobar_guardado_propio(ruta_zonas, guardado)
    datos = (json.dumps({"version": 1, "fase": fase,
                         "respaldo": respaldo.name if respaldo else None}) + "\n").encode()
    os.lseek(guardado.descriptor, 0, os.SEEK_SET)
    os.ftruncate(guardado.descriptor, 0)
    while datos:
        escritos = os.write(guardado.descriptor, datos)
        if escritos <= 0:
            raise OSError("No se pudo escribir el marcador de guardado.")
        datos = datos[escritos:]
    os.fsync(guardado.descriptor)
    _sincronizar_directorio(ruta_zonas.parent)
    _comprobar_guardado_propio(ruta_zonas, guardado)


def iniciar_guardado_pendiente(ruta_zonas: Path) -> _GuardadoPendiente:
    """Adquiere y sincroniza la exclusión antes de leer o respaldar el par."""
    ruta_zonas.parent.mkdir(parents=True, exist_ok=True)
    marcador = ruta_guardado_pendiente(ruta_zonas)
    try:
        descriptor = os.open(marcador, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise ValueError("Ya existe un guardado pendiente de recuperacion.") from error
    guardado = _GuardadoPendiente(marcador, descriptor)
    try:
        _escribir_estado_guardado(ruta_zonas, guardado, "preparacion", None)
    except BaseException:
        try:
            finalizar_guardado_pendiente(ruta_zonas, guardado)
        except BaseException as recuperacion:
            raise RuntimeError("No se pudo cancelar el marcador de guardado pendiente.") from recuperacion
        finally:
            guardado.cerrar()
        raise
    return guardado


def finalizar_guardado_pendiente(ruta_zonas: Path, guardado: _GuardadoPendiente) -> None:
    """Retira únicamente el marcador propio tras confirmar o restaurar el par."""
    try:
        _comprobar_guardado_propio(ruta_zonas, guardado)
        guardado.ruta.unlink()
        _sincronizar_directorio(ruta_zonas.parent)
    finally:
        guardado.cerrar()


def guardar_vinculo(ruta_zonas: Path, tipo: str, fuente: str | Path,
                    ancho: int, alto: int) -> None:
    identidad = identidad_fuente(tipo, fuente)
    metadata = _leer_metadata_canonica(ruta_zonas)
    if metadata is not None:
        _validar_metadata_fuente(metadata, tipo, identidad, ancho, alto)
    datos = {
        "version": 1,
        "fuente_sha256": identidad,
        "ancho": ancho,
        "alto": alto,
    }
    archivo = ruta_vinculo(ruta_zonas)
    temporal: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=archivo.parent,
            prefix=f".{archivo.name}.", delete=False,
        ) as salida:
            temporal = Path(salida.name)
            json.dump(datos, salida, indent=2)
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


def verificar_vinculo(ruta_zonas: Path, tipo: str, fuente: str | Path,
                      ancho: int, alto: int) -> None:
    """Comprueba que las zonas correspondan al mismo origen y tamaño de imagen."""
    verificar_sin_guardado_pendiente(ruta_zonas)
    try:
        datos = json.loads(ruta_vinculo(ruta_zonas).read_text(encoding="utf-8"))
        compatible = _sidecar_compatible(ruta_zonas, datos, tipo, fuente, ancho, alto)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        compatible = False
    if compatible:
        verificar_sin_guardado_pendiente(ruta_zonas)
        return
    verificar_sin_guardado_pendiente(ruta_zonas)
    try:
        _recuperar_sidecar_canonico(ruta_zonas, tipo, fuente, ancho, alto)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        raise ValueError("La calibracion no tiene un vinculo de fuente valido; recalibre.") from error
    verificar_sin_guardado_pendiente(ruta_zonas)


def _sidecar_compatible(ruta_zonas: Path, datos: dict, tipo: str, fuente: str | Path,
                        ancho: int, alto: int) -> bool:
    if not isinstance(datos, dict) or datos.get("version") not in (1, 2):
        return False
    identidad = identidad_fuente(tipo, fuente)
    if (datos.get("fuente_sha256") != identidad
            or not _dimensiones_exactas(datos, ancho, alto)):
        return False
    metadata = _leer_metadata_canonica(ruta_zonas)
    if metadata is not None:
        try:
            _validar_metadata_fuente(metadata, tipo, identidad, ancho, alto)
        except (ValueError, TypeError, KeyError):
            return False
    return True


def _dimensiones_exactas(datos: dict, ancho: int, alto: int) -> bool:
    return (
        isinstance(datos.get("ancho"), int)
        and not isinstance(datos.get("ancho"), bool)
        and isinstance(datos.get("alto"), int)
        and not isinstance(datos.get("alto"), bool)
        and datos["ancho"] == ancho
        and datos["alto"] == alto
    )


def _recuperar_sidecar_canonico(ruta_zonas: Path, tipo: str, fuente: str | Path,
                                 ancho: int, alto: int) -> None:
    guardado = iniciar_guardado_pendiente(ruta_zonas)
    escritura_iniciada = False
    try:
        try:
            datos = json.loads(ruta_vinculo(ruta_zonas).read_text(encoding="utf-8"))
            compatible = _sidecar_compatible(ruta_zonas, datos, tipo, fuente, ancho, alto)
        except (OSError, ValueError, TypeError, KeyError):
            compatible = False
        if compatible:
            finalizar_guardado_pendiente(ruta_zonas, guardado)
            return
        metadata = _leer_metadata_canonica(ruta_zonas)
        if metadata is None:
            raise ValueError("El archivo no incluye identidad de fuente recuperable.")
        identidad = identidad_fuente(tipo, fuente)
        _validar_metadata_fuente(metadata, tipo, identidad, ancho, alto)
        _escribir_estado_guardado(ruta_zonas, guardado, "recuperacion_sidecar", None)
        escritura_iniciada = True
        guardar_vinculo(ruta_zonas, tipo, fuente, ancho, alto)
        finalizar_guardado_pendiente(ruta_zonas, guardado)
    except BaseException:
        if not escritura_iniciada and guardado.descriptor is not None:
            finalizar_guardado_pendiente(ruta_zonas, guardado)
        raise
    finally:
        guardado.cerrar()


def _leer_metadata_canonica(ruta_zonas: Path) -> dict | None:
    datos = json.loads(ruta_zonas.read_text(encoding="utf-8"))
    metadata = datos.get("metadata") if isinstance(datos, dict) else None
    if not isinstance(metadata, dict) or not metadata.get("fuente_sha256"):
        return None
    return metadata


def _validar_metadata_fuente(metadata: dict, tipo: str, identidad: str,
                              ancho: int, alto: int) -> None:
    if (metadata.get("source_type") != tipo
            or metadata.get("fuente_sha256") != identidad
            or metadata.get("source_width") != ancho
            or metadata.get("source_height") != alto):
        raise ValueError("La identidad o las dimensiones de la fuente no coinciden.")


def respaldar_calibracion(
    ruta_zonas: Path,
    *,
    tipo: str | None = None,
    fuente: str | Path | None = None,
    ancho: int | None = None,
    alto: int | None = None,
) -> Path | None:
    """Respalda el par solo después de comprobar su identidad y dimensiones."""
    return _respaldar_calibracion(
        ruta_zonas, tipo=tipo, fuente=fuente, ancho=ancho, alto=alto,
        comprobar=lambda: verificar_sin_guardado_pendiente(ruta_zonas),
    )


def _respaldar_calibracion_bajo_guardado(
    ruta_zonas: Path, guardado: _GuardadoPendiente, *,
    tipo: str | None = None, fuente: str | Path | None = None,
    ancho: int | None = None, alto: int | None = None,
) -> Path | None:
    return _respaldar_calibracion(
        ruta_zonas, tipo=tipo, fuente=fuente, ancho=ancho, alto=alto,
        comprobar=lambda: _comprobar_guardado_propio(ruta_zonas, guardado),
    )


def _respaldar_calibracion(
    ruta_zonas: Path, *, tipo: str | None, fuente: str | Path | None,
    ancho: int | None, alto: int | None, comprobar,
) -> Path | None:
    import datetime

    comprobar()
    vinculo = ruta_vinculo(ruta_zonas)
    if not ruta_zonas.exists() and not vinculo.exists():
        return None
    if not ruta_zonas.is_file() or not vinculo.is_file():
        raise ValueError("La calibracion anterior esta incompleta; no se reemplazara.")
    zonas_anteriores = ruta_zonas.read_bytes()
    fuente_anterior = vinculo.read_bytes()
    comprobar()
    try:
        datos = json.loads(fuente_anterior)
        zonas = json.loads(zonas_anteriores)
        identidad = datos.get("fuente_sha256") if isinstance(datos, dict) else None
        correcto = (
            isinstance(datos, dict)
            and type(datos.get("version")) is int
            and datos.get("version") in (1, 2)
            and isinstance(identidad, str)
            and len(identidad) == 64
            and all(caracter in "0123456789abcdef" for caracter in identidad)
            and _dimensiones_exactas(datos, datos.get("ancho"), datos.get("alto"))
            and datos["ancho"] > 0
            and datos["alto"] > 0
            and isinstance(zonas, dict)
        )
        if correcto:
            metadata = zonas.get("metadata", {})
            if not isinstance(metadata, dict):
                raise ValueError("Los metadatos anteriores son invalidos.")
            if (("source_width" in metadata
                 and (type(metadata["source_width"]) is not int
                      or metadata["source_width"] != datos["ancho"]))
                    or ("source_height" in metadata
                        and (type(metadata["source_height"]) is not int
                             or metadata["source_height"] != datos["alto"]))):
                raise ValueError("Las dimensiones anteriores no coinciden.")
            tiene_fuente = all(valor is not None for valor in (tipo, fuente, ancho, alto))
            if not tiene_fuente and any(valor is not None for valor in (tipo, fuente, ancho, alto)):
                raise ValueError("La fuente de respaldo esta incompleta.")
            if tiene_fuente:
                if (tipo not in ("image", "http", "camera")
                        or type(ancho) is not int or ancho <= 0
                        or type(alto) is not int or alto <= 0
                        or not _dimensiones_exactas(datos, ancho, alto)
                        or identidad_fuente(tipo, fuente) != identidad
                        or ("source_type" in metadata and metadata["source_type"] != tipo)):
                    raise ValueError("La fuente anterior no coincide con su vinculo.")
            if "fuente_sha256" in metadata:
                if metadata["fuente_sha256"] != identidad:
                    raise ValueError("La identidad canonica anterior no coincide.")
                if (metadata.get("source_type") not in ("image", "http", "camera")
                        or metadata.get("source_width") != datos["ancho"]
                        or metadata.get("source_height") != datos["alto"]):
                    raise ValueError("Los metadatos canonicos anteriores son invalidos.")
            elif not tiene_fuente:
                raise ValueError("No se puede verificar la fuente de la calibracion anterior.")
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("El vinculo anterior es invalido; no se reemplazara.") from error
    if not correcto:
        raise ValueError("La calibracion anterior y su vinculo no coinciden; no se reemplazara.")

    carpeta = ruta_zonas.parent / "respaldos"
    carpeta.mkdir(mode=0o700, parents=True, exist_ok=True)
    _sincronizar_directorio(ruta_zonas.parent)
    fecha = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destino = Path(tempfile.mkdtemp(prefix=f"calibracion-{fecha}-", dir=carpeta))
    os.chmod(destino, 0o700)
    creados = []
    try:
        for nombre, contenido in ((ruta_zonas.name, zonas_anteriores),
                                  (vinculo.name, fuente_anterior)):
            archivo = destino / nombre
            descriptor = os.open(archivo, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            creados.append(archivo)
            with os.fdopen(descriptor, "wb") as salida:
                salida.write(contenido)
                salida.flush()
                os.fsync(salida.fileno())
        _sincronizar_directorio(destino)
        _sincronizar_directorio(carpeta)
        comprobar()
    except BaseException:
        for archivo in creados:
            archivo.unlink(missing_ok=True)
        destino.rmdir()
        raise
    return destino


def preparar_guardado_calibracion(
    ruta_zonas: Path, *, tipo: str | None = None, fuente: str | Path | None = None,
    ancho: int | None = None, alto: int | None = None, exigir_respaldo: bool = False,
) -> tuple[_GuardadoPendiente, Path | None]:
    """Excluye otros escritores antes de validar y respaldar el estado vigente."""
    guardado = iniciar_guardado_pendiente(ruta_zonas)
    entregado = False
    try:
        respaldo = _respaldar_calibracion_bajo_guardado(
            ruta_zonas, guardado, tipo=tipo, fuente=fuente, ancho=ancho, alto=alto,
        )
        if exigir_respaldo and respaldo is None:
            raise ValueError("No fue posible respaldar la calibracion anterior.")
        _escribir_estado_guardado(ruta_zonas, guardado, "respaldo_listo", respaldo)
        entregado = True
        return guardado, respaldo
    except BaseException:
        try:
            finalizar_guardado_pendiente(ruta_zonas, guardado)
        except BaseException as recuperacion:
            raise RuntimeError("No se pudo cancelar el marcador de guardado pendiente.") from recuperacion
        raise
    finally:
        if not entregado:
            guardado.cerrar()
