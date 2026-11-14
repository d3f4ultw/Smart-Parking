import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


LANZADOR = Path(__file__).resolve().parents[1] / "vision-local-20261104"


class PreparacionAutoridadGraficaTest(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory(prefix=".vision-xauth-test-", dir=Path(__file__).parent)
        self.raiz = Path(self.temporal.name)
        self.lanzador = self.raiz / "infra/vision/vision-local-20261104"
        self.lanzador.parent.mkdir(parents=True)
        shutil.copy2(LANZADOR, self.lanzador)
        self.runtime = self.raiz / "runtime"
        self.runtime.mkdir(mode=0o700)
        self.control = self.runtime / "smartparking-vision"
        self.control.mkdir(mode=0o700)
        self.autoridad = self.control / "vision.Xauthority"
        self.autoridad.write_bytes(b"AUTORIDAD_ANTERIOR")
        self.autoridad.chmod(0o600)
        self.origen = self.raiz / "origen-xauth"
        self.origen.write_bytes(b"FUENTE_SINTETICA")
        self.origen.chmod(0o600)
        self.ordenes = self.raiz / "ordenes"
        self.binarios = self.raiz / "bin"
        self.binarios.mkdir()
        self._binario("podman", """#!/bin/sh
printf '%s\\n' "$*" > "$ORDENES"
exit 0
""")
        self._binario("xauth", """#!/usr/bin/env python3
import os, pathlib, sys, time
archivo = pathlib.Path(sys.argv[2])
control = pathlib.Path(__file__).resolve().parents[1]
if sys.argv[3] == 'nlist':
    if (control / 'XAUTH_DEMORA').exists(): time.sleep(7)
    if (control / 'XAUTH_FALLA').exists(): sys.exit(1)
    if not (control / 'XAUTH_VACIO').exists():
        clave = (control / 'CLAVE_SINTETICA').read_text() if (control / 'CLAVE_SINTETICA').exists() else '42424242'
        sys.stdout.write('0100 0000 ' + clave + '\\n')
elif sys.argv[3] == 'nmerge':
    archivo.write_bytes(sys.stdin.buffer.read())
else:
    sys.exit(1)
""")
        self._binario("xdpyinfo", """#!/usr/bin/env python3
import os, pathlib, sys
nombre = pathlib.Path(os.environ['XAUTHORITY']).name
control = pathlib.Path(__file__).resolve().parents[1]
if (control / 'FALLA_CANDIDATA').exists() and nombre.startswith('.vision-xauth-candidata-'):
    sys.exit(1)
if (control / 'CAMBIA_RUTA').exists() and nombre == 'vision.Xauthority':
    destino = pathlib.Path(os.environ['XAUTHORITY'])
    destino.rename(control / 'destino-original')
    destino.write_bytes(b'ARCHIVO_AJENO')
    destino.chmod(0o600)
    sys.exit(1)
if (control / 'FALLA_DESTINO').exists() and nombre == 'vision.Xauthority':
    if (control / 'FALLA_ROLLBACK').exists(): (control / 'ROLLBACK_ACTIVO').touch()
    sys.exit(1)
sys.exit(0)
""")
        self.entorno = os.environ.copy()
        self.entorno.update({
            "PATH": str(self.binarios) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
            "DISPLAY": ":8.0",
            "XAUTHORITY": str(self.origen),
            "XDG_RUNTIME_DIR": str(self.runtime),
            "ORDENES": str(self.ordenes),
        })

    def tearDown(self):
        self.temporal.cleanup()

    def _binario(self, nombre, contenido):
        ruta = self.binarios / nombre
        ruta.write_text(contenido, encoding="utf-8")
        ruta.chmod(0o700)

    def ejecutar(self, **cambios):
        for clave in ("XAUTH_FALLA", "XAUTH_VACIO", "XAUTH_DEMORA", "FALLA_CANDIDATA", "FALLA_DESTINO", "FALLA_ROLLBACK", "CAMBIA_RUTA", "CLAVE_SINTETICA"):
            ruta = self.raiz / clave
            if clave in cambios:
                ruta.write_text(cambios[clave], encoding="utf-8")
            else:
                ruta.unlink(missing_ok=True)
        entorno = self.entorno.copy()
        entorno.update(cambios)
        return subprocess.run([str(self.lanzador), "preparar-grafica"], env=entorno,
                              capture_output=True, text=True, timeout=15)

    def assert_sin_secretos(self, resultado):
        self.assertNotIn("42424242", resultado.stdout + resultado.stderr)
        self.assertNotIn("12345678", resultado.stdout + resultado.stderr)
        self.assertNotIn("FUENTE_SINTETICA", resultado.stdout + resultado.stderr)

    def assert_sin_temporales(self):
        self.assertEqual([], list(self.control.glob(".vision-xauth-*")))

    def test_renueva_autoridad_grafica_en_el_mismo_inode(self):
        inode = self.autoridad.stat().st_ino
        resultado = self.ejecutar()
        self.assertEqual(0, resultado.returncode, resultado.stderr)
        self.assertEqual(inode, self.autoridad.stat().st_ino)
        self.assertEqual(0o600, stat.S_IMODE(self.autoridad.stat().st_mode))
        self.assertTrue(self.autoridad.read_bytes().startswith(b"ffff"))
        self.assertFalse(self.ordenes.exists())
        self.assert_sin_secretos(resultado)
        self.assert_sin_temporales()

    def test_rotacion_se_aplica_al_siguiente_arranque_sin_cambiar_inode(self):
        inode = self.autoridad.stat().st_ino
        self.assertEqual(0, self.ejecutar().returncode)
        anterior = self.autoridad.read_bytes()
        resultado = self.ejecutar(CLAVE_SINTETICA="12345678")
        self.assertEqual(0, resultado.returncode, resultado.stderr)
        self.assertNotEqual(anterior, self.autoridad.read_bytes())
        self.assertEqual(inode, self.autoridad.stat().st_ino)
        self.assert_sin_secretos(resultado)
        self.assert_sin_temporales()

    def test_crea_autoridad_privada_si_no_existia(self):
        self.autoridad.unlink()
        resultado = self.ejecutar()
        self.assertEqual(0, resultado.returncode, resultado.stderr)
        self.assertEqual(0o600, stat.S_IMODE(self.autoridad.stat().st_mode))
        self.assert_sin_temporales()

    def test_sin_sesion_o_con_display_remoto_falla_sin_cambiar_destino(self):
        for cambios in ({"XAUTHORITY": ""}, {"DISPLAY": "servidor:0"}, {"XAUTH_VACIO": "1"},
                        {"XAUTH_FALLA": "1"}, {"FALLA_CANDIDATA": "1"}):
            with self.subTest(cambios=cambios):
                anterior = self.autoridad.read_bytes()
                inode = self.autoridad.stat().st_ino
                resultado = self.ejecutar(**cambios)
                self.assertNotEqual(0, resultado.returncode)
                self.assertEqual(anterior, self.autoridad.read_bytes())
                self.assertEqual(inode, self.autoridad.stat().st_ino)
                self.assertFalse(self.ordenes.exists())
                self.assert_sin_secretos(resultado)
                self.assert_sin_temporales()

    def test_error_posterior_a_escritura_restaura_contenido_e_inode(self):
        anterior = self.autoridad.read_bytes()
        inode = self.autoridad.stat().st_ino
        resultado = self.ejecutar(FALLA_DESTINO="1")
        self.assertNotEqual(0, resultado.returncode)
        self.assertEqual(anterior, self.autoridad.read_bytes())
        self.assertEqual(inode, self.autoridad.stat().st_ino)
        self.assertFalse(self.ordenes.exists())
        self.assert_sin_temporales()

    def test_rollback_fallido_conserva_respaldo_privado(self):
        self._binario("python3", """#!/usr/bin/python3
import os, pathlib, sys
if len(sys.argv) < 3 or sys.argv[1] != '-':
    os.execv('/usr/bin/python3', ['/usr/bin/python3', *sys.argv[1:]])
destino = os.path.realpath(sys.argv[2])
control = pathlib.Path(__file__).resolve().parents[1]
escritura_real = os.write
def escritura_con_fallo(descriptor, contenido):
    if (control / 'ROLLBACK_ACTIVO').exists():
        ruta = os.path.realpath('/proc/self/fd/' + str(descriptor))
        if ruta == destino: raise OSError('fallo sintetico de restauracion')
    return escritura_real(descriptor, contenido)
os.write = escritura_con_fallo
codigo = sys.stdin.read()
sys.argv = ['-', sys.argv[2]]
exec(compile(codigo, '<launcher>', 'exec'), {'__name__': '__main__'})
""")
        inode = self.autoridad.stat().st_ino
        resultado = self.ejecutar(FALLA_DESTINO="1", FALLA_ROLLBACK="1")
        self.assertNotEqual(0, resultado.returncode)
        respaldos = list(self.control.glob(".vision-xauth-respaldo-*"))
        self.assertEqual(1, len(respaldos))
        self.assertEqual(0o600, stat.S_IMODE(respaldos[0].stat().st_mode))
        self.assertEqual(b"AUTORIDAD_ANTERIOR", respaldos[0].read_bytes())
        self.assertEqual(inode, self.autoridad.stat().st_ino)
        self.assertIn("respaldo privado", resultado.stderr)
        self.assertFalse(self.ordenes.exists())
        self.assert_sin_secretos(resultado)

    def test_ruta_reemplazada_durante_rollback_conserva_respaldo(self):
        resultado = self.ejecutar(CAMBIA_RUTA="1")
        self.assertNotEqual(0, resultado.returncode)
        respaldos = list(self.control.glob(".vision-xauth-respaldo-*"))
        self.assertEqual(1, len(respaldos))
        self.assertEqual(0o600, stat.S_IMODE(respaldos[0].stat().st_mode))
        self.assertEqual(b"AUTORIDAD_ANTERIOR", respaldos[0].read_bytes())
        self.assertEqual(b"AUTORIDAD_ANTERIOR", (self.raiz / "destino-original").read_bytes())
        self.assertEqual(b"ARCHIVO_AJENO", self.autoridad.read_bytes())
        self.assertFalse(self.ordenes.exists())
        self.assertIn("respaldo privado", resultado.stderr)
        self.assert_sin_secretos(resultado)

    def test_agotamiento_de_xauth_falla_cerrado(self):
        anterior = self.autoridad.read_bytes()
        inode = self.autoridad.stat().st_ino
        resultado = self.ejecutar(XAUTH_DEMORA="1")
        self.assertNotEqual(0, resultado.returncode)
        self.assertEqual(anterior, self.autoridad.read_bytes())
        self.assertEqual(inode, self.autoridad.stat().st_ino)
        self.assertFalse(self.ordenes.exists())
        self.assert_sin_secretos(resultado)
        self.assert_sin_temporales()

    def test_preparar_grafica_no_invoca_podman(self):
        resultado = self.ejecutar()
        self.assertEqual(0, resultado.returncode, resultado.stderr)
        self.assertFalse(self.ordenes.exists())
        self.assert_sin_secretos(resultado)
        self.assert_sin_temporales()

    def test_rechaza_archivo_no_privado_y_enlace_simbolico(self):
        anterior = self.autoridad.read_bytes()
        self.autoridad.chmod(0o644)
        resultado = self.ejecutar()
        self.assertNotEqual(0, resultado.returncode)
        self.assertEqual(anterior, self.autoridad.read_bytes())
        self.autoridad.unlink()
        self.autoridad.symlink_to(self.origen)
        resultado = self.ejecutar()
        self.assertNotEqual(0, resultado.returncode)
        self.assertEqual(b"FUENTE_SINTETICA", self.origen.read_bytes())
        self.assertFalse(self.ordenes.exists())
        self.assert_sin_temporales()

    def test_rechaza_enlace_duro_sin_modificar_ninguna_copia(self):
        otro = self.raiz / "autoridad-enlazada"
        os.link(self.autoridad, otro)
        inode = self.autoridad.stat().st_ino
        resultado = self.ejecutar()
        self.assertNotEqual(0, resultado.returncode)
        self.assertEqual(b"AUTORIDAD_ANTERIOR", otro.read_bytes())
        self.assertEqual(inode, self.autoridad.stat().st_ino)
        self.assertFalse(self.ordenes.exists())
        self.assert_sin_temporales()


if __name__ == "__main__":
    unittest.main()
