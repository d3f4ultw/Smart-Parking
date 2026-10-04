"""Primitivas de presentacion para las CLI interactivas de Smart Parking."""

from __future__ import annotations

import os
import sys


def limpiar_pantalla() -> None:
    """Limpia la consola interactiva sin generar ruido en salidas capturadas."""

    if not sys.stdout.isatty():
        return
    comando = "cls" if os.name == "nt" else "clear"
    if os.system(comando) != 0:
        print("\033[2J\033[H", end="")


ANSI_REINICIO = "\033[0m"
ANSI_CIAN = "\033[36m"
ANSI_CIAN_BRILLANTE = "\033[96m"
ANSI_VERDE = "\033[32m"
ANSI_AMARILLO = "\033[33m"
ANSI_ROJO = "\033[31m"
ANSI_DIM = "\033[2m"


def _colores_habilitados() -> bool:
    """Indica si la salida permite colores y no solicito su desactivacion."""

    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


def _estilizar(texto: str, codigo: str | None) -> str:
    """Aplica un estilo ANSI solo cuando la salida es una terminal interactiva."""

    if codigo is None or not _colores_habilitados():
        return texto
    return f"{codigo}{texto}{ANSI_REINICIO}"
