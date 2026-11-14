"""Pruebas del contrato y aislamiento del publicador de Vision."""

import json
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from publicador_java import PublicadorVision, cargar_configuracion


class PublicadorTests(unittest.TestCase):
    def setUp(self):
        self.directorio = tempfile.TemporaryDirectory()
        self.addCleanup(self.directorio.cleanup)
        carpeta = Path(self.directorio.name)
        self.ruta = carpeta / "zones.json"
        self.token = carpeta / "token"
        self.token.write_text("secreto-de-prueba-no-real", encoding="utf-8")
        self.zona_id = str(uuid4())
        self.poligono = ((0, 0), (1, 0), (1, 1), (0, 1))
        self.datos = {"zones": [{"id": "C1", "vision_zone_id": self.zona_id,
                                 "polygon": self.poligono}]}
        self.ruta.write_text(json.dumps(self.datos), encoding="utf-8")
        self.zonas = [SimpleNamespace(identifier="C1", polygon=self.poligono)]
        self.entorno = {"VISION_JAVA_URL": "http://127.0.0.1:8080",
                        "VISION_FUENTE_ID": str(uuid4()),
                        "VISION_TOKEN_ARCHIVO": str(self.token)}

    def configuracion(self):
        return cargar_configuracion(self.ruta, self.zonas, self.entorno)

    def muestra(self, estado):
        return [SimpleNamespace(snapshot=SimpleNamespace(identifier="C1"), efectivo=estado)]

    def publicador(self, post):
        publicador = PublicadorVision(self.configuracion())
        publicador._post = post
        publicador.iniciar()
        self.addCleanup(publicador.detener)
        return publicador

    def test_sin_configuracion_no_altera_modo_autonomo(self):
        self.assertIsNone(cargar_configuracion(self.ruta, self.zonas, {}))
        with self.assertRaises(ValueError):
            cargar_configuracion(self.ruta, self.zonas, {"VISION_JAVA_URL": "http://localhost"})

    def test_configuracion_requiere_uuid_estable_y_no_revela_token(self):
        config = self.configuracion()
        self.assertNotIn("secreto-de-prueba-no-real", repr(config))
        self.assertEqual(config.identidades, {"C1": self.zona_id})
        del self.datos["zones"][0]["vision_zone_id"]
        self.ruta.write_text(json.dumps(self.datos), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.configuracion()

    def test_origen_sin_credenciales_y_http_privado_explicito(self):
        self.entorno["VISION_JAVA_URL"] = "http://user:password@api:8080"
        with self.assertRaises(ValueError):
            self.configuracion()
        self.entorno["VISION_JAVA_URL"] = "http://api:8080"
        with self.assertRaises(ValueError):
            self.configuracion()
        self.entorno["VISION_JAVA_HTTP_PRIVADO"] = "1"
        self.assertEqual(self.configuracion().url, "http://api:8080")

    def test_publica_solo_muestra_completa_y_verificable(self):
        recibido = threading.Event()
        llamadas = []
        sesion = str(uuid4())
        def post(ruta, cuerpo):
            llamadas.append((ruta, cuerpo))
            if ruta.endswith("sesiones"):
                return 200, json.dumps({"sesionId": sesion}).encode()
            recibido.set()
            return 200, b"{}"
        publicador = self.publicador(post)
        publicador.ofrecer(self.muestra("NO_VERIFICABLE"))
        self.assertFalse(recibido.wait(0.1))
        self.assertEqual(llamadas, [])
        publicador.ofrecer(self.muestra("OCUPADO"))
        self.assertTrue(recibido.wait(2))
        cuerpo = llamadas[-1][1]
        self.assertEqual(cuerpo["sesionId"], sesion)
        self.assertEqual(cuerpo["secuencia"], 1)
        self.assertNotIn("revisionCalibracion", cuerpo)
        self.assertNotIn("hashCalibracion", cuerpo)
        self.assertEqual(cuerpo["zonas"], [{"visionZoneId": self.zona_id, "estado": "OCUPADO"}])
        self.assertNotIn("secreto-de-prueba-no-real", json.dumps(cuerpo))
        self.assertNotIn("polygon", json.dumps(cuerpo))

    def test_reintento_identico_no_renueva_fecha_ni_solicitud(self):
        recibido = threading.Event()
        observaciones = []
        def post(ruta, cuerpo):
            if ruta.endswith("sesiones"):
                return 200, json.dumps({"sesionId": str(uuid4())}).encode()
            observaciones.append(cuerpo)
            if len(observaciones) == 1:
                return 503, b""
            recibido.set()
            return 200, b"{}"
        publicador = self.publicador(post)
        fecha_captura = datetime.now(timezone.utc) - timedelta(seconds=1)
        publicador.ofrecer(self.muestra("LIBRE"), observado_en=fecha_captura,
                           momento_observacion=time.monotonic() - 1)
        self.assertTrue(recibido.wait(2))
        self.assertEqual(observaciones[0], observaciones[1])
        self.assertEqual(observaciones[0]["observadoEn"],
                         fecha_captura.isoformat().replace("+00:00", "Z"))

    def test_descarta_muestra_envejecida_desde_captura(self):
        recibido = threading.Event()
        llamadas = []
        def post(ruta, cuerpo):
            llamadas.append(ruta)
            if ruta.endswith("sesiones"):
                return 200, json.dumps({"sesionId": str(uuid4())}).encode()
            recibido.set()
            return 200, b"{}"
        publicador = self.publicador(post)
        publicador.ofrecer(self.muestra("OCUPADO"),
                           observado_en=datetime.now(timezone.utc) - timedelta(seconds=11),
                           momento_observacion=time.monotonic() - 11)
        self.assertFalse(recibido.wait(0.2))
        self.assertEqual(llamadas, [])
        publicador.ofrecer(self.muestra("LIBRE"))
        self.assertTrue(recibido.wait(2))

    def test_fallo_obsoleto_no_se_repite_tras_nueva_muestra(self):
        inicio = threading.Event()
        liberar = threading.Event()
        final = threading.Event()
        observaciones = []
        def post(ruta, cuerpo):
            if ruta.endswith("sesiones"):
                return 200, json.dumps({"sesionId": str(uuid4())}).encode()
            observaciones.append(cuerpo)
            if len(observaciones) == 1:
                inicio.set()
                liberar.wait(2)
                return 503, b""
            final.set()
            return 200, b"{}"
        publicador = self.publicador(post)
        publicador.ofrecer(self.muestra("OCUPADO"))
        self.assertTrue(inicio.wait(2))
        publicador.ofrecer(self.muestra("LIBRE"))
        liberar.set()
        self.assertTrue(final.wait(3))
        self.assertEqual([v["zonas"][0]["estado"] for v in observaciones], ["OCUPADO", "LIBRE"])
        self.assertGreater(observaciones[1]["secuencia"], observaciones[0]["secuencia"])

    def test_invalidar_cancela_reintento_y_exige_muestra_nueva(self):
        inicio = threading.Event()
        liberar = threading.Event()
        observaciones = []
        def post(ruta, cuerpo):
            if ruta.endswith("sesiones"):
                return 200, json.dumps({"sesionId": str(uuid4())}).encode()
            observaciones.append(cuerpo)
            inicio.set()
            liberar.wait(2)
            return 503, b""
        publicador = self.publicador(post)
        publicador.ofrecer(self.muestra("OCUPADO"))
        self.assertTrue(inicio.wait(2))
        publicador.invalidar()
        liberar.set()
        time.sleep(0.5)
        self.assertEqual(len(observaciones), 1)

    def test_sesion_desplazada_no_reabre_automaticamente(self):
        rechazado = threading.Event()
        llamadas = []
        def post(ruta, cuerpo):
            llamadas.append(ruta)
            if ruta.endswith("sesiones"):
                return 200, json.dumps({"sesionId": str(uuid4())}).encode()
            rechazado.set()
            return 409, b""
        publicador = self.publicador(post)
        publicador.ofrecer(self.muestra("OCUPADO"))
        self.assertTrue(rechazado.wait(2))
        publicador._hilo.join(2)
        publicador.ofrecer(self.muestra("LIBRE"))
        self.assertEqual(sum(ruta.endswith("sesiones") for ruta in llamadas), 1)
        self.assertFalse(publicador._hilo.is_alive())

    def test_calibracion_modificada_no_bloquea_publicacion_por_hash(self):
        recibido = threading.Event()
        llamadas = []
        def post(ruta, _cuerpo):
            llamadas.append(ruta)
            if ruta.endswith("sesiones"):
                return 200, json.dumps({"sesionId": str(uuid4())}).encode()
            recibido.set()
            return 200, b"{}"
        publicador = self.publicador(post)
        self.ruta.write_text(self.ruta.read_text() + " ", encoding="utf-8")
        publicador.ofrecer(self.muestra("OCUPADO"))
        self.assertTrue(recibido.wait(2))
        self.assertEqual(len(llamadas), 2)

    def test_reintentos_de_apertura_conservan_solicitud(self):
        recibido = threading.Event()
        aperturas = []
        def post(ruta, cuerpo):
            if ruta.endswith("sesiones"):
                aperturas.append(cuerpo.copy())
                return ((503, b"") if len(aperturas) == 1
                        else (200, json.dumps({"sesionId": str(uuid4())}).encode()))
            recibido.set()
            return 200, b"{}"
        inicio = datetime(2026, 11, 2, 12, 30, tzinfo=timezone.utc)
        publicador = PublicadorVision(self.configuracion(), iniciada_en=inicio)
        publicador._post = post
        publicador.iniciar()
        self.addCleanup(publicador.detener)
        publicador.ofrecer(self.muestra("LIBRE"))
        self.assertTrue(recibido.wait(2))
        self.assertEqual(aperturas[0], aperturas[1])
        self.assertEqual(aperturas[0]["iniciadaEn"], "2026-11-02T12:30:00Z")

    def test_interrupcion_detiene_reintentos_de_apertura_hasta_nueva_observacion(self):
        iniciado = threading.Event()
        liberar = threading.Event()
        aperturas = []
        def post(ruta, cuerpo):
            aperturas.append(cuerpo)
            iniciado.set()
            liberar.wait(2)
            return 503, b""
        publicador = self.publicador(post)
        publicador.ofrecer(self.muestra("OCUPADO"))
        self.assertTrue(iniciado.wait(2))
        publicador.invalidar()
        liberar.set()
        time.sleep(0.6)
        self.assertEqual(len(aperturas), 1)

    def test_http_real_envia_bearer_y_transiciones_sin_incluirlo_en_payload(self):
        observaciones = []
        cabeceras = []
        llegada = threading.Event()
        sesion = str(uuid4())
        class Manejador(BaseHTTPRequestHandler):
            def log_message(self, formato, *args):
                pass

            def do_POST(self):
                cuerpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                cabeceras.append(self.headers.get("Authorization"))
                if self.path.endswith("sesiones"):
                    respuesta = json.dumps({"sesionId": sesion}).encode()
                else:
                    observaciones.append(cuerpo)
                    if len(observaciones) == 2:
                        llegada.set()
                    respuesta = b"{}"
                self.send_response(200)
                self.send_header("Content-Length", str(len(respuesta)))
                self.end_headers()
                self.wfile.write(respuesta)

        servidor = ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
        hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
        hilo.start()
        self.addCleanup(servidor.server_close)
        self.addCleanup(servidor.shutdown)
        self.entorno["VISION_JAVA_URL"] = f"http://127.0.0.1:{servidor.server_port}"
        publicador = PublicadorVision(self.configuracion())
        publicador.iniciar()
        self.addCleanup(publicador.detener)
        publicador.ofrecer(self.muestra("OCUPADO"))
        limite = time.monotonic() + 2
        while not observaciones and time.monotonic() < limite:
            time.sleep(0.01)
        self.assertEqual(len(observaciones), 1)
        publicador.ofrecer(self.muestra("LIBRE"))
        self.assertTrue(llegada.wait(3))
        self.assertEqual([item["secuencia"] for item in observaciones], [1, 2])
        self.assertEqual([item["zonas"][0]["estado"] for item in observaciones], ["OCUPADO", "LIBRE"])
        self.assertTrue(all(valor == "Bearer secreto-de-prueba-no-real" for valor in cabeceras))
        self.assertNotIn("secreto-de-prueba-no-real", json.dumps(observaciones))

    def test_put_y_get_calibracion_envian_mapa_completo_con_bearer(self):
        solicitudes = []
        cajon = str(uuid4())
        clase = self

        class Manejador(BaseHTTPRequestHandler):
            def log_message(self, formato, *args):
                pass

            def do_PUT(self):
                cuerpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                solicitudes.append(("PUT", self.path, self.headers.get("Authorization"), cuerpo))
                self.send_response(204)
                self.end_headers()

            def do_GET(self):
                solicitudes.append(("GET", self.path, self.headers.get("Authorization"), None))
                cuerpo = json.dumps({
                    "fuenteId": clase.entorno["VISION_FUENTE_ID"],
                    "zonas": [{
                        "visionZoneId": clase.zona_id,
                        "etiqueta": "C1",
                        "cajonId": cajon,
                    }],
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(cuerpo)))
                self.end_headers()
                self.wfile.write(cuerpo)

        servidor = ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
        hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
        hilo.start()
        self.addCleanup(servidor.server_close)
        self.addCleanup(servidor.shutdown)
        self.entorno["VISION_JAVA_URL"] = f"http://127.0.0.1:{servidor.server_port}"
        publicador = PublicadorVision(self.configuracion())
        payload = [{
            "visionZoneId": self.zona_id,
            "etiqueta": "C1",
            "cajonId": None,
        }]

        self.assertEqual(publicador.activar_calibracion(payload), 204)
        respuesta = publicador.consultar_calibracion()

        ruta = f"/api/v1/vision/fuentes/{self.entorno['VISION_FUENTE_ID']}/calibracion"
        self.assertEqual(respuesta["zonas"][0]["cajonId"], cajon)
        self.assertEqual([solicitud[0] for solicitud in solicitudes], ["PUT", "GET"])
        self.assertTrue(all(solicitud[1] == ruta for solicitud in solicitudes))
        self.assertTrue(all(
            solicitud[2] == "Bearer secreto-de-prueba-no-real" for solicitud in solicitudes
        ))
        self.assertEqual(solicitudes[0][3], {"zonas": payload})


if __name__ == "__main__":
    unittest.main()
