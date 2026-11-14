"""Prueba recuperación de mantenimiento incierto sin acceder al ESP32."""

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import inspeccion_firmware as inspeccion


class ReplSimulado:
    def __init__(self, modo):
        self.modo = modo
        self.serie = self
        self.bandera = None
        self.consultas_prompt = 0
        self.reinicio = False
        self.cerrado = False
        self.desfasado = False

    def write(self, datos):
        if datos == b'STOP\r\n':
            self.bandera = b'1\n'
        elif b'machine.reset()' in datos:
            self.reinicio = True

    def _leer_prompt(self, _timeout):
        self.consultas_prompt += 1
        if self.modo == 'stop-incierto' and self.consultas_prompt <= 2:
            raise TimeoutError('Sin acuse de STOP')
        self.desfasado = False
        return b'>>>'

    def preparar_escritura(self):
        if self.desfasado:
            raise RuntimeError('El prompt requiere resincronización')

    def existe(self, nombre):
        return nombre == 'maintenance.flag' and self.bandera is not None

    def comando(self, linea):
        if "f=open('maintenance.flag','w')" in linea:
            if self.modo != 'bandera-no-creada':
                self.bandera = b'1\n'
            self.desfasado = True
            raise TimeoutError('Acuse de escritura perdido')
        if "os.remove('maintenance.flag')" in linea:
            self.bandera = None

    def consultar_linea(self, prefijo, _comando):
        if prefijo == 'FLAG:':
            return self.bandera.hex()
        raise AssertionError('Consulta inesperada')

    def cerrar(self):
        self.cerrado = True


class PruebaInspeccion(unittest.TestCase):
    def ejecutar_con_doble(self, modo, interrupcion=False):
        repl = ReplSimulado(modo)
        modulo = SimpleNamespace(ReplFriendly=lambda _puerto: repl)
        with TemporaryDirectory(dir=Path(__file__).parent) as directorio:
            with patch.object(inspeccion, 'TRABAJO', Path(directorio)), \
                 patch.object(inspeccion, 'comprobar_exclusividad'), \
                 patch.dict('sys.modules', {'transferencia_repl': modulo}), \
                 patch.object(inspeccion, 'observar_arranque',
                              side_effect=KeyboardInterrupt if interrupcion else None):
                with self.assertRaises((TimeoutError, RuntimeError)):
                    inspeccion.main()
        self.assertTrue(repl.cerrado)
        if not interrupcion:
            self.assertIsNone(repl.bandera)
            self.assertTrue(repl.reinicio)

    def test_bandera_creada_con_acuse_perdido(self):
        self.ejecutar_con_doble('bandera-incierta')

    def test_stop_creado_con_acuse_perdido(self):
        self.ejecutar_con_doble('stop-incierto')

    def test_bandera_no_creada_y_acuse_perdido(self):
        self.ejecutar_con_doble('bandera-no-creada')

    def test_interrupcion_durante_recuperacion_cierra_serial(self):
        self.ejecutar_con_doble('bandera-incierta', interrupcion=True)

    def test_rutas_inseguras_se_rechazan(self):
        for ruta in ('relativa', '/a/../b', '/', '/ñ.py'):
            with self.subTest(ruta=ruta), self.assertRaises(RuntimeError):
                inspeccion.nombre_seguro(ruta)


if __name__ == '__main__':
    unittest.main()
