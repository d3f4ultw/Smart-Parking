"""Pruebas del launcher con systemd y X11 sinteticos, sin tocar servicios reales."""

import os
import shutil
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path


class LauncherPermanenteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)
        destino = self.raiz / "infra/vision"
        destino.mkdir(parents=True)
        fuente = Path(__file__).resolve().parents[1] / "vision-escritorio"
        self.launcher = destino / "vision-escritorio"
        shutil.copyfile(fuente, self.launcher)
        self.launcher.chmod(0o755)
        self.bin = self.raiz / "bin"
        self.bin.mkdir()
        self.estado = self.raiz / "estado"
        self.registro = self.raiz / "registro"
        self.runtime = self.raiz / "runtime"
        (self.runtime / "smartparking-vision").mkdir(parents=True)
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.bind(str(self.runtime / "smartparking-vision/control.sock"))
        self.socket.listen(1)
        self.addCleanup(self.socket.close)
        self._script(destino / "vision-local-20261104", 'echo preparar >> "$PRUEBA_REGISTRO"\n[ "${PRUEBA_GRAFICA:-ok}" = ok ]')
        self._script(self.bin / "systemctl", '''if [ "$2" = show ]; then cat "$PRUEBA_ESTADO"; exit 0; fi
if [ "$2" = start ]; then echo iniciar >> "$PRUEBA_REGISTRO"; echo active > "$PRUEBA_ESTADO"; exit 0; fi
exit 1''')
        self._script(self.bin / "python3", 'echo mostrar >> "$PRUEBA_REGISTRO"\nexit "${PRUEBA_RESULTADO:-0}"')
        self._script(self.bin / "xmessage", 'exit 0')
        self._script(self.bin / "wmctrl", 'exit 0')
        self.entorno = dict(os.environ, PATH=str(self.bin) + ":/usr/bin:/bin", DISPLAY=":0",
                            XDG_RUNTIME_DIR=str(self.runtime), PRUEBA_REGISTRO=str(self.registro),
                            PRUEBA_ESTADO=str(self.estado))

    def _script(self, ruta, contenido):
        ruta.write_text("#!/bin/sh\n" + contenido + "\n", encoding="utf-8")
        ruta.chmod(0o755)

    def invocar(self):
        return subprocess.run([str(self.launcher)], env=self.entorno, capture_output=True, timeout=5)

    def test_arranca_una_vez_y_peticiones_siguientes_solo_adjuntan(self):
        self.estado.write_text("inactive\n")
        self.assertEqual(self.invocar().returncode, 0)
        self.assertEqual(self.invocar().returncode, 0)
        self.assertEqual(self.registro.read_text().splitlines(),
                         ["preparar", "iniciar", "mostrar", "preparar", "mostrar"])

    def test_sesion_invalida_no_inicia_ni_adjunta(self):
        self.estado.write_text("inactive\n")
        self.entorno["PRUEBA_GRAFICA"] = "no"
        self.assertNotEqual(self.invocar().returncode, 0)
        self.assertEqual(self.registro.read_text().splitlines(), ["preparar"])

    def test_fallo_de_control_no_inicia_otra_instancia(self):
        self.estado.write_text("active\n")
        self.entorno["PRUEBA_RESULTADO"] = "1"
        self.assertNotEqual(self.invocar().returncode, 0)
        self.assertEqual(self.registro.read_text().splitlines(), ["preparar", "mostrar"])


if __name__ == "__main__":
    unittest.main()
