"""Pruebas sinteticas de edicion activa y sincronizacion con Java."""

import argparse
import json
import os
import shutil
import tempfile
import threading
import unittest
from collections import deque
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

import numpy as np

import aplicacion_local
import capture
import control_interfaz_local
import detect
import edicion_permanente
import estado_calibracion
import test_aplicacion_local as fixture
from configuracion_local import ruta_vinculo
from calibracion_zonas import guardar_calibracion
from publicador_java import PublicadorVision, cargar_configuracion
from temporal_validation import load_zones


class EdicionPermanenteLocalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        carpeta = Path(self.tmp.name)
        productiva, local = carpeta / "productiva", carpeta / "local"
        productiva.mkdir()
        local.mkdir()
        self.productiva = productiva / "zones.json"
        self.local = local / "zones.json"
        self.inicial = fixture.crear_calibracion(self.productiva)
        self.cajones_java = {
            etiqueta: str(uuid4()) for etiqueta in self.inicial.zonas
        }
        guardar_calibracion(
            self.productiva, self.inicial, "http",
            atributos_por_zona={
                etiqueta: {"cajonId": cajon}
                for etiqueta, cajon in self.cajones_java.items()
            },
        )
        shutil.copyfile(self.productiva, self.local)
        shutil.copyfile(ruta_vinculo(self.productiva), ruta_vinculo(self.local))
        self.token = carpeta / "token"
        self.token.write_text("token-sintetico")
        self.entorno = {
            "VISION_JAVA_URL": "http://127.0.0.1:8080",
            "VISION_FUENTE_ID": str(uuid4()),
            "VISION_TOKEN_ARCHIVO": str(self.token),
        }
        self.config = cargar_configuracion(
            self.productiva, load_zones(self.productiva), self.entorno,
        )
        self.captura = capture.CapturadorReciente("http", fixture.FUENTE, None)
        self.imagen = np.full((fixture.ALTO, fixture.ANCHO, 3), 100, dtype=np.uint8)
        self.captura._publicar(self.imagen, "sintetica", nueva_conexion=True)
        self.publicador = PublicadorVision(self.config)
        self.args = argparse.Namespace(
            source="http", zones=self.productiva, ruta_productiva=self.productiva,
            local_proposal=self.local, seleccion_segura=True,
            publicador=self.publicador, configuracion_vision=self.config,
        )
        self.edicion = edicion_permanente.EdicionPermanente(self.args, fixture.FUENTE)

    def abrir_editor(self):
        self.assertTrue(self.edicion.iniciar(self.captura, 5), self.edicion.mensaje)
        self.assertIs(self.args.publicador, self.publicador)
        self.assertEqual(self.edicion.editor.ruta, self.productiva)
        return self.edicion.editor

    def crear_c9(self):
        editor = self.edicion.editor
        editor.tecla(ord("n"))
        for x, y in [(500, 200), (560, 200), (560, 260), (500, 260)]:
            editor.raton(1, x, y, 0, None)
        editor.tecla(13)
        self.assertIn("C9", editor.borrador.zonas)

    def respuesta_java(self):
        zonas = []
        for etiqueta, identidad in self.edicion.editor.borrador.vision_zone_ids.items():
            cajon = self.cajones_java.get(etiqueta)
            zonas.append({
                "visionZoneId": str(identidad),
                "etiqueta": etiqueta,
                "cajonId": cajon or str(uuid4()),
            })
        return {"fuenteId": self.entorno["VISION_FUENTE_ID"], "zonas": zonas}

    def pulsar_boton(self, etiqueta):
        editor = self.edicion.editor
        _, tecla, (x, y, ancho, alto) = next(
            boton for boton in editor.botones_calibracion() if boton[0] == etiqueta)
        cola = deque()
        for evento in (detect.cv2.EVENT_LBUTTONDOWN, detect.cv2.EVENT_LBUTTONUP):
            detect._raton_en_marco(editor, evento, x + ancho // 2, y + alto // 2, 0, None, cola)
        self.assertEqual(list(cola), [(editor, tecla)])
        entrada = detect._tecla_calibracion(255, editor, cola)
        self.assertFalse(cola)
        return self.edicion.tecla(entrada, self.captura, 5)

    def test_botones_put_rechazado_cancelar_y_fuente_no_vigente(self):
        anterior = self.productiva.read_bytes()
        with patch.dict(os.environ, self.entorno, clear=True), \
             patch.object(PublicadorVision, "detener", return_value=True), \
             patch.object(PublicadorVision, "_solicitar_calibracion", return_value=(400, b"")) as solicitar, \
             patch.object(PublicadorVision, "iniciar") as iniciar_nuevo:
            self.abrir_editor()
            self.crear_c9()
            self.assertIsNone(self.pulsar_boton("Sincronizar y guardar"))
            self.assertEqual(solicitar.call_count, 1)
            self.assertIsNone(self.edicion.paso_pendiente)
            self.assertTrue(self.edicion.activa)
            self.assertEqual(self.productiva.read_bytes(), anterior)
            self.assertEqual(self.pulsar_boton("Cancelar"), "cancelada")
            iniciar_nuevo.assert_called_once()
        self.assertEqual(self.productiva.read_bytes(), anterior)

        self.publicador = self.args.publicador
        with patch.dict(os.environ, self.entorno, clear=True), \
             patch.object(PublicadorVision, "_solicitar_calibracion") as solicitar:
            self.abrir_editor()
            self.crear_c9()
            self.captura._publicar(self.imagen, "sintetica", nueva_conexion=True)
            self.assertIsNone(self.pulsar_boton("Sincronizar y guardar"))
            solicitar.assert_not_called()
            self.assertTrue(self.edicion.editor.fuente_cambiada)
            self.assertEqual(self.productiva.read_bytes(), anterior)

    def test_botones_pendiente_local_reintenta_sin_otro_put_o_get(self):
        anterior = self.productiva.read_bytes()
        llamadas, respuesta, intentos = [], {}, []

        def solicitar(metodo, _cuerpo=None):
            llamadas.append(metodo)
            if metodo == "PUT":
                respuesta.update(self.respuesta_java())
                return 204, b""
            return 200, json.dumps(respuesta).encode()

        with patch.dict(os.environ, self.entorno, clear=True), \
             patch.object(PublicadorVision, "detener", return_value=True), \
             patch.object(PublicadorVision, "_solicitar_calibracion", side_effect=solicitar), \
             patch.object(PublicadorVision, "iniciar") as iniciar_nuevo:
            editor = self.abrir_editor()
            self.crear_c9()
            guardar = editor.guardar_con_asociaciones

            def guardar_con_fallo(cajones):
                intentos.append(1)
                if len(intentos) == 1:
                    raise OSError("fallo sintetico")
                return guardar(cajones)

            with patch.object(editor, "guardar_con_asociaciones", side_effect=guardar_con_fallo):
                self.assertIsNone(self.pulsar_boton("Sincronizar y guardar"))
                self.assertEqual(self.edicion.paso_pendiente, "local")
                self.assertTrue(editor.bloqueado)
                self.assertEqual(self.productiva.read_bytes(), anterior)
                self.assertIsNone(self.pulsar_boton("Cancelar"))
                self.assertIs(self.edicion.editor, editor)
                self.assertEqual(self.pulsar_boton("Sincronizar y guardar"), "actualizar")
            self.assertEqual(llamadas, ["PUT", "GET"])
            self.assertEqual(len(intentos), 2)
            iniciar_nuevo.assert_called_once()
        datos = json.loads(self.productiva.read_text())
        zonas = {zona["id"]: zona for zona in datos["zones"]}
        self.assertEqual(set(zonas), {f"C{numero}" for numero in range(1, 10)})
        self.assertEqual({etiqueta: zonas[etiqueta]["cajonId"] for etiqueta in self.inicial.zonas},
                         self.cajones_java)
        self.assertEqual({etiqueta: zonas[etiqueta]["vision_zone_id"] for etiqueta in self.inicial.zonas},
                         {etiqueta: str(identidad) for etiqueta, identidad in self.inicial.vision_zone_ids.items()})

    def test_fallo_tras_guardar_asociaciones_restaura_y_reintenta_solo_local(self):
        anteriores = self.productiva.read_bytes(), ruta_vinculo(self.productiva).read_bytes()
        llamadas, respuesta, observadas = [], {}, []
        compatible_real = aplicacion_local._sidecar_compatible

        def solicitar(metodo, _cuerpo=None):
            llamadas.append(metodo)
            if metodo == "PUT":
                respuesta.update(self.respuesta_java())
                return 204, b""
            return 200, json.dumps(respuesta).encode()

        def fallar_una_verificacion(*args):
            observadas.append(self.productiva.read_bytes())
            if len(observadas) == 1:
                return False
            return compatible_real(*args)

        with patch.dict(os.environ, self.entorno, clear=True), \
             patch.object(PublicadorVision, "detener", return_value=True), \
             patch.object(PublicadorVision, "_solicitar_calibracion", side_effect=solicitar), \
             patch.object(PublicadorVision, "iniciar") as iniciar_nuevo:
            editor = self.abrir_editor()
            self.crear_c9()
            with patch.object(aplicacion_local, "_sidecar_compatible", side_effect=fallar_una_verificacion):
                self.assertIsNone(self.pulsar_boton("Sincronizar y guardar"))
            self.assertGreaterEqual(len(observadas), 2)
            self.assertNotEqual(observadas[0], anteriores[0])
            self.assertEqual((self.productiva.read_bytes(), ruta_vinculo(self.productiva).read_bytes()), anteriores)
            self.assertEqual(self.edicion.paso_pendiente, "local")
            self.assertTrue(editor.bloqueado)
            self.assertIsNone(self.args.publicador)
            self.assertEqual(llamadas, ["PUT", "GET"])
            respaldo = next((self.productiva.parent / "respaldos").iterdir())
            self.assertEqual((respaldo / self.productiva.name).read_bytes(), anteriores[0])
            self.assertEqual((respaldo / ruta_vinculo(self.productiva).name).read_bytes(), anteriores[1])
            self.assertEqual(self.pulsar_boton("Sincronizar y guardar"), "actualizar")
            self.assertEqual(llamadas, ["PUT", "GET"])
            iniciar_nuevo.assert_called_once()
        zonas = {zona["id"]: zona for zona in json.loads(self.productiva.read_text())["zones"]}
        self.assertEqual(set(zonas), {f"C{numero}" for numero in range(1, 10)})
        self.assertEqual({etiqueta: zonas[etiqueta]["cajonId"] for etiqueta in self.inicial.zonas},
                         self.cajones_java)

    def test_botones_permanente_bucle_put_get_pendiente_y_reintento(self):
        class FinBucle(Exception):
            pass

        anterior = self.productiva.read_bytes()
        llamadas, respuesta = [], {}
        raton, bucle = {}, {"tick": 0, "fin": False}
        pedido = {"display": ":sintetico", "cancelado": threading.Event()}
        control = Mock()
        control.siguiente.side_effect = [pedido] + [None] * 20
        self.args.http_url = fixture.FUENTE
        self.args.device = None
        self.args.headless = True
        self.args.permanente = True
        self.args.control_socket = Path(self.tmp.name) / "control-sintetico"
        self.args.max_frame_age = 5
        estado = detect.inicializar_estado(self.productiva)
        mostrar = detect._mostrar_interfaz

        def solicitar(metodo, _cuerpo=None):
            llamadas.append(metodo)
            if metodo == "PUT":
                respuesta.update(self.respuesta_java())
                return 204, b""
            if llamadas.count("GET") == 1:
                return 503, b""
            return 200, json.dumps(respuesta).encode()

        def mostrar_capturando(imagen, coordenadas=None):
            mostrar(imagen, coordenadas)
            raton["ajuste"] = coordenadas["ajuste"]

        def enviar(evento, x, y, flags=0):
            ancho, alto, rx, ry, mx, my = raton["ajuste"]
            xx = round(mx + (x + .5) * rx / ancho - .5)
            yy = round(my + (y + .5) * ry / alto - .5)
            raton["callback"](evento, xx, yy, flags, None)

        def boton(etiqueta):
            _, _, (x, y, ancho, alto) = next(
                b for b in self.edicion.editor.botones_calibracion() if b[0] == etiqueta)
            enviar(detect.cv2.EVENT_LBUTTONDOWN, x + ancho // 2, y + alto // 2)
            enviar(detect.cv2.EVENT_LBUTTONUP, x + ancho // 2, y + alto // 2)

        def esperar(_):
            bucle["tick"] += 1
            tick = bucle["tick"]
            if tick == 1:
                return ord("c")
            if tick == 2:
                boton("Nuevo")
            elif tick == 3:
                c = detect.ALTO_CABECERA
                for x, y in ((500, 200), (560, 200), (560, 260), (500, 260)):
                    enviar(detect.cv2.EVENT_LBUTTONDOWN, x, y + c)
                    enviar(detect.cv2.EVENT_LBUTTONUP, x, y + c)
                boton("Aceptar")
            elif tick == 4:
                self.assertIn("C9", self.edicion.editor.borrador.zonas)
                boton("Sincronizar y guardar")
            elif tick == 5:
                self.assertEqual(self.edicion.paso_pendiente, "get")
                self.assertTrue(self.edicion.editor.bloqueado)
                self.assertEqual(self.productiva.read_bytes(), anterior)
                boton("Cancelar")
            elif tick == 6:
                self.assertTrue(self.edicion.activa)
                self.assertEqual(self.edicion.paso_pendiente, "get")
                self.assertEqual(llamadas, ["PUT", "GET"])
                boton("Sincronizar y guardar")
            elif tick == 7:
                self.assertFalse(self.edicion.activa)
                self.assertEqual(llamadas, ["PUT", "GET", "GET"])
                bucle["fin"] = True
                return ord("x")
            return 255

        def muestra(*_):
            if bucle["fin"]:
                raise FinBucle()
            return self.captura.instantanea()

        with ExitStack() as mocks:
            mocks.enter_context(patch.dict(os.environ, self.entorno, clear=True))
            mocks.enter_context(patch.object(control_interfaz_local, "ControlInterfaz", return_value=control))
            mocks.enter_context(patch.object(edicion_permanente, "EdicionPermanente", return_value=self.edicion))
            mocks.enter_context(patch.object(detect, "CapturadorReciente", return_value=self.captura))
            mocks.enter_context(patch.object(self.captura, "iniciar"))
            mocks.enter_context(patch.object(self.captura, "detener", return_value=True))
            mocks.enter_context(patch.object(self.captura, "esperar", side_effect=muestra))
            mocks.enter_context(patch.object(self.publicador, "invalidar"))
            mocks.enter_context(patch.object(PublicadorVision, "detener", return_value=True))
            mocks.enter_context(patch.object(PublicadorVision, "_solicitar_calibracion", side_effect=solicitar))
            iniciar_nuevo = mocks.enter_context(patch.object(PublicadorVision, "iniciar"))
            mocks.enter_context(patch.object(detect, "inferir", return_value=([], None, None)))
            mocks.enter_context(patch.object(detect.FrameQualityGuard, "inspect", return_value=(True, "")))
            mocks.enter_context(patch.object(detect, "probar_grafica_aislada", return_value=True))
            mocks.enter_context(patch.object(detect, "_crear_ventana"))
            mocks.enter_context(patch.object(detect, "_dimensiones_ventana", return_value=(800, 941)))
            mocks.enter_context(patch.object(detect, "_mostrar_interfaz", side_effect=mostrar_capturando))
            mocks.enter_context(patch.object(detect.cv2, "setMouseCallback",
                                            side_effect=lambda _, cb: raton.update(callback=cb)))
            mocks.enter_context(patch.object(detect.cv2, "imshow"))
            mocks.enter_context(patch.object(detect.cv2, "destroyWindow"))
            mocks.enter_context(patch.object(detect.cv2, "waitKey", side_effect=esperar))
            mocks.enter_context(patch.object(detect, "ventana_cerrada", return_value=False))
            with self.assertRaises(FinBucle):
                detect.ejecutar_directo(self.args, object(), estado)
            iniciar_nuevo.assert_called_once()
        datos = json.loads(self.productiva.read_text())
        zonas = {zona["id"]: zona for zona in datos["zones"]}
        self.assertEqual(set(zonas), {f"C{numero}" for numero in range(1, 10)})
        self.assertEqual({etiqueta: zonas[etiqueta]["cajonId"] for etiqueta in self.inicial.zonas},
                         self.cajones_java)
        self.assertEqual({etiqueta: zonas[etiqueta]["vision_zone_id"] for etiqueta in self.inicial.zonas},
                         {etiqueta: str(identidad) for etiqueta, identidad in self.inicial.vision_zone_ids.items()})
        self.assertIsNotNone(zonas["C9"]["cajonId"])

    def test_usa_calibracion_activa_y_cancelar_reanuda_publicacion_anterior(self):
        local = self.local.read_bytes()
        with patch.dict(os.environ, self.entorno, clear=True), \
             patch.object(PublicadorVision, "iniciar") as iniciar_nuevo:
            self.abrir_editor()
            self.assertEqual(self.edicion.tecla(27, self.captura, 5), "cancelada")
            iniciar_nuevo.assert_not_called()
            self.assertIs(self.args.publicador, self.publicador)
        self.assertEqual(self.local.read_bytes(), local)

    def test_put_completo_get_asignaciones_y_guardado_atomico_activo(self):
        configuracion_anterior = self.productiva.read_bytes()
        llamadas = []
        cuerpos = []
        respuesta = {}

        def solicitar(metodo, cuerpo=None):
            llamadas.append(metodo)
            cuerpos.append(cuerpo)
            if metodo == "PUT":
                respuesta.update(self.respuesta_java())
                return 204, b""
            return 200, json.dumps(respuesta).encode()

        with patch.dict(os.environ, self.entorno, clear=True), \
             patch.object(PublicadorVision, "_solicitar_calibracion", side_effect=solicitar), \
             patch.object(PublicadorVision, "iniciar") as iniciar_nuevo:
            editor = self.abrir_editor()
            self.crear_c9()
            self.assertEqual(self.edicion.tecla(ord("s"), self.captura, 5), "actualizar")
            iniciar_nuevo.assert_called_once()
        self.assertEqual(llamadas, ["PUT", "GET"])
        self.assertEqual(len(cuerpos[0]["zonas"]), 9)
        self.assertEqual(
            {fila["etiqueta"] for fila in cuerpos[0]["zonas"]},
            {f"C{numero}" for numero in range(1, 10)},
        )
        self.assertEqual(
            {fila["visionZoneId"] for fila in cuerpos[0]["zonas"]},
            {str(identidad) for identidad in editor.borrador.vision_zone_ids.values()},
        )
        por_etiqueta = {fila["etiqueta"]: fila for fila in cuerpos[0]["zonas"]}
        for etiqueta, cajon in self.cajones_java.items():
            self.assertEqual(por_etiqueta[etiqueta]["cajonId"], cajon)
        self.assertIsNone(por_etiqueta["C9"]["cajonId"])
        self.assertEqual(self.args.zones, self.productiva)
        self.assertNotEqual(self.productiva.read_bytes(), configuracion_anterior)
        datos = json.loads(self.productiva.read_text())
        zonas = {zona["id"]: zona for zona in datos["zones"]}
        self.assertEqual(len(zonas), 9)
        self.assertEqual(set(zonas), {f"C{numero}" for numero in range(1, 10)})
        self.assertIsNotNone(zonas["C9"]["cajonId"])
        self.assertEqual(
            {etiqueta: zonas[etiqueta]["cajonId"] for etiqueta in self.inicial.zonas},
            self.cajones_java,
        )
        self.assertEqual(
            set(self.args.configuracion_vision.identidades),
            set(zonas),
        )
        self.assertFalse(ruta_vinculo(self.productiva).read_bytes() == b"")

    def test_put_rechazado_deja_archivo_y_permite_cancelar(self):
        anterior = self.productiva.read_bytes()
        llamadas = []

        def solicitar(metodo, _cuerpo=None):
            llamadas.append(metodo)
            return 400, b""

        with patch.dict(os.environ, self.entorno, clear=True), \
             patch.object(PublicadorVision, "_solicitar_calibracion", side_effect=solicitar), \
             patch.object(PublicadorVision, "iniciar") as iniciar_nuevo:
            self.abrir_editor()
            self.crear_c9()
            self.assertIsNone(self.edicion.tecla(ord("s"), self.captura, 5))
            self.assertEqual(llamadas, ["PUT"])
            self.assertEqual(self.productiva.read_bytes(), anterior)
            self.assertIsNone(self.edicion.paso_pendiente)
            self.assertTrue(self.edicion.activa)
            self.assertEqual(self.edicion.tecla(27, self.captura, 5), "cancelada")
            iniciar_nuevo.assert_called_once()
        self.assertEqual(self.productiva.read_bytes(), anterior)

    def test_get_fallido_deja_publicacion_pausada_y_s_reintenta_solo_get(self):
        anterior = self.productiva.read_bytes()
        llamadas = []
        respuesta = {}

        def solicitar(metodo, _cuerpo=None):
            llamadas.append(metodo)
            if metodo == "PUT":
                respuesta.update(self.respuesta_java())
                return 204, b""
            if llamadas.count("GET") == 1:
                return 503, b""
            return 200, json.dumps(respuesta).encode()

        with patch.dict(os.environ, self.entorno, clear=True), \
             patch.object(PublicadorVision, "_solicitar_calibracion", side_effect=solicitar), \
             patch.object(PublicadorVision, "iniciar") as iniciar_nuevo:
            self.abrir_editor()
            self.crear_c9()
            editor = self.edicion.editor
            self.assertIsNone(self.edicion.tecla(ord("s"), self.captura, 5))
            self.assertEqual(self.productiva.read_bytes(), anterior)
            self.assertEqual(self.edicion.paso_pendiente, "get")
            self.assertFalse(self.edicion.cerrar())
            self.assertIs(self.edicion.editor, editor)
            self.assertIsNone(self.args.publicador)
            self.assertEqual(self.edicion.tecla(ord("s"), self.captura, 5), "actualizar")
            self.assertEqual(llamadas, ["PUT", "GET", "GET"])
            iniciar_nuevo.assert_called_once()
        datos = json.loads(self.productiva.read_text())
        zonas = {zona["id"]: zona for zona in datos["zones"]}
        self.assertEqual(len(zonas), 9)
        self.assertIsNotNone(zonas["C9"]["cajonId"])

    def test_drenaje_ocurre_al_guardar_y_aborta_put_si_no_termina(self):
        with patch.dict(os.environ, self.entorno, clear=True), \
             patch.object(self.publicador, "detener", return_value=False) as detener, \
             patch.object(PublicadorVision, "_solicitar_calibracion") as solicitar:
            self.abrir_editor()
            self.crear_c9()
            self.assertIsNone(self.edicion.tecla(ord("s"), self.captura, 5))
            detener.assert_called_once()
            solicitar.assert_not_called()
            self.assertIs(self.args.publicador, self.publicador)
            self.assertEqual(self.edicion.paso_pendiente, None)
            self.assertTrue(self.edicion.activa)

    def test_marcador_invalido_no_permite_publicacion(self):
        marcador = self.local.parent / estado_calibracion.MARCADOR
        marcador.write_text("invalido")
        marcador.chmod(0o600)
        self.assertEqual(
            estado_calibracion.seleccion_activa(self.productiva, self.local),
            (self.productiva, False),
        )


if __name__ == "__main__":
    unittest.main()
