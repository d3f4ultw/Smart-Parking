"""Compatibilidad historica para emitir acceso Web de gestion del dueño."""

from __future__ import annotations

import sys

from app.cli.propietario_web import main

if __name__ == "__main__":
    sys.exit(main())
