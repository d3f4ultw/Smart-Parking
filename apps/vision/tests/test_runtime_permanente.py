"""Pruebas focales del runtime permanente."""

import argparse
import copy
import hashlib
import json
import os
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

import control_interfaz_local
import detect
import edicion_permanente
from aplicacion_local import EditorLocal
from configuracion_local import ruta_vinculo
from publicador_java import PublicadorVision, cargar_configuracion
import test_aplicacion_local as fixture
import capture
import numpy as np

ALTO, ANCHO, FUENTE = fixture.ALTO, fixture.ANCHO, fixture.FUENTE
crear_calibracion = fixture.crear_calibracion


class ControlLocalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.carpeta = Path(self.tmp.name)
        os.chmod(self.carpeta, 0o700)
        self.ruta = self.carpeta / "control.sock"
        self.control = control_interfaz_local.ControlInterfaz(self.ruta)
        self.control.iniciar()
        self.addCleanup(self.control.cerrar)

    def enviar(self, contenido):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as cliente:
            cliente.settimeout(3)
            cliente.connect(str(self.ruta))
            cliente.sendall(contenido)
            return cliente.recv(1024)

    def test_rechaza_comando_y_mensaje_excesivo(self):
        solicitud = b'{"version":1,"comando":"otro","display":":0"}\n'
        self.assertFalse(json.loads(self.enviar(solicitud))["aceptado"])
        self.assertFalse(json.loads(self.enviar(b"x" * 513 + b"\n"))["aceptado"])
        self.assertIsNone(self.control.siguiente())

    def test_peer_distinto_no_se_acepta(self):
        with patch.object(control_interfaz_local.os, "getuid", return_value=os.getuid() + 1):
            try:
                respuesta = self.enviar(b'{"version":1,"comando":"mostrar","display":":0"}\n')
                self.assertEqual(respuesta, b"")
            except ConnectionResetError:
                pass
        self.assertIsNone(self.control.siguiente())

    def test_mostrar_recibe_ack_unicamente_tras_la_respuesta_del_hilo_principal(self):
        respuestas = []
        cliente = threading.Thread(target=lambda: respuestas.append(
            control_interfaz_local.solicitar_mostrar(self.ruta, ":0")))
        cliente.start()
        limite = time.monotonic() + 2
        pedido = None
        while pedido is None and time.monotonic() < limite:
            pedido = self.control.siguiente()
            time.sleep(.005)
        self.assertIsNotNone(pedido)
        self.assertEqual(respuestas, [])
        self.control.responder(pedido, True)
        cliente.join(2)
        self.assertEqual(respuestas, [True])




