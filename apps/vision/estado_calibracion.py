"""Elige entre las zonas habituales y una copia local guardada por el usuario."""
from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path


MARCADOR = ".vision-local-activa"
CONTENIDO = b"local-v1\n"


def seleccion_activa(productiva: Path, local: Path) -> tuple[Path, bool]:
    """Usa las zonas habituales salvo que exista una selección local válida.

    Si no puede comprobar la selección, indica que no es segura.
    """
    marcador = local.parent / MARCADOR
    try:
        estado = marcador.lstat()
    except FileNotFoundError:
        return productiva, True
    except OSError:
        return productiva, False
    if (not stat.S_ISREG(estado.st_mode) or estado.st_uid != os.getuid()
            or stat.S_IMODE(estado.st_mode) != 0o600 or estado.st_nlink != 1):
        return productiva, False
    try:
        if marcador.read_bytes() != CONTENIDO:
            return productiva, False
    except OSError:
        return productiva, False
    return local, True


def activar_local(local: Path) -> None:
    """Recuerda la elección de la copia local sin reemplazar los archivos habituales."""
    carpeta = local.parent
    if not carpeta.is_dir() or carpeta.is_symlink() or local.is_symlink():
        raise ValueError("El directorio LOCAL no es seguro.")
    descriptor, nombre = tempfile.mkstemp(prefix=".vision-local-", dir=carpeta)
    temporal = Path(nombre)
    try:
        with os.fdopen(descriptor, "wb") as archivo:
            archivo.write(CONTENIDO)
            archivo.flush()
            os.fsync(archivo.fileno())
        os.chmod(temporal, 0o600)
        os.replace(temporal, carpeta / MARCADOR)
        directorio = os.open(carpeta, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directorio)
        finally:
            os.close(directorio)
    finally:
        temporal.unlink(missing_ok=True)


def activaciones_pendientes(carpeta: Path) -> bool:
    """Indica si quedaron cambios de activación pendientes de revisar antes de enviar datos."""
    return any(carpeta.glob(".vision-activacion-*"))
