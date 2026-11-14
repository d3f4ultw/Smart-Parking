"""Prueba callbacks y recuperación del activador sin hardware."""

import importlib.util
import itertools
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import activar_firmware as activador


class ReplSimulado:
    def __init__(self, lineas=b''):
        self.serie = self
        self.lineas = [lineas]
        self.bandera = None
        self.escrituras = []
        self.cerrado = False
        self._buffer = bytearray()
        self.responder_ping = False

    def write(self, datos):
        self.escrituras.append(datos)
        if datos == b'PING\r\n' and self.responder_ping:
            self.lineas.append(b'PONG\r\n')

    def read(self, _cantidad):
        return self.lineas.pop(0) if self.lineas else b''

    def _leer_prompt(self, _timeout):
        return b'>>>'

    def preparar_escritura(self):
        pass

    def consultar_linea(self, prefijo, _codigo):
        return {'CACHE:': 'True', 'IMPORTS:': 'OK', 'FLAG:': '310a'}[prefijo]

    def existe(self, nombre):
        return nombre == '/maintenance.flag' and self.bandera is not None

    def comando(self, comando):
        if "open('/maintenance.flag','w')" in comando:
            self.bandera = b'1\n'
        elif "os.remove('/maintenance.flag')" in comando:
            self.bandera = None

    def cerrar(self):
        self.cerrado = True