class PublicadorPausaTests(unittest.TestCase):

    def test_drenaje_espera_observacion_y_nueva_generacion_no_reutiliza_solicitud(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "zones.json"
            token = Path(carpeta) / "token"
            token.write_text("token-sintetico")
            zona = str(uuid4())
            poligono = ((0, 0), (1, 0), (1, 1), (0, 1))
            ruta.write_text(json.dumps({"zones": [{"id": "C1", "vision_zone_id": zona, "polygon": poligono}]}))
            env = {"VISION_JAVA_URL": "http://127.0.0.1:8080", "VISION_FUENTE_ID": str(uuid4()),
                   "VISION_TOKEN_ARCHIVO": str(token)}
            config = cargar_configuracion(ruta, [SimpleNamespace(identifier="C1", polygon=poligono)], env)
            iniciado = threading.Event()
            liberar = threading.Event()
            sesiones = []
            def post(ruta_api, cuerpo):
                if ruta_api.endswith("sesiones"):
                    sesiones.append(cuerpo)
                    return 200, json.dumps({"sesionId": str(uuid4())}).encode()
                iniciado.set()
                liberar.wait(2)
                return 200, b"{}"
            muestra = [SimpleNamespace(snapshot=SimpleNamespace(identifier="C1"), efectivo="LIBRE")]
            primero = PublicadorVision(config)
            primero._post = post
            primero.iniciar()
            primero.ofrecer(muestra)
            self.assertTrue(iniciado.wait(2))
            resultados = []
            pausa = threading.Thread(target=lambda: resultados.append(primero.detener()))
            pausa.start()
            time.sleep(.05)
            self.assertTrue(pausa.is_alive())
            liberar.set()
            pausa.join(3)
            self.assertEqual(resultados, [True])
            segundo = PublicadorVision(config)
            segundo._post = post
            segundo.iniciar()
            segundo.ofrecer(muestra)
            limite = time.monotonic() + 2
            while len(sesiones) < 2 and time.monotonic() < limite:
                time.sleep(.01)
            self.assertTrue(segundo.detener())
            self.assertEqual(len(sesiones), 2)
            self.assertNotEqual(sesiones[0]["solicitudId"], sesiones[1]["solicitudId"])
            self.assertGreater(sesiones[1]["iniciadaEn"], sesiones[0]["iniciadaEn"])



class VidaRuntimeTests(unittest.TestCase):
    def test_staging_pendiente_y_sidecar_invalido_no_modifican_par_ni_publican(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "zones.json"
            crear_calibracion(ruta)
            sidecar = ruta_vinculo(ruta)
            datos_zonas = json.loads(ruta.read_text())
            datos_zonas["metadata"].pop("fuente_sha256", None)
            ruta.write_text(json.dumps(datos_zonas))
            invalido = b'{"version":1,"fuente_sha256":"incorrecto","ancho":640,"alto":360}'
            sidecar.write_bytes(invalido)
            zonas_originales = ruta.read_bytes()
            etapa = ruta.parent / ".vision-activacion-sintetica"
            etapa.mkdir(mode=0o700)
            token = ruta.parent / "token"
            token.write_text("token-sintetico")
            args = argparse.Namespace(image=None, simulation_dir=None, source="http", http_url=FUENTE,
                                      device=None, zones=ruta, model=Path("modelo.pt"), headless=True,
                                      permanente=True, control_socket=Path(carpeta) / "control.sock",
                                      local_proposal=ruta, local_desktop=False, publish_java=True,
                                      imgsz=64, conf=.3, max_frame_age=2)
            class Control:
                def __init__(self, _ruta): pass
                def iniciar(self): pass
                def siguiente(self): return None
                def cerrar(self): pass
            class Captura:
                def __init__(self, *_args): self.n = 0
                def iniciar(self): pass
                def esperar(self, *_args):
                    self.n += 1
                    if self.n > 1: raise KeyboardInterrupt()
                    return SimpleNamespace(revision=1, estado="conectada", cuadro=np.full((ALTO, ANCHO, 3), 100,
                                                                                         dtype=np.uint8),
                                           momento=time.monotonic(), generacion=1, backend="sintetico")
                def detener(self): return True
            entorno = {"VISION_JAVA_URL": "http://127.0.0.1:8080", "VISION_FUENTE_ID": str(uuid4()),
                       "VISION_TOKEN_ARCHIVO": str(token)}
            with patch.dict(os.environ, entorno), \
                 patch.object(control_interfaz_local, "ControlInterfaz", Control), \
                 patch.object(detect, "CapturadorReciente", Captura), \
                 patch.object(detect, "load_model_from_path", return_value=object()), \
                 patch.object(detect, "PublicadorVision") as publicador, \
                 patch.object(detect, "inferir") as inferir:
                self.assertEqual(detect.run(args), 0)
            self.assertEqual(sidecar.read_bytes(), invalido)
            self.assertEqual(ruta.read_bytes(), zonas_originales)
            self.assertTrue(etapa.is_dir())
            publicador.assert_not_called()
            inferir.assert_not_called()

    def test_headless_mostrar_repetido_cerrar_y_reabrir_con_proceso_unico(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "zones.json"
            crear_calibracion(ruta)
            args = argparse.Namespace(image=None, simulation_dir=None, source="http", http_url=FUENTE,
                                      device=None, zones=ruta, model=Path("modelo.pt"), headless=True,
                                      permanente=True, control_socket=Path(carpeta) / "control.sock",
                                      local_proposal=ruta, local_desktop=False, publish_java=False,
                                      imgsz=64, conf=.3, max_frame_age=2)
            eventos = []
            class Control:
                def __init__(self, _ruta): self.n = 0
                def iniciar(self): eventos.append("control")
                def siguiente(self):
                    self.n += 1
                    if self.n in (2, 3, 5):
                        return {"display": ":0", "cancelado": threading.Event()}
                    return None
                def responder(self, _pedido, aceptado): eventos.append(("ack", aceptado))
                def cerrar(self): eventos.append("control-cerrado")
            class Captura:
                def __init__(self, *_args): self.n = 0; eventos.append("captura")
                def iniciar(self): eventos.append("inicio-captura")
                def esperar(self, *_args):
                    self.n += 1
                    if self.n == 8: raise KeyboardInterrupt()
                    return SimpleNamespace(revision=self.n, estado="interrumpida", cuadro=None,
                                           momento=None, generacion=0)
                def detener(self): eventos.append("fin-captura"); return True
            teclas = iter([255, 255, ord("q"), 255, ord("x")])
            def ventana(*_args): eventos.append(("ventana", threading.get_ident()))
            hilo_principal = threading.get_ident()
            with patch.object(control_interfaz_local, "ControlInterfaz", Control), \
                 patch.object(detect, "CapturadorReciente", Captura), \
                 patch.object(detect, "probar_grafica_aislada", return_value=True), \
                 patch.object(detect, "load_model_from_path", return_value=object()) as modelo, \
                 patch.object(detect.cv2, "namedWindow", side_effect=ventana), \
                 patch.object(detect.cv2, "resizeWindow"), patch.object(detect.cv2, "setMouseCallback"), \
                 patch.object(detect.cv2, "imshow"), patch.object(detect.cv2, "waitKey", side_effect=lambda _: next(teclas)), \
                 patch.object(detect.cv2, "destroyWindow"), patch.object(detect.cv2, "destroyAllWindows"), \
                 patch.object(detect, "ventana_cerrada", return_value=False):
                self.assertEqual(detect.run(args), 0)
            self.assertEqual(eventos.count("captura"), 1)
            self.assertEqual(eventos.count("inicio-captura"), 1)
            self.assertEqual(eventos.count("fin-captura"), 1)
            self.assertEqual(modelo.call_count, 1)
            self.assertEqual([e for e in eventos if isinstance(e, tuple) and e[0] == "ventana"],
                             [("ventana", hilo_principal), ("ventana", hilo_principal)])
            self.assertEqual([e for e in eventos if isinstance(e, tuple) and e[0] == "ack"],
                             [("ack", True)] * 3)


if __name__ == "__main__":
    unittest.main()
