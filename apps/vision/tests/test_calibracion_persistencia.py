"""Pruebas de respaldo, vinculos y round-trip de calibracion."""

import copy
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import calibrar_zonas
import configuracion_local

from soporte_calibracion_zonas import (
    CalibracionZonas,
    CUADRILATERO,
    ControlRaton,
    PENTAGONO,
    TRIANGULO,
    _procesar_tecla,
    crear_zona,
    guardar_calibracion,
    guardar_vinculo,
    identidad_fuente,
    respaldar_calibracion,
    verificar_vinculo,
    config_dinamica,
    cargar_calibracion,
    load_zones,
)


class PersistenciaCalibracionTests(unittest.TestCase):
    def test_guardar_conserva_respaldo_privado_y_recuperable_sin_colisiones(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta = Path(directorio) / "zones.json"
            imagen = Path(directorio) / "imagen.png"
            imagen.write_bytes(b"imagen de referencia")
            calibracion = CalibracionZonas(100, 100)
            crear_zona(calibracion)
            guardar_calibracion(ruta, calibracion, "image")
            guardar_vinculo(ruta, "image", imagen, 100, 100)
            vinculo = ruta.with_name("zones.json.fuente.json")
            zonas_anteriores = ruta.read_bytes()
            fuente_anterior = vinculo.read_bytes()
            identidad_original = calibracion.vision_zone_ids["C1"]
            crear_zona(calibracion, ((5, 5), (20, 5), (12, 20)))
            control = ControlRaton(calibracion)
            _procesar_tecla(ord("s"), calibracion, control, ruta, "image", imagen)
            respaldos = list((ruta.parent / "respaldos").iterdir())
            self.assertEqual(len(respaldos), 1)
            self.assertEqual((respaldos[0] / ruta.name).read_bytes(), zonas_anteriores)
            self.assertEqual((respaldos[0] / vinculo.name).read_bytes(), fuente_anterior)
            verificar_vinculo(respaldos[0] / ruta.name, "image", imagen, 100, 100)
            self.assertEqual((respaldos[0].stat().st_mode & 0o777), 0o700)
            self.assertEqual(((respaldos[0] / ruta.name).stat().st_mode & 0o777), 0o600)
            actual = cargar_calibracion(ruta, 100, 100)
            self.assertEqual(tuple(actual.zonas), ("C1", "C2"))
            self.assertEqual(actual.vision_zone_ids["C1"], identidad_original)
            zonas_antes_del_segundo = ruta.read_bytes()
            fuente_antes_del_segundo = vinculo.read_bytes()
            _procesar_tecla(ord("s"), calibracion, control, ruta, "image", imagen)
            segundos_respaldos = set((ruta.parent / "respaldos").iterdir())
            self.assertEqual(len(segundos_respaldos), 2)
            segundo = (segundos_respaldos - {respaldos[0]}).pop()
            self.assertEqual((segundo / ruta.name).read_bytes(), zonas_antes_del_segundo)
            self.assertEqual((segundo / vinculo.name).read_bytes(), fuente_antes_del_segundo)
            verificar_vinculo(segundo / ruta.name, "image", imagen, 100, 100)
            self.assertEqual((respaldos[0] / ruta.name).read_bytes(), zonas_anteriores)

    def test_guardar_no_reemplaza_si_falta_vinculo_o_falla_respaldo(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta = Path(directorio) / "zones.json"
            imagen = Path(directorio) / "imagen.png"
            imagen.write_bytes(b"imagen de referencia")
            calibracion = CalibracionZonas(100, 100)
            crear_zona(calibracion)
            guardar_calibracion(ruta, calibracion, "image")
            anterior = ruta.read_bytes()
            control = ControlRaton(calibracion)
            _procesar_tecla(ord("s"), calibracion, control, ruta, "image", imagen)
            self.assertEqual(ruta.read_bytes(), anterior)
            self.assertIn("incompleta", control.mensaje)
            guardar_vinculo(ruta, "image", imagen, 100, 100)
            vinculo = ruta.with_name("zones.json.fuente.json")
            fuente = vinculo.read_bytes()
            aceptada, _ = calibracion.mover_vertice("C1", 2, 50, 70)
            self.assertTrue(aceptada)
            with patch("configuracion_local._respaldar_calibracion_bajo_guardado", side_effect=OSError("fallo simulado")):
                _procesar_tecla(ord("s"), calibracion, control, ruta, "image", imagen)
            self.assertEqual(ruta.read_bytes(), anterior)
            self.assertEqual(vinculo.read_bytes(), fuente)
            self.assertIn("No se guardo", control.mensaje)

    def test_respaldo_rechaza_un_vinculo_inconsistente_sin_modificar_archivos(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta = Path(directorio) / "zones.json"
            calibracion = CalibracionZonas(100, 100)
            crear_zona(calibracion)
            guardar_calibracion(ruta, calibracion, "image")
            imagen = Path(directorio) / "imagen.png"
            imagen.write_bytes(b"imagen de referencia")
            guardar_vinculo(ruta, "image", imagen, 100, 100)
            datos = json.loads(ruta.with_name("zones.json.fuente.json").read_text())
            datos["fuente_sha256"] = "fuente-distinta"
            ruta.with_name("zones.json.fuente.json").write_text(json.dumps(datos))
            alterado = ruta.with_name("zones.json.fuente.json").read_bytes()
            zonas_anteriores = ruta.read_bytes()
            with self.assertRaises(ValueError):
                respaldar_calibracion(ruta)
            self.assertEqual(ruta.read_bytes(), zonas_anteriores)
            self.assertEqual(ruta.with_name("zones.json.fuente.json").read_bytes(), alterado)
            self.assertFalse((ruta.parent / "respaldos").exists())

    def test_respaldo_http_no_guarda_la_url_privada(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta = Path(directorio) / "zones.json"
            calibracion = CalibracionZonas(100, 100)
            crear_zona(calibracion)
            guardar_calibracion(ruta, calibracion, "http")
            url = "http://127.0.0.1:4747/video?camara=privada"
            guardar_vinculo(ruta, "http", url, 100, 100)
            respaldo = respaldar_calibracion(ruta, tipo="http", fuente=url, ancho=100, alto=100)
            self.assertNotIn(url.encode(), (respaldo / "zones.json.fuente.json").read_bytes())
            verificar_vinculo(respaldo / ruta.name, "http", url, 100, 100)

    def test_respaldo_legacy_exige_fuente_verificable_y_preserva_el_par(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta = Path(directorio) / "zones.json"
            imagen = Path(directorio) / "imagen.png"
            imagen.write_bytes(b"referencia")
            calibracion = CalibracionZonas(100, 100)
            crear_zona(calibracion)
            guardar_calibracion(ruta, calibracion, "image")
            guardar_vinculo(ruta, "image", imagen, 100, 100)
            vinculo = ruta.with_name("zones.json.fuente.json")
            zonas_anteriores = ruta.read_bytes()
            vinculo_anterior = vinculo.read_bytes()
            self.assertNotIn("fuente_sha256", json.loads(zonas_anteriores)["metadata"])

            with self.assertRaises(ValueError):
                respaldar_calibracion(ruta)
            self.assertEqual(ruta.read_bytes(), zonas_anteriores)
            self.assertEqual(vinculo.read_bytes(), vinculo_anterior)
            self.assertFalse((ruta.parent / "respaldos").exists())

            otra = Path(directorio) / "otra.png"
            otra.write_bytes(b"otra referencia")
            for fuente, ancho in ((otra, 100), (imagen, 101)):
                with self.subTest(fuente=fuente.name, ancho=ancho):
                    with self.assertRaises(ValueError):
                        respaldar_calibracion(ruta, tipo="image", fuente=fuente,
                                              ancho=ancho, alto=100)
                    self.assertEqual(ruta.read_bytes(), zonas_anteriores)
                    self.assertEqual(vinculo.read_bytes(), vinculo_anterior)
                    self.assertFalse((ruta.parent / "respaldos").exists())

            respaldo = respaldar_calibracion(ruta, tipo="image", fuente=imagen,
                                              ancho=100, alto=100)
            self.assertEqual((respaldo / ruta.name).read_bytes(), zonas_anteriores)
            self.assertEqual((respaldo / vinculo.name).read_bytes(), vinculo_anterior)
            verificar_vinculo(respaldo / ruta.name, "image", imagen, 100, 100)

    def test_respaldo_rechaza_hashes_y_dimensiones_inconsistentes(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta = Path(directorio) / "zones.json"
            imagen = Path(directorio) / "imagen.png"
            imagen.write_bytes(b"referencia")
            calibracion = CalibracionZonas(100, 100)
            crear_zona(calibracion)
            calibracion.metadata["fuente_sha256"] = identidad_fuente("image", imagen)
            guardar_calibracion(ruta, calibracion, "image")
            guardar_vinculo(ruta, "image", imagen, 100, 100)
            vinculo = ruta.with_name("zones.json.fuente.json")
            zonas_anteriores = ruta.read_bytes()
            valido = json.loads(vinculo.read_text(encoding="utf-8"))
            casos = (
                {"fuente_sha256": "g" * 64},
                {"fuente_sha256": "0" * 64},
                {"ancho": 0},
                {"ancho": True},
                {"version": True},
            )
            for cambio in casos:
                with self.subTest(cambio=cambio):
                    vinculo.write_text(json.dumps({**valido, **cambio}), encoding="utf-8")
                    vinculo_anterior = vinculo.read_bytes()
                    with self.assertRaises(ValueError):
                        respaldar_calibracion(ruta)
                    self.assertEqual(ruta.read_bytes(), zonas_anteriores)
                    self.assertEqual(vinculo.read_bytes(), vinculo_anterior)
                    self.assertFalse((ruta.parent / "respaldos").exists())

            vinculo.write_text(json.dumps(valido), encoding="utf-8")
            respaldo = respaldar_calibracion(ruta)
            self.assertEqual((respaldo / ruta.name).read_bytes(), zonas_anteriores)
            verificar_vinculo(respaldo / ruta.name, "image", imagen, 100, 100)

    def test_respaldo_rechaza_dimensiones_booleanas_del_contexto_y_metadata(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta = Path(directorio) / "zones.json"
            imagen = Path(directorio) / "imagen.png"
            imagen.write_bytes(b"referencia")
            calibracion = CalibracionZonas(2, 2)
            calibracion.metadata["fuente_sha256"] = identidad_fuente("image", imagen)
            guardar_calibracion(ruta, calibracion, "image")
            guardar_vinculo(ruta, "image", imagen, 2, 2)
            vinculo = ruta.with_name("zones.json.fuente.json")
            anterior = ruta.read_bytes()
            vinculo_anterior = vinculo.read_bytes()
            with self.assertRaises(ValueError):
                respaldar_calibracion(ruta, tipo="image", fuente=imagen, ancho=True, alto=2)
            self.assertEqual(ruta.read_bytes(), anterior)
            self.assertEqual(vinculo.read_bytes(), vinculo_anterior)
            self.assertFalse((ruta.parent / "respaldos").exists())

            datos = json.loads(anterior)
            datos["metadata"]["source_width"] = True
            ruta.write_text(json.dumps(datos), encoding="utf-8")
            anterior_invalido = ruta.read_bytes()
            with self.assertRaises(ValueError):
                respaldar_calibracion(ruta)
            self.assertEqual(ruta.read_bytes(), anterior_invalido)
            self.assertEqual(vinculo.read_bytes(), vinculo_anterior)
            self.assertFalse((ruta.parent / "respaldos").exists())

    def test_identidad_image_incluye_ruta_exacta_y_sha256_del_contenido(self):
        with tempfile.TemporaryDirectory() as directorio:
            carpeta = Path(directorio)
            primera = carpeta / "primera.png"
            segunda = carpeta / "segunda.png"
            primera.write_bytes(b"referencia A")
            segunda.write_bytes(b"referencia B")

            identidad_primera = identidad_fuente("image", primera)
            identidad_segunda = identidad_fuente("image", segunda)
            self.assertEqual(len(identidad_primera), 64)
            self.assertNotEqual(identidad_primera, identidad_segunda)

            primera.write_bytes(b"referencia A modificada")
            self.assertNotEqual(identidad_primera, identidad_fuente("image", primera))

    def test_sidecar_v1_exige_ancho_y_alto_exactos(self):
        with tempfile.TemporaryDirectory() as directorio:
            carpeta = Path(directorio)
            ruta = carpeta / "zones.json"
            imagen = carpeta / "referencia.png"
            imagen.write_bytes(b"fixture de referencia local")
            calibracion = CalibracionZonas(100, 100)
            crear_zona(calibracion)
            guardar_calibracion(ruta, calibracion, "image")
            guardar_vinculo(ruta, "image", imagen, 100, 100)

            verificar_vinculo(ruta, "image", imagen, 100, 100)
            with self.assertRaises(ValueError):
                verificar_vinculo(ruta, "image", imagen, 200, 200)

    def test_guardar_omite_revision_y_hashes_de_calibracion(self):
        with tempfile.TemporaryDirectory() as directorio:
            carpeta = Path(directorio)
            ruta = carpeta / "zones.json"
            imagen = carpeta / "referencia.png"
            imagen.write_bytes(b"fixture de referencia local")
            calibracion = CalibracionZonas(100, 100)
            crear_zona(calibracion, CUADRILATERO)
            guardar_calibracion(ruta, calibracion, "image")
            guardar_vinculo(ruta, "image", imagen, 100, 100)
            control = ControlRaton(calibracion)

            zonas_originales = ruta.read_bytes()
            _procesar_tecla(ord("s"), calibracion, control, ruta, "image", imagen)
            guardada_1 = json.loads(ruta.read_text(encoding="utf-8"))
            respaldos_1 = set((carpeta / "respaldos").iterdir())
            self.assertEqual(len(respaldos_1), 1)
            self.assertEqual((next(iter(respaldos_1)) / ruta.name).read_bytes(), zonas_originales)
            self.assertEqual(guardada_1["metadata"]["fuente_sha256"], identidad_fuente("image", imagen))
            for campo in ("revision_calibracion", "calibration_sha256", "geometry_fingerprint"):
                self.assertNotIn(campo, guardada_1["metadata"])

            aceptada, _ = calibracion.mover_vertice("C1", 2, 82, 78)
            self.assertTrue(aceptada)
            zonas_antes_del_cambio = ruta.read_bytes()
            _procesar_tecla(ord("s"), calibracion, control, ruta, "image", imagen)
            guardada_2 = json.loads(ruta.read_text(encoding="utf-8"))
            for campo in ("revision_calibracion", "calibration_sha256", "geometry_fingerprint"):
                self.assertNotIn(campo, guardada_2["metadata"])
            respaldos_2 = set((carpeta / "respaldos").iterdir())
            self.assertEqual(len(respaldos_2), 2)
            self.assertEqual(((respaldos_2 - respaldos_1).pop() / ruta.name).read_bytes(),
                             zonas_antes_del_cambio)
            self.assertNotEqual(guardada_1["zones"], guardada_2["zones"])

            bytes_sin_cambios = ruta.read_bytes()
            _procesar_tecla(ord("s"), calibracion, control, ruta, "image", imagen)
            guardada_3 = json.loads(ruta.read_text(encoding="utf-8"))
            guardada_2["metadata"].pop("created_at_utc")
            guardada_3["metadata"].pop("created_at_utc")
            self.assertEqual(guardada_3, guardada_2)
            respaldos_3 = set((carpeta / "respaldos").iterdir())
            self.assertEqual(len(respaldos_3), 3)
            self.assertEqual(((respaldos_3 - respaldos_2).pop() / ruta.name).read_bytes(),
                             bytes_sin_cambios)

    def test_empty_calibration_round_trips_with_dynamic_schema(self):
        calibracion = CalibracionZonas(1672, 941)
        with tempfile.TemporaryDirectory() as directorio:
            destino = Path(directorio) / "zones.json"
            self.assertEqual(guardar_calibracion(destino, calibracion, "image"), [])
            datos = json.loads(destino.read_text(encoding="utf-8"))
            cargada = cargar_calibracion(destino, 1280, 720)
            temporal = load_zones(destino)

        self.assertEqual(datos["version"], 2)
        self.assertEqual(datos["coordinate_system"], "normalized_0_to_1")
        self.assertEqual(datos["next_c_number"], 1)
        self.assertEqual(datos["zones"], [])
        self.assertEqual(cargada.zonas, {})
        self.assertEqual(cargada.next_c_number, 1)
        self.assertEqual(temporal, ())

    def test_partial_round_trip_preserves_ids_and_normalized_geometry(self):
        calibracion = CalibracionZonas(100, 100)
        crear_zona(calibracion, TRIANGULO)
        crear_zona(calibracion, PENTAGONO)
        with tempfile.TemporaryDirectory() as directorio:
            destino = Path(directorio) / "zones.json"
            guardar_calibracion(destino, calibracion, "image")
            cargada = cargar_calibracion(destino, 100, 100)

        self.assertEqual(tuple(cargada.zonas), ("C1", "C2"))
        self.assertEqual(cargada.next_c_number, 3)
        for identifier in ("C1", "C2"):
            for actual, original in zip(
                cargada.zonas[identifier].polygon,
                calibracion.zonas[identifier].polygon,
            ):
                self.assertAlmostEqual(actual[0], original[0], places=8)
                self.assertAlmostEqual(actual[1], original[1], places=8)

    def test_arbitrary_zone_count_round_trips_without_a_fixed_maximum(self):
        calibracion = CalibracionZonas(1000, 800)
        for fila in range(3):
            for columna in range(4):
                x = 20 + columna * 240
                y = 20 + fila * 240
                crear_zona(
                    calibracion,
                    ((x, y), (x + 150, y), (x + 75, y + 160)),
                )

        with tempfile.TemporaryDirectory() as directorio:
            destino = Path(directorio) / "zones.json"
            guardar_calibracion(destino, calibracion, "image")
            cargada = cargar_calibracion(destino, 1000, 800)

        self.assertEqual(len(cargada.zonas), 12)
        self.assertEqual(tuple(cargada.zonas), tuple(f"C{i}" for i in range(1, 13)))
        self.assertEqual(cargada.next_c_number, 13)


class GuardadoParCalibracionTests(unittest.TestCase):
    def preparar_par(self, directorio):
        carpeta = Path(directorio)
        ruta = carpeta / "zones.json"
        imagen = carpeta / "imagen.png"
        imagen.write_bytes(b"imagen sintetica")
        calibracion = CalibracionZonas(100, 100)
        crear_zona(calibracion)
        guardar_calibracion(ruta, calibracion, "image")
        guardar_vinculo(ruta, "image", imagen, 100, 100)
        vinculo = ruta.with_name("zones.json.fuente.json")
        anteriores = ruta.read_bytes(), vinculo.read_bytes()
        crear_zona(calibracion, ((5, 5), (20, 5), (12, 20)))
        calibracion.cambios_pendientes = True
        return ruta, imagen, calibracion, ControlRaton(calibracion), anteriores

    def test_guardado_concurrente_no_restaura_respaldo_obsoleto(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta, imagen, segundo, control_segundo, anteriores = self.preparar_par(directorio)
            primero = copy.deepcopy(segundo)
            self.assertTrue(primero.mover_vertice("C1", 2, 50, 70)[0])
            control_primero = ControlRaton(primero)
            esperando, continuar, fallo_sidecar = (threading.Event() for _ in range(3))
            errores = []
            iniciar_real = configuracion_local.iniciar_guardado_pendiente
            vinculo_real = calibrar_zonas.guardar_vinculo

            def iniciar(*args, **kwargs):
                if threading.current_thread().name == "segundo-guardado":
                    esperando.set()
                    if not continuar.wait(5):
                        raise RuntimeError("El primer guardado no termino.")
                return iniciar_real(*args, **kwargs)

            def vinculo(*args, **kwargs):
                if threading.current_thread().name == "segundo-guardado":
                    fallo_sidecar.set()
                    raise OSError("fallo concurrente sintetico")
                return vinculo_real(*args, **kwargs)

            def guardar_segundo():
                try:
                    _procesar_tecla(ord("s"), segundo, control_segundo, ruta, "image", imagen)
                except BaseException as error:
                    errores.append(error)

            with patch.object(configuracion_local, "iniciar_guardado_pendiente", side_effect=iniciar), \
                 patch.object(calibrar_zonas, "guardar_vinculo", side_effect=vinculo):
                hilo = threading.Thread(target=guardar_segundo, name="segundo-guardado")
                hilo.start()
                try:
                    self.assertTrue(esperando.wait(5))
                    _procesar_tecla(ord("s"), primero, control_primero, ruta, "image", imagen)
                    confirmado = ruta.read_bytes(), ruta.with_name("zones.json.fuente.json").read_bytes()
                    self.assertNotEqual(confirmado[0], anteriores[0])
                    self.assertIn("Guardadas", control_primero.mensaje)
                finally:
                    continuar.set()
                    hilo.join(5)
            self.assertFalse(hilo.is_alive())
            self.assertEqual(errores, [])
            self.assertTrue(fallo_sidecar.is_set())
            self.assertIn("recupero", control_segundo.mensaje)
            self.assertEqual((ruta.read_bytes(), ruta.with_name("zones.json.fuente.json").read_bytes()), confirmado)

    def test_segundo_escritor_no_retiro_marcador_durante_respaldo(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta, imagen, primero, control_primero, anteriores = self.preparar_par(directorio)
            segundo = copy.deepcopy(primero)
            control_segundo = ControlRaton(segundo)
            preparando, continuar = threading.Event(), threading.Event()
            errores = []
            respaldar_real = configuracion_local._respaldar_calibracion_bajo_guardado

            def respaldar(*args, **kwargs):
                preparando.set()
                if not continuar.wait(5):
                    raise RuntimeError("No se libero el respaldo sintetico.")
                return respaldar_real(*args, **kwargs)

            def guardar_primero():
                try:
                    _procesar_tecla(ord("s"), primero, control_primero, ruta, "image", imagen)
                except BaseException as error:
                    errores.append(error)

            with patch.object(configuracion_local, "_respaldar_calibracion_bajo_guardado", side_effect=respaldar):
                hilo = threading.Thread(target=guardar_primero)
                hilo.start()
                try:
                    self.assertTrue(preparando.wait(5))
                    marcador = ruta.with_name(".zones.json.guardado-pendiente")
                    propio = marcador.read_bytes()
                    self.assertEqual(json.loads(propio)["fase"], "preparacion")
                    _procesar_tecla(ord("s"), segundo, control_segundo, ruta, "image", imagen)
                    self.assertIn("guardado pendiente", control_segundo.mensaje)
                    self.assertEqual(marcador.read_bytes(), propio)
                    self.assertEqual((ruta.read_bytes(), ruta.with_name("zones.json.fuente.json").read_bytes()), anteriores)
                finally:
                    continuar.set()
                    hilo.join(5)
            self.assertFalse(hilo.is_alive())
            self.assertEqual(errores, [])
            self.assertIn("Guardadas", control_primero.mensaje)

    def test_crash_antes_y_despues_de_registrar_respaldo_preserva_el_par(self):
        for fase in ("antes", "durante", "despues"):
            with self.subTest(fase=fase), tempfile.TemporaryDirectory() as directorio:
                ruta, imagen, _, _, anteriores = self.preparar_par(directorio)
                programa = """
import os, sys
from pathlib import Path
import calibrar_zonas, configuracion_local
from calibracion_zonas import cargar_calibracion
ruta, imagen, fase = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
calibracion = cargar_calibracion(ruta, 100, 100)
if fase == "antes":
    configuracion_local._respaldar_calibracion_bajo_guardado = lambda *a, **k: os._exit(76)
else:
    original = configuracion_local._escribir_estado_guardado
    def interrumpir(ruta, guardado, estado, respaldo):
        if estado == "respaldo_listo" and fase == "durante":
            os.ftruncate(guardado.descriptor, 0)
            os.fsync(guardado.descriptor)
            os._exit(78)
        original(ruta, guardado, estado, respaldo)
        if estado == "respaldo_listo":
            os._exit(77)
    configuracion_local._escribir_estado_guardado = interrumpir
calibrar_zonas._procesar_tecla(ord("s"), calibracion,
    calibrar_zonas.ControlRaton(calibracion), ruta, "image", imagen)
"""
                resultado = subprocess.run(
                    [sys.executable, "-c", programa, str(ruta), str(imagen), fase],
                    capture_output=True, text=True, check=False,
                )
                self.assertEqual(resultado.returncode, {"antes": 76, "durante": 78, "despues": 77}[fase], resultado.stderr)
                self.assertEqual((ruta.read_bytes(), ruta.with_name("zones.json.fuente.json").read_bytes()), anteriores)
                contenido_marcador = ruta.with_name(".zones.json.guardado-pendiente").read_text()
                if fase == "durante":
                    self.assertEqual(contenido_marcador, "")
                    with self.assertRaisesRegex(ValueError, "guardado pendiente"):
                        cargar_calibracion(ruta, 100, 100)
                    continue
                marcador = json.loads(contenido_marcador)
                self.assertEqual(marcador["fase"], "preparacion" if fase == "antes" else "respaldo_listo")
                if fase == "antes":
                    self.assertIsNone(marcador["respaldo"])
                else:
                    respaldo = ruta.parent / "respaldos" / marcador["respaldo"]
                    self.assertEqual((respaldo / ruta.name).read_bytes(), anteriores[0])
                    self.assertEqual((respaldo / "zones.json.fuente.json").read_bytes(), anteriores[1])
                with self.assertRaisesRegex(ValueError, "guardado pendiente"):
                    cargar_calibracion(ruta, 100, 100)

    def test_solo_el_propietario_puede_usar_o_retirar_su_marcador(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta, imagen, _, _, anteriores = self.preparar_par(directorio)
            guardado = configuracion_local.iniciar_guardado_pendiente(ruta)
            marcador = ruta.with_name(".zones.json.guardado-pendiente")
            with self.assertRaisesRegex(ValueError, "no posee"):
                configuracion_local._respaldar_calibracion_bajo_guardado(
                    ruta, object(), tipo="image", fuente=imagen, ancho=100, alto=100,
                )
            marcador.unlink()
            marcador.write_bytes(b"marcador de otro escritor")
            with self.assertRaisesRegex(ValueError, "ya no pertenece"):
                configuracion_local.finalizar_guardado_pendiente(ruta, guardado)
            self.assertEqual(marcador.read_bytes(), b"marcador de otro escritor")
            self.assertEqual((ruta.read_bytes(), ruta.with_name("zones.json.fuente.json").read_bytes()), anteriores)
            self.assertFalse((ruta.parent / "respaldos").exists())

    def test_respaldo_sincroniza_archivos_y_directorios_antes_del_registro(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta, imagen, _, _, anteriores = self.preparar_par(directorio)
            sincronizar = configuracion_local._sincronizar_directorio
            fsync_real, sincronizados = os.fsync, []

            def registrar_fsync(descriptor):
                sincronizados.append(Path(os.readlink(f"/proc/self/fd/{descriptor}")))
                return fsync_real(descriptor)

            with patch.object(configuracion_local, "_sincronizar_directorio", wraps=sincronizar) as llamadas, \
                 patch.object(configuracion_local.os, "fsync", side_effect=registrar_fsync):
                guardado, respaldo = configuracion_local.preparar_guardado_calibracion(
                    ruta, tipo="image", fuente=imagen, ancho=100, alto=100,
                )
                try:
                    directorios = [llamada.args[0] for llamada in llamadas.call_args_list]
                    self.assertIn(ruta.parent, directorios)
                    self.assertIn(ruta.parent / "respaldos", directorios)
                    self.assertIn(respaldo, directorios)
                    marcador_ruta = ruta.with_name(".zones.json.guardado-pendiente")
                    registro_final = max(i for i, archivo in enumerate(sincronizados) if archivo == marcador_ruta)
                    for archivo in (respaldo / ruta.name, respaldo / "zones.json.fuente.json", respaldo,
                                    ruta.parent / "respaldos"):
                        self.assertIn(archivo, sincronizados[:registro_final])
                    self.assertEqual((respaldo / ruta.name).read_bytes(), anteriores[0])
                    self.assertEqual((respaldo / "zones.json.fuente.json").read_bytes(), anteriores[1])
                    marcador = json.loads(ruta.with_name(".zones.json.guardado-pendiente").read_text())
                    self.assertEqual(marcador["fase"], "respaldo_listo")
                    self.assertEqual(marcador["respaldo"], respaldo.name)
                finally:
                    configuracion_local.finalizar_guardado_pendiente(ruta, guardado)

    def test_error_sidecar_restaura_ambos_archivos_y_conserva_borrador(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta, imagen, calibracion, control, anteriores = self.preparar_par(directorio)
            metadata = dict(calibracion.metadata)
            with patch("calibrar_zonas.guardar_vinculo", side_effect=OSError("fallo sintetico")):
                _procesar_tecla(ord("s"), calibracion, control, ruta, "image", imagen)
            vinculo = ruta.with_name("zones.json.fuente.json")
            self.assertEqual((ruta.read_bytes(), vinculo.read_bytes()), anteriores)
            self.assertFalse(ruta.with_name(".zones.json.guardado-pendiente").exists())
            self.assertEqual(calibracion.metadata, metadata)
            self.assertTrue(calibracion.cambios_pendientes)
            self.assertEqual(tuple(calibracion.zonas), ("C1", "C2"))
            self.assertIn("No se guardo", control.mensaje)
            respaldos = list((ruta.parent / "respaldos").iterdir())
            self.assertEqual(len(respaldos), 1)
            self.assertEqual((respaldos[0] / ruta.name).read_bytes(), anteriores[0])
            self.assertEqual((respaldos[0] / vinculo.name).read_bytes(), anteriores[1])
            _procesar_tecla(ord("s"), calibracion, control, ruta, "image", imagen)
            self.assertEqual(tuple(cargar_calibracion(ruta, 100, 100).zonas), ("C1", "C2"))
            verificar_vinculo(ruta, "image", imagen, 100, 100)

    def test_sidecar_falla_despues_de_reemplazar_y_se_recupera_el_par(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta, imagen, calibracion, control, anteriores = self.preparar_par(directorio)
            vinculo = ruta.with_name("zones.json.fuente.json")
            datos = json.loads(vinculo.read_text(encoding="utf-8"))
            datos["version"] = 2
            datos["atributo_legacy"] = "conservar"
            vinculo.write_text(json.dumps(datos), encoding="utf-8")
            anteriores = ruta.read_bytes(), vinculo.read_bytes()

            def escribir_y_fallar(*args):
                guardar_vinculo(*args)
                raise OSError("fallo despues de reemplazar")

            with patch("calibrar_zonas.guardar_vinculo", side_effect=escribir_y_fallar):
                _procesar_tecla(ord("s"), calibracion, control, ruta, "image", imagen)
            self.assertEqual((ruta.read_bytes(), ruta.with_name("zones.json.fuente.json").read_bytes()), anteriores)
            self.assertIn("No se guardo", control.mensaje)

    def test_fallo_despues_de_escribir_geometria_restaura_el_par(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta, imagen, calibracion, control, anteriores = self.preparar_par(directorio)

            def escribir_y_fallar(*args):
                guardar_calibracion(*args)
                raise OSError("fallo despues de geometria")

            with patch("calibrar_zonas.guardar_calibracion", side_effect=escribir_y_fallar):
                _procesar_tecla(ord("s"), calibracion, control, ruta, "image", imagen)
            self.assertEqual((ruta.read_bytes(), ruta.with_name("zones.json.fuente.json").read_bytes()), anteriores)
            self.assertIn("No se guardo", control.mensaje)

    def test_primer_guardado_fallido_restaurara_ausencia_de_ambos_archivos(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta = Path(directorio) / "zones.json"
            imagen = Path(directorio) / "imagen.png"
            imagen.write_bytes(b"imagen sintetica")
            calibracion = CalibracionZonas(100, 100)
            crear_zona(calibracion)
            control = ControlRaton(calibracion)
            metadata = dict(calibracion.metadata)

            def escribir_y_fallar(*args):
                guardar_vinculo(*args)
                raise OSError("fallo despues de sidecar")

            with patch("calibrar_zonas.guardar_vinculo", side_effect=escribir_y_fallar):
                _procesar_tecla(ord("s"), calibracion, control, ruta, "image", imagen)
            self.assertFalse(ruta.exists())
            self.assertFalse(ruta.with_name("zones.json.fuente.json").exists())
            self.assertEqual(calibracion.metadata, metadata)
            self.assertIn("No se guardo", control.mensaje)

    def test_verificacion_fallida_despues_de_guardar_restaura_el_par(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta, imagen, calibracion, control, anteriores = self.preparar_par(directorio)
            with patch("calibrar_zonas._sidecar_compatible", return_value=False) as comprobacion:
                _procesar_tecla(ord("s"), calibracion, control, ruta, "image", imagen)
            comprobacion.assert_called_once()
            self.assertEqual((ruta.read_bytes(), ruta.with_name("zones.json.fuente.json").read_bytes()), anteriores)
            self.assertIn("No se guardo", control.mensaje)

    def test_fallo_de_restauracion_detiene_calibrador_y_conserva_respaldo(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta, imagen, calibracion, control, anteriores = self.preparar_par(directorio)
            with patch("calibrar_zonas.guardar_vinculo", side_effect=OSError("fallo escritura")), \
                    patch("calibrar_zonas._restaurar_par_calibracion", side_effect=OSError("fallo restauracion"), create=True):
                with self.assertRaisesRegex(RuntimeError, "No se recupero"):
                    _procesar_tecla(ord("s"), calibracion, control, ruta, "image", imagen)
            respaldos = list((ruta.parent / "respaldos").iterdir())
            self.assertEqual(len(respaldos), 1)
            self.assertEqual((respaldos[0] / ruta.name).read_bytes(), anteriores[0])
            self.assertEqual((respaldos[0] / "zones.json.fuente.json").read_bytes(), anteriores[1])
            self.assertIn("No se recupero", control.mensaje)
            self.assertTrue(ruta.with_name(".zones.json.guardado-pendiente").exists())
            with self.assertRaisesRegex(ValueError, "guardado pendiente"):
                cargar_calibracion(ruta, 100, 100)

    def test_error_real_al_reemplazar_restauracion_deja_marcador_y_respaldo(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta, imagen, calibracion, control, anteriores = self.preparar_par(directorio)
            reemplazar = os.replace

            def fallar_restauracion(origen, destino):
                if ".restaurar-" in Path(origen).name:
                    raise OSError("fallo sintetico de restauracion")
                return reemplazar(origen, destino)

            with patch("calibrar_zonas.guardar_vinculo", side_effect=OSError("fallo de sidecar")), \
                    patch("calibrar_zonas.os.replace", side_effect=fallar_restauracion):
                with self.assertRaisesRegex(RuntimeError, "No se recupero"):
                    _procesar_tecla(ord("s"), calibracion, control, ruta, "image", imagen)
            respaldo = next((ruta.parent / "respaldos").iterdir())
            self.assertEqual((respaldo / ruta.name).read_bytes(), anteriores[0])
            self.assertEqual((respaldo / "zones.json.fuente.json").read_bytes(), anteriores[1])
            self.assertTrue(ruta.with_name(".zones.json.guardado-pendiente").exists())
            with self.assertRaisesRegex(ValueError, "guardado pendiente"):
                load_zones(ruta)

    def test_interrupcion_durante_guardado_restaura_y_se_propaga(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta, imagen, calibracion, control, anteriores = self.preparar_par(directorio)

            def escribir_y_interrumpir(*args):
                guardar_calibracion(*args)
                raise KeyboardInterrupt()

            with patch("calibrar_zonas.guardar_calibracion", side_effect=escribir_y_interrumpir):
                with self.assertRaises(KeyboardInterrupt):
                    _procesar_tecla(ord("s"), calibracion, control, ruta, "image", imagen)
            self.assertEqual((ruta.read_bytes(), ruta.with_name("zones.json.fuente.json").read_bytes()), anteriores)
            self.assertFalse(ruta.with_name(".zones.json.guardado-pendiente").exists())

    def test_fallo_al_cerrar_marcador_deja_el_par_bloqueado_y_respaldo(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta, imagen, calibracion, control, anteriores = self.preparar_par(directorio)
            with patch("calibrar_zonas.finalizar_guardado_pendiente", side_effect=OSError("fallo de cierre")):
                with self.assertRaisesRegex(RuntimeError, "no se pudo cerrar"):
                    _procesar_tecla(ord("s"), calibracion, control, ruta, "image", imagen)
            self.assertTrue(ruta.with_name(".zones.json.guardado-pendiente").is_file())
            with self.assertRaisesRegex(ValueError, "guardado pendiente"):
                load_zones(ruta)
            respaldo = next((ruta.parent / "respaldos").iterdir())
            self.assertEqual((respaldo / ruta.name).read_bytes(), anteriores[0])
            self.assertEqual((respaldo / "zones.json.fuente.json").read_bytes(), anteriores[1])

    def test_fallo_fsync_tras_quitar_marcador_conserva_par_completo(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta, imagen, calibracion, control, _ = self.preparar_par(directorio)

            def quitar_y_fallar(destino, _guardado):
                destino.with_name(".zones.json.guardado-pendiente").unlink()
                raise OSError("fallo sintetico de fsync")

            with patch("calibrar_zonas.finalizar_guardado_pendiente", side_effect=quitar_y_fallar):
                with self.assertRaisesRegex(RuntimeError, "no se pudo cerrar"):
                    _procesar_tecla(ord("s"), calibracion, control, ruta, "image", imagen)
            self.assertFalse(ruta.with_name(".zones.json.guardado-pendiente").exists())
            self.assertEqual(tuple(cargar_calibracion(ruta, 100, 100).zonas), ("C1", "C2"))
            verificar_vinculo(ruta, "image", imagen, 100, 100)

    def test_proceso_terminado_entre_archivos_bloquea_todos_los_lectores(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta, imagen, _, _, anteriores = self.preparar_par(directorio)
            zonas_previas = load_zones(ruta)
            programa = """
import os, sys
from pathlib import Path
import calibrar_zonas
from calibracion_zonas import cargar_calibracion
ruta, imagen = Path(sys.argv[1]), Path(sys.argv[2])
calibracion = cargar_calibracion(ruta, 100, 100)
aceptado, _ = calibracion.mover_vertice("C1", 2, 50, 70)
assert aceptado
calibrar_zonas.guardar_vinculo = lambda *args: os._exit(73)
calibrar_zonas._procesar_tecla(ord("s"), calibracion,
    calibrar_zonas.ControlRaton(calibracion), ruta, "image", imagen)
"""
            resultado = subprocess.run(
                [sys.executable, "-c", programa, str(ruta), str(imagen)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(resultado.returncode, 73, resultado.stderr)
            self.assertNotEqual(ruta.read_bytes(), anteriores[0])
            self.assertEqual(ruta.with_name("zones.json.fuente.json").read_bytes(), anteriores[1])
            marcador = ruta.with_name(".zones.json.guardado-pendiente")
            self.assertTrue(marcador.is_file())
            respaldo = next((ruta.parent / "respaldos").iterdir())
            self.assertEqual((respaldo / ruta.name).read_bytes(), anteriores[0])
            self.assertEqual((respaldo / "zones.json.fuente.json").read_bytes(), anteriores[1])
            self.assertEqual(json.loads(marcador.read_text())["respaldo"], respaldo.name)
            self.assertEqual(marcador.stat().st_mode & 0o777, 0o600)
            with self.assertRaisesRegex(ValueError, "guardado pendiente"):
                verificar_vinculo(ruta, "image", imagen, 100, 100)
            with self.assertRaisesRegex(ValueError, "guardado pendiente"):
                cargar_calibracion(ruta, 100, 100)
            with self.assertRaisesRegex(ValueError, "guardado pendiente"):
                load_zones(ruta)
            with self.assertRaisesRegex(ValueError, "guardado pendiente"):
                respaldar_calibracion(ruta, tipo="image", fuente=imagen, ancho=100, alto=100)
            from aplicacion_local import validar_archivo_local
            from publicador_java import cargar_configuracion
            with self.assertRaisesRegex(ValueError, "guardado pendiente"):
                validar_archivo_local(ruta, "image", imagen, (100, 100), recuperar=False)
            token = Path(directorio) / "token-prueba"
            token.write_text("token-sintetico", encoding="utf-8")
            entorno = {
                "VISION_JAVA_URL": "https://localhost",
                "VISION_FUENTE_ID": "00000000-0000-4000-8000-000000000001",
                "VISION_TOKEN_ARCHIVO": str(token),
            }
            with self.assertRaisesRegex(ValueError, "guardado pendiente"):
                cargar_configuracion(ruta, zonas_previas, entorno)

    def test_primer_guardado_interrumpido_deja_marcador_sin_respaldo(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta = Path(directorio) / "zones.json"
            imagen = Path(directorio) / "imagen.png"
            imagen.write_bytes(b"imagen sintetica")
            programa = """
import os, sys
from pathlib import Path
import calibrar_zonas
from calibracion_zonas import CalibracionZonas
ruta, imagen = Path(sys.argv[1]), Path(sys.argv[2])
calibracion = CalibracionZonas(100, 100)
calibrar_zonas.guardar_vinculo = lambda *args: os._exit(74)
calibrar_zonas._procesar_tecla(ord("s"), calibracion,
    calibrar_zonas.ControlRaton(calibracion), ruta, "image", imagen)
"""
            resultado = subprocess.run(
                [sys.executable, "-c", programa, str(ruta), str(imagen)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(resultado.returncode, 74, resultado.stderr)
            marcador = ruta.with_name(".zones.json.guardado-pendiente")
            self.assertIsNone(json.loads(marcador.read_text())["respaldo"])
            self.assertTrue(ruta.is_file())
            self.assertFalse(ruta.with_name("zones.json.fuente.json").exists())
            with self.assertRaisesRegex(ValueError, "guardado pendiente"):
                load_zones(ruta)
            with self.assertRaisesRegex(ValueError, "guardado pendiente"):
                cargar_calibracion(ruta, 100, 100)

    def test_marcador_existente_no_se_reemplaza_ni_se_borra(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta, imagen, calibracion, control, anteriores = self.preparar_par(directorio)
            marcador = ruta.with_name(".zones.json.guardado-pendiente")
            marcador.write_bytes(b"recuperacion pendiente")
            _procesar_tecla(ord("s"), calibracion, control, ruta, "image", imagen)
            self.assertEqual(marcador.read_bytes(), b"recuperacion pendiente")
            self.assertEqual((ruta.read_bytes(), ruta.with_name("zones.json.fuente.json").read_bytes()), anteriores)
            self.assertIn("guardado pendiente", control.mensaje)


if __name__ == "__main__":
    unittest.main()