class PruebaActivador(unittest.TestCase):
    def setUp(self):
        activador.ESTADO.update(sesion=None, bandera_propia=False)

    def test_arranque_exige_tres_lectores_y_ping(self):
        datos = (b'READY,1\r\nDIAG,RFID1,ESTADO,READY\r\n'
                 b'DIAG,RFID2,ESTADO,READY\r\nDIAG,RFID3,ESTADO,READY\r\n'
                 b'PONG\r\nPONG\r\nPONG\r\n')
        resultado = activador.verificar_arranque(ReplSimulado(datos))
        self.assertTrue(resultado['imports'])
        self.assertEqual(set(resultado['lectores']), {'RFID1', 'RFID2', 'RFID3'})
        self.assertEqual(resultado['pongs'], 3)

    def test_lectura_no_solicitada_falla_sin_divulgar_trama(self):
        repl = ReplSimulado(b'RFID3,identificador-privado\r\n')
        with self.assertRaises(RuntimeError) as error:
            activador.verificar_arranque(repl)
        self.assertNotIn('identificador-privado', str(error.exception))

    def test_resincronizacion_recrea_bandera_si_el_ack_se_perdio(self):
        repl = ReplSimulado()
        self.assertIs(activador.resincronizar(repl, permitir_crear_bandera=True), repl)
        self.assertEqual(repl.bandera, b'1\n')

    def test_stop_exige_pong_si_no_se_conoce_la_bandera(self):
        repl = ReplSimulado(b'>>>')
        with patch.object(activador.time, 'monotonic', side_effect=[0, 0, 1, 2, 3, 4]):
            with self.assertRaises(RuntimeError):
                activador.solicitar_stop(repl)
        self.assertNotIn(b'STOP\r\n', repl.escrituras)
        self.assertFalse(activador.ESTADO['bandera_propia'])

    def test_stop_con_pong_registra_propiedad(self):
        repl = ReplSimulado()
        repl.responder_ping = True
        activador.solicitar_stop(repl)
        self.assertIn(b'STOP\r\n', repl.escrituras)
        self.assertTrue(activador.ESTADO['bandera_propia'])

    def test_pong_antiguo_no_autoriza_stop(self):
        repl = ReplSimulado(b'PONG\r\n')
        with patch.object(activador.time, 'monotonic', side_effect=itertools.count()):
            with self.assertRaises(RuntimeError):
                activador.solicitar_stop(repl)
        self.assertNotIn(b'STOP\r\n', repl.escrituras)

    def test_ctrl_c_en_uart_reintenta_ping_con_parser_instalado(self):
        raiz = Path(__file__).parent / 'firmware-anterior/comunicacion'
        config = SimpleNamespace(MAXIMO_LINEA_SERIAL=96, UART_ID=1, UART_RX=3, UART_TX=1, VELOCIDAD_USB=115200)
        spec = importlib.util.spec_from_file_location('serial_original_prueba', raiz / 'serial.py')
        serial_original = importlib.util.module_from_spec(spec)
        with patch.dict('sys.modules', {'config': config}):
            spec.loader.exec_module(serial_original)
        spec = importlib.util.spec_from_file_location('protocolo_original_prueba', raiz / 'protocolo.py')
        protocolo_original = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(protocolo_original)

        class UART:
            entrada = b''
            salida = b''

            def read(self):
                datos, self.entrada = self.entrada, b''
                return datos

            def write(self, datos):
                self.salida += datos.encode() if isinstance(datos, str) else datos

        for propia in (False, True):
            with self.subTest(bandera_propia=propia):
                uart = UART()
                puerto = serial_original.PuertoSerial(uart)
                protocolo = protocolo_original.Protocolo(puerto, None, lambda: 0)

                class Host:
                    def write(self, datos):
                        uart.entrada += datos
                        protocolo.atender()

                    def read(self, _cantidad):
                        datos, uart.salida = uart.salida, b''
                        return datos

                host = Host()
                repl = SimpleNamespace(serie=host, _buffer=bytearray(), _leer_prompt=lambda _tiempo: b'>>>')
                activador.ESTADO['bandera_propia'] = propia
                host.write(b'\x03')
                with patch.object(activador.time, 'monotonic', side_effect=itertools.count()):
                    activador.solicitar_stop(repl)
                self.assertTrue(protocolo.detener)

    def test_reconexion_fallida_cierra_ambas_sesiones(self):
        anterior = ReplSimulado()
        nueva = ReplSimulado()
        nueva.entrar = lambda permitir_stop: None
        with patch.object(anterior, '_leer_prompt', side_effect=OSError), \
             patch.object(nueva, 'preparar_escritura', side_effect=KeyboardInterrupt), \
             patch.object(activador, 'ReplFriendly', return_value=nueva):
            with self.assertRaises(KeyboardInterrupt):
                activador.resincronizar(anterior, permitir_crear_bandera=True)
        self.assertTrue(anterior.cerrado)
        self.assertTrue(nueva.cerrado)

    def test_reintenta_bandera_creada_sin_acuse(self):
        repl = ReplSimulado()
        original = repl.comando
        veces = []

        def comando_incierto(texto):
            original(texto)
            if "open('/maintenance.flag','w')" in texto and not veces:
                veces.append(True)
                raise TimeoutError('Acuse perdido')

        repl.comando = comando_incierto
        with patch.object(activador, 'retirar_bandera_y_arrancar') as reiniciar, \
             patch.object(activador, 'verificar_identidad'), \
             patch.object(activador.instalacion, '_validar_local', return_value=({}, {}, {})), \
             patch.object(activador.instalacion, '_verificar_estado'):
            self.assertIs(activador.recuperar_previo(repl), repl)
        reiniciar.assert_called_once_with(repl)

    def test_fallo_de_arranque_normal_invoca_reversion(self):
        repl = ReplSimulado()
        spec = SimpleNamespace(loader=SimpleNamespace(exec_module=lambda _m: None))
        modulo = SimpleNamespace(verificar_identidad=lambda _r: None)
        with patch.object(activador.inspeccion, 'comprobar_exclusividad'), \
             patch.object(activador, 'ReplFriendly', return_value=repl), \
             patch.object(activador.importlib.util, 'spec_from_file_location', return_value=spec), \
             patch.object(activador.importlib.util, 'module_from_spec', return_value=modulo), \
             patch.object(activador.instalacion, 'instalar_stage3', return_value={'sesion': repl}), \
             patch.object(activador, 'retirar_bandera_y_arrancar', side_effect=TimeoutError), \
             patch.object(activador, 'recuperar_original', return_value=repl) as recuperar:
            self.assertFalse(activador.main())
        recuperar.assert_called_once_with(repl)
        self.assertTrue(repl.cerrado)

    def test_reversion_incompleta_no_reinicia_original(self):
        repl = ReplSimulado()
        spec = SimpleNamespace(loader=SimpleNamespace(exec_module=lambda _m: None))
        modulo = SimpleNamespace(verificar_identidad=lambda _r: None)
        error = activador.instalacion.ErrorInstalacion('promoción', False, repl)
        with patch.object(activador.inspeccion, 'comprobar_exclusividad'), \
             patch.object(activador, 'ReplFriendly', return_value=repl), \
             patch.object(activador.importlib.util, 'spec_from_file_location', return_value=spec), \
             patch.object(activador.importlib.util, 'module_from_spec', return_value=modulo), \
             patch.object(activador.instalacion, 'instalar_stage3', side_effect=error), \
             patch.object(activador, 'retirar_bandera_y_arrancar') as reiniciar:
            self.assertFalse(activador.main())
        reiniciar.assert_not_called()
        self.assertTrue(repl.cerrado)

    def test_interrupcion_al_recibir_resultado_invoca_reversion(self):
        class ResultadoInterrumpido:
            def __getitem__(self, _clave):
                raise KeyboardInterrupt()

        repl = ReplSimulado()
        spec = SimpleNamespace(loader=SimpleNamespace(exec_module=lambda _m: None))
        modulo = SimpleNamespace(verificar_identidad=lambda _r: None)
        with patch.object(activador.inspeccion, 'comprobar_exclusividad'), \
             patch.object(activador, 'ReplFriendly', return_value=repl), \
             patch.object(activador.importlib.util, 'spec_from_file_location', return_value=spec), \
             patch.object(activador.importlib.util, 'module_from_spec', return_value=modulo), \
             patch.object(activador.instalacion, 'instalar_stage3', return_value=ResultadoInterrumpido()), \
             patch.object(activador, 'recuperar_original', return_value=repl) as recuperar:
            self.assertFalse(activador.main())
        recuperar.assert_called_once_with(repl)
        self.assertTrue(repl.cerrado)

    def test_interrupcion_con_sesion_reemplazada_recupera_la_vigente(self):
        class ResultadoInterrumpido:
            def __getitem__(self, _clave):
                raise KeyboardInterrupt()

        anterior, nueva = ReplSimulado(), ReplSimulado()
        spec = SimpleNamespace(loader=SimpleNamespace(exec_module=lambda _m: None))
        modulo = SimpleNamespace(verificar_identidad=lambda _r: None)

        def instalar(**_argumentos):
            anterior.cerrar()
            activador.ESTADO['sesion'] = nueva
            return ResultadoInterrumpido()

        with patch.object(activador.inspeccion, 'comprobar_exclusividad'), \
             patch.object(activador, 'ReplFriendly', return_value=anterior), \
             patch.object(activador.importlib.util, 'spec_from_file_location', return_value=spec), \
             patch.object(activador.importlib.util, 'module_from_spec', return_value=modulo), \
             patch.object(activador.instalacion, 'instalar_stage3', side_effect=instalar), \
             patch.object(activador, 'recuperar_original', return_value=nueva) as recuperar:
            self.assertFalse(activador.main())
        recuperar.assert_called_once_with(nueva)
        self.assertTrue(anterior.cerrado)
        self.assertTrue(nueva.cerrado)

    def test_interrupcion_al_enviar_ctrl_c_intenta_recuperar(self):
        repl = ReplSimulado()
        repl.write = lambda _datos: (_ for _ in ()).throw(KeyboardInterrupt())
        with patch.object(activador.inspeccion, 'comprobar_exclusividad'), \
             patch.object(activador, 'ReplFriendly', return_value=repl), \
             patch.object(activador, 'recuperar_previo', return_value=repl) as recuperar:
            self.assertFalse(activador.main())
        recuperar.assert_called_once_with(repl)
        self.assertTrue(repl.cerrado)

    def test_bandera_ajena_no_se_elimina_ni_se_reinicia(self):
        repl = ReplSimulado()
        repl.bandera = b'1\n'
        with patch.object(activador.inspeccion, 'comprobar_exclusividad'), \
             patch.object(activador, 'ReplFriendly', return_value=repl), \
             patch.object(activador, 'recuperar_previo') as recuperar:
            self.assertFalse(activador.main())
        recuperar.assert_not_called()
        self.assertEqual(repl.bandera, b'1\n')
        self.assertTrue(repl.cerrado)


if __name__ == '__main__':
    unittest.main()
