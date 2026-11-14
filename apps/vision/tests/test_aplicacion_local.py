"""Flujos locales con captura, modelo y configuracion sinteticos."""

from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

import aplicacion_local
import capture
import configuracion_local
import detect
from calibracion_zonas import CalibracionZonas, cargar_calibracion, guardar_calibracion
from configuracion_local import guardar_vinculo, identidad_fuente, ruta_vinculo, verificar_vinculo
from temporal_validation import ParkingZone


FUENTE = "http://127.0.0.1:14747/video"
ANCHO, ALTO = 640, 360


def crear_calibracion(ruta):
    zonas = {}
    for indice in range(8):
        columna, fila = indice % 4, indice // 4
        x, y = 30 + columna * 145, 60 + fila * 150
        poligono = tuple((px / (ANCHO - 1), py / (ALTO - 1)) for px, py in (
            (x, y), (x + 110, y), (x + 110, y + 90), (x, y + 90)))
        etiqueta = f"C{indice + 1}"
        zonas[etiqueta] = ParkingZone(etiqueta, poligono)
    calibracion = CalibracionZonas(ANCHO, ALTO, zonas=zonas, next_c_number=9)
    identidad = identidad_fuente("http", FUENTE)
    calibracion.metadata["fuente_sha256"] = identidad
    atributos = {etiqueta: {"cajonId": f"cajon-sintetico-{etiqueta}"} for etiqueta in zonas}
    guardar_calibracion(ruta, calibracion, "http", atributos_por_zona=atributos)
    guardar_vinculo(ruta, "http", FUENTE, ANCHO, ALTO)
    return calibracion


class AplicacionLocalTests(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporal.cleanup)
        self.ruta = Path(self.temporal.name) / "zones.json"
        self.inicial = crear_calibracion(self.ruta)
        self.capturador = capture.CapturadorReciente("http", FUENTE, None)
        self.imagen = np.full((ALTO, ANCHO, 3), 100, dtype=np.uint8)
        self.capturador._publicar(self.imagen, "sintetica", nueva_conexion=True)

    def editor(self):
        return aplicacion_local.EditorLocal(self.ruta, "http", FUENTE, self.capturador.instantanea())

    @staticmethod
    def mover(editor):
        editor.raton(cv2.EVENT_LBUTTONDOWN, 70, 100, 0, None)
        editor.raton(cv2.EVENT_LBUTTONDOWN, 30, 60, 0, None)
        editor.raton(cv2.EVENT_MOUSEMOVE, 35, 63, cv2.EVENT_FLAG_LBUTTON, None)
        editor.raton(cv2.EVENT_LBUTTONUP, 35, 63, 0, None)

    def pulsar_boton(self, editor, etiqueta):
        boton = next(b for b in editor.botones_calibracion() if b[0] == etiqueta)
        _, tecla, (x, y, ancho, alto) = boton
        cola = deque()
        for evento in (cv2.EVENT_LBUTTONDOWN, cv2.EVENT_LBUTTONUP):
            detect._raton_en_marco(editor, evento, x + ancho // 2, y + alto // 2,
                                   0, None, cola)
        self.assertEqual(list(cola), [(editor, tecla)])
        self.assertEqual(detect._tecla_calibracion(255, editor, cola), tecla)
        self.assertFalse(cola)
        return editor.tecla(tecla)

    def test_botones_dibujo_geometria_y_estado_visual(self):
        editor = self.editor()
        original = editor.imagen.copy()
        esperados = (
            ("Nuevo", ord("n"), (654, 180, 112, 32)),
            ("Eliminar", ord("d"), (774, 180, 112, 32)),
            ("Deshacer", ord("z"), (654, 220, 112, 32)),
            ("Propuesta", ord("a"), (774, 220, 112, 32)),
            ("Aceptar", 13, (654, 268, 112, 32)),
            ("Descartar", ord("r"), (774, 268, 112, 32)),
            ("Sincronizar y guardar", ord("s"), (654, 316, 232, 36)),
            ("Cancelar", 27, (654, 360, 232, 32)),
        )
        self.assertEqual(editor.botones_calibracion(), esperados)
        previa = []
        dibujar = aplicacion_local.dibujar_superposicion

        def capturar(*args, **kwargs):
            lienzo = dibujar(*args, **kwargs)
            previa.append(lienzo.copy())
            return lienzo

        with patch.object(aplicacion_local, "dibujar_superposicion", side_effect=capturar), \
             patch.object(cv2, "putText", wraps=cv2.putText) as textos:
            pantalla = editor.pantalla()
        self.assertEqual(pantalla.shape, previa[0].shape)
        self.assertTrue(np.array_equal(editor.imagen, original))
        mascara = np.zeros(pantalla.shape[:2], dtype=bool)
        bordes = {
            ord("n"): (98, 73, 48),
            ord("d"): (60, 56, 96),
            ord("a"): (98, 65, 82),
            13: (48, 48, 48),
            ord("r"): (48, 48, 48),
            ord("s"): (78, 150, 64),
        }
        for etiqueta, tecla, (x, y, ancho, alto) in esperados:
            self.assertLessEqual(x + ancho, ANCHO + 260)
            self.assertLessEqual(y + alto, detect.ALTO_CABECERA + ALTO)
            self.assertEqual(editor.tecla_de_boton(x, y), tecla)
            self.assertEqual(editor.tecla_de_boton(x + ancho - 1, y + alto - 1), tecla)
            self.assertIsNone(editor.tecla_de_boton(x + ancho, y))
            self.assertIsNone(editor.tecla_de_boton(x, y + alto))
            borde = bordes.get(tecla, aplicacion_local.COLOR_SEPARADOR)
            self.assertEqual(tuple(pantalla[y, x]), borde)
            self.assertEqual(tuple(pantalla[y + alto - 1, x + ancho - 1]), borde)
            mascara[y:y + alto, x:x + ancho] = True
        for y in (detect.ALTO_CABECERA + 204, detect.ALTO_CABECERA + 252):
            mascara[y, ANCHO + 14:ANCHO + 246] = True
            self.assertEqual(tuple(pantalla[y, ANCHO + 14]), aplicacion_local.COLOR_SEPARADOR)
        self.assertTrue(np.array_equal(pantalla[~mascara], previa[0][~mascara]))
        llamadas = {c.args[1]: c.args[5] for c in textos.call_args_list
                    if c.args[1] in {b[0] for b in esperados}}
        self.assertEqual(set(llamadas), {b[0] for b in esperados})
        self.assertEqual(llamadas["Aceptar"], aplicacion_local.COLOR_SECUNDARIO)
        self.assertEqual(llamadas["Descartar"], aplicacion_local.COLOR_SECUNDARIO)
        editor.creando_poligono = True
        with patch.object(cv2, "putText", wraps=cv2.putText) as textos:
            editor.pantalla()
        colores = {c.args[1]: c.args[5] for c in textos.call_args_list}
        self.assertEqual(colores["Aceptar"], aplicacion_local.COLOR_PRINCIPAL)
        self.assertEqual(colores["Descartar"], aplicacion_local.COLOR_SECUNDARIO)
        editor.propuesta = copy.deepcopy(editor.borrador)
        with patch.object(cv2, "putText", wraps=cv2.putText) as textos:
            editor.pantalla()
        colores = {c.args[1]: c.args[5] for c in textos.call_args_list}
        self.assertEqual(colores["Aceptar"], aplicacion_local.COLOR_PRINCIPAL)
        self.assertEqual(colores["Descartar"], aplicacion_local.COLOR_PRINCIPAL)

    def test_botones_equivalen_atajos_y_prioridad_de_entrada(self):
        def preparar(editor, contexto):
            if contexto == "seleccion":
                editor.borrador.seleccionar_zona("C1")
            elif contexto == "historial":
                self.mover(editor)
            elif contexto == "propuesta":
                editor.propuesta = copy.deepcopy(editor.borrador)
                editor.propuesta.mover_vertice("C1", 0, 35, 63)
            elif contexto in ("creacion", "incompleta"):
                editor.tecla(ord("n"))
                puntos = [(500, 200), (560, 200), (560, 260), (500, 260)]
                for x, y in puntos[:1 if contexto == "incompleta" else 4]:
                    editor.raton(cv2.EVENT_LBUTTONDOWN, x, y, 0, None)

        def estado(editor):
            return (
                {k: z.polygon for k, z in editor.borrador.zonas.items()},
                {k: v for k, v in editor.borrador.vision_zone_ids.items() if k != "C9"},
                editor.borrador.id_seleccionado, list(editor.borrador.puntos_pendientes),
                editor.borrador.next_c_number, editor.creando_poligono,
                None if editor.propuesta is None else
                {k: z.polygon for k, z in editor.propuesta.zonas.items()},
                len(editor.historial), editor.control.mensaje,
            )

        def candidato(_imagen, borrador):
            propuesta = copy.deepcopy(borrador)
            propuesta.mover_vertice("C1", 0, 35, 63)
            return argparse.Namespace(calibracion=propuesta)

        casos = (
            ("Nuevo", "normal", ord("N")),
            ("Eliminar", "seleccion", ord("D")),
            ("Deshacer", "historial", ord("Z")),
            ("Propuesta", "normal", ord("A")),
            ("Aceptar", "propuesta", 10),
            ("Aceptar", "creacion", 13),
            ("Aceptar", "incompleta", 10),
            ("Descartar", "propuesta", ord("R")),
            ("Descartar", "normal", ord("r")),
            ("Descartar", "creacion", ord("R")),
            ("Sincronizar y guardar", "normal", ord("S")),
            ("Cancelar", "normal", 27),
        )
        with patch.object(aplicacion_local, "generar_candidato_automatico", side_effect=candidato):
            for etiqueta, contexto, tecla in casos:
                with self.subTest(boton=etiqueta, contexto=contexto):
                    clic, teclado = self.editor(), self.editor()
                    preparar(clic, contexto)
                    preparar(teclado, contexto)
                    accion_clic = self.pulsar_boton(clic, etiqueta)
                    accion_teclado = teclado.tecla(tecla)
                    self.assertEqual(accion_clic, accion_teclado)
                    self.assertEqual(estado(clic), estado(teclado))
                    if etiqueta == "Descartar" and contexto == "creacion":
                        self.assertTrue(clic.creando_poligono)
                        self.assertEqual(len(clic.borrador.puntos_pendientes), 4)
                    if etiqueta == "Aceptar" and contexto == "incompleta":
                        self.assertTrue(clic.creando_poligono)
        anterior, actual = self.editor(), self.editor()
        cola = deque([(anterior, ord("n")), (actual, ord("d")), (actual, ord("s"))])
        self.assertEqual(detect._tecla_calibracion(ord("Z"), actual, cola), ord("Z"))
        self.assertEqual(len(cola), 3)
        self.assertEqual(detect._tecla_calibracion(255, actual, cola), ord("d"))
        self.assertEqual(detect._tecla_calibracion(255, actual, cola), ord("s"))
        self.assertEqual(detect._tecla_calibracion(255, actual, cola), 255)

    def test_botones_aislan_gestos_y_terminan_arrastres(self):
        editor = self.editor()
        cola = deque()
        x, y = ANCHO + 30, detect.ALTO_CABECERA + 140
        editor.tecla(ord("n"))
        for evento in (cv2.EVENT_LBUTTONDOWN, cv2.EVENT_LBUTTONUP):
            detect._raton_en_marco(editor, evento, x, y, 0, None, cola)
        self.assertEqual(editor.borrador.puntos_pendientes, [])
        self.assertEqual(cola.popleft(), (editor, ord("n")))
        detect._raton_en_marco(editor, cv2.EVENT_LBUTTONDOWN, x, y, 0, None, cola)
        detect._raton_en_marco(editor, cv2.EVENT_MOUSEMOVE, 70, 156, cv2.EVENT_FLAG_LBUTTON, None, cola)
        detect._raton_en_marco(editor, cv2.EVENT_LBUTTONUP, 70, 156, 0, None, cola)
        self.assertEqual(editor.borrador.puntos_pendientes, [])
        cola.clear()
        editor.tecla(ord("z"))
        cabecera = detect.ALTO_CABECERA
        for evento in (cv2.EVENT_LBUTTONDOWN, cv2.EVENT_LBUTTONUP):
            detect._raton_en_marco(editor, evento, 70, 100 + cabecera, 0, None, cola)
        self.assertEqual(editor.borrador.id_seleccionado, "C1")
        detect._raton_en_marco(editor, cv2.EVENT_LBUTTONDOWN, 30, 60 + cabecera, 0, None, cola)
        self.assertIsNotNone(editor.control.arrastre)
        detect._raton_en_marco(editor, cv2.EVENT_MOUSEMOVE, 35, 63 + cabecera,
                               cv2.EVENT_FLAG_LBUTTON, None, cola)
        detect._raton_en_marco(editor, cv2.EVENT_LBUTTONUP, 35, 63 + cabecera, 0, None, cola)
        self.assertNotEqual(editor.borrador.zonas["C1"], editor.original.zonas["C1"])
        self.assertIsNone(editor.control.arrastre)
        self.assertIsNone(editor.antes_arrastre)
        geometria_antes = editor.borrador.zonas["C1"]
        detect._raton_en_marco(editor, cv2.EVENT_LBUTTONDOWN, 35, 63 + cabecera, 0, None, cola)
        self.assertIsNotNone(editor.control.arrastre)
        detect._raton_en_marco(editor, cv2.EVENT_LBUTTONDOWN, x, y, 0, None, cola)
        detect._raton_en_marco(editor, cv2.EVENT_LBUTTONUP, x, y, 0, None, cola)
        self.assertIsNone(editor.control.arrastre)
        self.assertIsNone(editor.antes_arrastre)
        self.assertEqual(editor.borrador.zonas["C1"], geometria_antes)
        self.assertFalse(cola)

    def test_botones_escalado_y_callback_real_en_tres_ventanas(self):
        for dimensiones in ((1540, 856), (800, 941), (2048, 900)):
            with self.subTest(ventana=dimensiones):
                raton, estado_bucle = {}, {"tick": 0, "teclas": []}
                args = argparse.Namespace(source="http", http_url=FUENTE, device=None,
                                          zones=self.ruta, headless=False, local_desktop=True,
                                          publicador=None, max_frame_age=5)
                estado = detect.inicializar_estado(self.ruta)
                mostrar = detect._mostrar_interfaz
                pantalla = aplicacion_local.EditorLocal.pantalla

                def mostrar_capturando(imagen, coordenadas=None):
                    mostrar(imagen, coordenadas)
                    raton["ajuste"] = coordenadas["ajuste"]

                def pantalla_capturando(editor):
                    raton["editor"] = editor
                    return pantalla(editor)

                def convertir(x, y):
                    ancho, alto, render_x, render_y, margen_x, margen_y = raton["ajuste"]
                    return (round(margen_x + (x + .5) * render_x / ancho - .5),
                            round(margen_y + (y + .5) * render_y / alto - .5))

                def enviar(evento, x, y, flags=0):
                    x, y = convertir(x, y)
                    raton["callback"](evento, x, y, flags, None)

                def esperar(_):
                    estado_bucle["tick"] += 1
                    tick = estado_bucle["tick"]
                    if tick == 1:
                        return ord("c")
                    if 2 <= tick <= 9:
                        _, _, (x, y, ancho, alto) = raton["editor"].botones_calibracion()[tick - 2]
                        for evento in (cv2.EVENT_LBUTTONDOWN, cv2.EVENT_LBUTTONUP):
                            enviar(evento, x + ancho // 2, y + alto // 2)
                        return ord("Z") if tick == 3 else 255
                    if tick == 10:
                        c = detect.ALTO_CABECERA
                        enviar(cv2.EVENT_LBUTTONDOWN, 70, 100 + c)
                        enviar(cv2.EVENT_LBUTTONUP, 70, 100 + c)
                        enviar(cv2.EVENT_LBUTTONDOWN, 30, 60 + c)
                        enviar(cv2.EVENT_MOUSEMOVE, 35, 63 + c, cv2.EVENT_FLAG_LBUTTON)
                        enviar(cv2.EVENT_LBUTTONUP, 35, 63 + c)
                    if tick == 11:
                        _, _, _, _, margen_x, margen_y = raton["ajuste"]
                        self.assertTrue(margen_x or margen_y)
                        x, y = (0, dimensiones[1] // 2) if margen_x else (dimensiones[0] // 2, 0)
                        raton["callback"](cv2.EVENT_LBUTTONDOWN, x, y, 0, None)
                        raton["callback"](cv2.EVENT_LBUTTONUP, x, y, 0, None)
                    return ord("q") if tick == 12 else 255

                def tecla(editor, valor):
                    if valor != 255:
                        estado_bucle["teclas"].append(valor)

                with patch.object(detect, "CapturadorReciente", return_value=self.capturador), \
                     patch.object(self.capturador, "iniciar"), \
                     patch.object(self.capturador, "detener", return_value=True), \
                     patch.object(self.capturador, "esperar", side_effect=lambda *_: self.capturador.instantanea()), \
                     patch.object(detect, "inferir", return_value=([], None, None)), \
                     patch.object(detect.FrameQualityGuard, "inspect", return_value=(True, "")), \
                     patch.object(aplicacion_local.EditorLocal, "pantalla", pantalla_capturando), \
                     patch.object(aplicacion_local.EditorLocal, "tecla", tecla), \
                     patch.object(detect, "_crear_ventana"), \
                     patch.object(detect, "_dimensiones_ventana", return_value=dimensiones), \
                     patch.object(detect, "_mostrar_interfaz", side_effect=mostrar_capturando), \
                     patch.object(detect.cv2, "setMouseCallback", side_effect=lambda _, cb: raton.update(callback=cb)), \
                     patch.object(detect.cv2, "imshow"), patch.object(detect.cv2, "waitKey", side_effect=esperar), \
                     patch.object(detect, "ventana_cerrada", return_value=False):
                    self.assertEqual(detect.ejecutar_directo(args, object(), estado), 0)
                esperado = [b[1] for b in raton["editor"].botones_calibracion()]
                self.assertEqual(estado_bucle["teclas"], [esperado[0], ord("Z"), *esperado[1:]])
                self.assertEqual(raton["editor"].borrador.id_seleccionado, "C1")
                self.assertNotEqual(raton["editor"].borrador.zonas["C1"], self.inicial.zonas["C1"])
                self.assertIsNone(raton["editor"].control.arrastre)

    def test_botones_local_cancelar_y_guardar_en_bucle(self):
        anterior = self.ruta.read_bytes()
        raton, estado_bucle = {}, {"tick": 0}
        args = argparse.Namespace(source="http", http_url=FUENTE, device=None, zones=self.ruta,
                                  headless=False, local_desktop=True, publicador=None, max_frame_age=5)
        estado = detect.inicializar_estado(self.ruta)
        mostrar = detect._mostrar_interfaz
        pantalla = aplicacion_local.EditorLocal.pantalla

        def mostrar_capturando(imagen, coordenadas=None):
            mostrar(imagen, coordenadas)
            raton["ajuste"] = coordenadas["ajuste"]

        def pantalla_capturando(editor):
            raton["editor"] = editor
            return pantalla(editor)

        def enviar(evento, x, y, flags=0):
            ancho, alto, rx, ry, mx, my = raton["ajuste"]
            xx = round(mx + (x + .5) * rx / ancho - .5)
            yy = round(my + (y + .5) * ry / alto - .5)
            raton["callback"](evento, xx, yy, flags, None)

        def esperar(_):
            estado_bucle["tick"] += 1
            tick = estado_bucle["tick"]
            if tick in (1, 4):
                if tick == 4:
                    self.assertEqual(self.ruta.read_bytes(), anterior)
                return ord("c")
            if tick in (2, 5):
                c = detect.ALTO_CABECERA
                enviar(cv2.EVENT_LBUTTONDOWN, 70, 100 + c)
                enviar(cv2.EVENT_LBUTTONUP, 70, 100 + c)
                enviar(cv2.EVENT_LBUTTONDOWN, 30, 60 + c)
                enviar(cv2.EVENT_MOUSEMOVE, 35, 63 + c, cv2.EVENT_FLAG_LBUTTON)
                enviar(cv2.EVENT_LBUTTONUP, 35, 63 + c)
            if tick in (3, 6):
                etiqueta = "Cancelar" if tick == 3 else "Sincronizar y guardar"
                _, _, (x, y, ancho, alto) = next(
                    b for b in raton["editor"].botones_calibracion() if b[0] == etiqueta)
                enviar(cv2.EVENT_LBUTTONDOWN, x + ancho // 2, y + alto // 2)
                enviar(cv2.EVENT_LBUTTONUP, x + ancho // 2, y + alto // 2)
            return ord("q") if tick == 7 else 255

        with patch.object(detect, "CapturadorReciente", return_value=self.capturador), \
             patch.object(self.capturador, "iniciar"), patch.object(self.capturador, "detener", return_value=True), \
             patch.object(self.capturador, "esperar", side_effect=lambda *_: self.capturador.instantanea()), \
             patch.object(detect, "inferir", return_value=([], None, None)), \
             patch.object(detect.FrameQualityGuard, "inspect", return_value=(True, "")), \
             patch.object(aplicacion_local.EditorLocal, "pantalla", pantalla_capturando), \
             patch.object(detect, "_crear_ventana"), patch.object(detect, "_dimensiones_ventana", return_value=(800, 941)), \
             patch.object(detect, "_mostrar_interfaz", side_effect=mostrar_capturando), \
             patch.object(detect.cv2, "setMouseCallback", side_effect=lambda _, cb: raton.update(callback=cb)), \
             patch.object(detect.cv2, "imshow"), patch.object(detect.cv2, "waitKey", side_effect=esperar), \
             patch.object(detect, "ventana_cerrada", return_value=False):
            self.assertEqual(detect.ejecutar_directo(args, object(), estado), 0)
        guardada = cargar_calibracion(self.ruta, ANCHO, ALTO)
        self.assertNotEqual(self.ruta.read_bytes(), anterior)
        self.assertEqual(guardada.vision_zone_ids, self.inicial.vision_zone_ids)
        self.assertNotEqual(guardada.zonas["C1"], self.inicial.zonas["C1"])

    def test_guardar_cancelar_deshacer_y_conservar_identidades(self):
        anterior = self.ruta.read_bytes()
        vinculo_anterior = ruta_vinculo(self.ruta).read_bytes()
        editor = self.editor()
        self.mover(editor)
        self.assertNotEqual(editor.borrador.zonas["C1"], editor.original.zonas["C1"])
        editor.tecla(ord("z"))
        self.assertEqual(editor.borrador.zonas["C1"], editor.original.zonas["C1"])
        self.assertEqual(editor.guardar(self.capturador, 2), "sin_cambios")
        self.assertEqual(self.ruta.read_bytes(), anterior)
        self.assertEqual(ruta_vinculo(self.ruta).read_bytes(), vinculo_anterior)
        self.assertFalse((self.ruta.parent / "respaldos").exists())

        editor = self.editor()
        self.mover(editor)
        self.assertEqual(editor.tecla(27), "cancelar")
        self.assertEqual(self.ruta.read_bytes(), anterior)
        self.assertEqual(editor.guardar(self.capturador, 2), "guardada")
        guardada = cargar_calibracion(self.ruta, ANCHO, ALTO)
        self.assertEqual(guardada.vision_zone_ids, self.inicial.vision_zone_ids)
        datos_guardados = json.loads(self.ruta.read_text())
        self.assertNotIn("revision_calibracion", datos_guardados["metadata"])
        self.assertNotIn("calibration_sha256", datos_guardados["metadata"])
        self.assertNotIn("geometry_fingerprint", datos_guardados["metadata"])
        self.assertNotEqual(guardada.zonas["C1"], self.inicial.zonas["C1"])
        self.assertEqual({z["id"]: z["cajonId"] for z in datos_guardados["zones"]},
                         {f"C{n}": f"cajon-sintetico-C{n}" for n in range(1, 9)})
        verificar_vinculo(self.ruta, "http", FUENTE, ANCHO, ALTO)
        respaldo = next((self.ruta.parent / "respaldos").iterdir())
        self.assertEqual((respaldo / self.ruta.name).read_bytes(), anterior)
        self.assertEqual((respaldo / ruta_vinculo(self.ruta).name).read_bytes(), vinculo_anterior)

    def test_fallo_sidecar_restaura_anterior_y_recupera_interrupcion(self):
        anterior = self.ruta.read_bytes()
        vinculo_anterior = ruta_vinculo(self.ruta).read_bytes()
        editor = self.editor()
        self.mover(editor)
        with patch.object(aplicacion_local, "guardar_vinculo", side_effect=OSError("fallo sintetico")):
            self.assertIsNone(editor.guardar(self.capturador, 2))
        self.assertEqual(self.ruta.read_bytes(), anterior)
        self.assertEqual(ruta_vinculo(self.ruta).read_bytes(), vinculo_anterior)
        self.assertIn("recupero", editor.control.mensaje)
        self.assertFalse(editor.bloqueado)
        self.assertNotEqual(editor.borrador.zonas["C1"], editor.original.zonas["C1"])
        verificar_vinculo(self.ruta, "http", FUENTE, ANCHO, ALTO)
        self.assertEqual(editor.guardar(self.capturador, 2), "guardada")
        # Simula interrupcion tras reemplazar JSON, antes de reemplazar el sidecar.
        ruta_vinculo(self.ruta).write_bytes(vinculo_anterior)
        verificar_vinculo(self.ruta, "http", FUENTE, ANCHO, ALTO)
        self.assertEqual(
            set(cargar_calibracion(self.ruta, ANCHO, ALTO).zonas),
            set(self.inicial.zonas),
        )

    def test_editor_concurrente_no_restaura_respaldo_obsoleto(self):
        primero, segundo = self.editor(), self.editor()
        self.mover(primero)
        self.mover(segundo)
        self.assertTrue(primero.borrador.mover_vertice("C2", 0, 177, 63)[0])
        anteriores = self.ruta.read_bytes(), ruta_vinculo(self.ruta).read_bytes()
        esperando, continuar, fallo_sidecar = (threading.Event() for _ in range(3))
        errores, resultados = [], []
        iniciar_real = configuracion_local.iniciar_guardado_pendiente
        vinculo_real = aplicacion_local.guardar_vinculo

        def iniciar(*args, **kwargs):
            if threading.current_thread().name == "segundo-editor":
                esperando.set()
                if not continuar.wait(5):
                    raise RuntimeError("El primer editor no termino.")
            return iniciar_real(*args, **kwargs)

        def vinculo(*args, **kwargs):
            if threading.current_thread().name == "segundo-editor":
                fallo_sidecar.set()
                raise OSError("fallo concurrente sintetico")
            return vinculo_real(*args, **kwargs)

        def guardar_segundo():
            try:
                resultados.append(segundo.guardar(self.capturador, 5))
            except BaseException as error:
                errores.append(error)

        with patch.object(configuracion_local, "iniciar_guardado_pendiente", side_effect=iniciar), \
             patch.object(aplicacion_local, "guardar_vinculo", side_effect=vinculo):
            hilo = threading.Thread(target=guardar_segundo, name="segundo-editor")
            hilo.start()
            try:
                self.assertTrue(esperando.wait(5))
                self.assertEqual(primero.guardar(self.capturador, 5), "guardada")
                confirmado = self.ruta.read_bytes(), ruta_vinculo(self.ruta).read_bytes()
                self.assertNotEqual(confirmado[0], anteriores[0])
            finally:
                continuar.set()
                hilo.join(5)
        self.assertFalse(hilo.is_alive())
        self.assertEqual(errores, [])
        self.assertEqual(resultados, [None])
        self.assertTrue(fallo_sidecar.is_set())
        self.assertIn("recupero", segundo.control.mensaje)
        self.assertEqual((self.ruta.read_bytes(), ruta_vinculo(self.ruta).read_bytes()), confirmado)

    def test_fallo_respaldo_mantiene_el_editor_y_el_par_anterior(self):
        anterior = self.ruta.read_bytes()
        vinculo_anterior = ruta_vinculo(self.ruta).read_bytes()
        editor = self.editor()
        self.mover(editor)
        with patch("configuracion_local._respaldar_calibracion_bajo_guardado",
                   side_effect=OSError("respaldo sintetico")):
            self.assertIsNone(editor.guardar(self.capturador, 2))
        self.assertIn("No se guardo", editor.control.mensaje)
        self.assertFalse(editor.bloqueado)
        self.assertEqual(self.ruta.read_bytes(), anterior)
        self.assertEqual(ruta_vinculo(self.ruta).read_bytes(), vinculo_anterior)
        self.assertNotEqual(editor.borrador.zonas["C1"], editor.original.zonas["C1"])

    def test_recupera_sidecar_ausente_tras_fallo_parcial_de_guardado(self):
        anterior = self.ruta.read_bytes()
        vinculo_anterior = ruta_vinculo(self.ruta).read_bytes()
        editor = self.editor()
        self.mover(editor)

        def fallar_despues_de_retirar_sidecar(ruta, *_args):
            ruta_vinculo(ruta).unlink()
            raise OSError("fallo parcial sintetico")

        with patch.object(aplicacion_local, "guardar_vinculo",
                          side_effect=fallar_despues_de_retirar_sidecar):
            self.assertIsNone(editor.guardar(self.capturador, 2))
        self.assertEqual(self.ruta.read_bytes(), anterior)
        self.assertEqual(ruta_vinculo(self.ruta).read_bytes(), vinculo_anterior)
        self.assertIn("recupero", editor.control.mensaje)
        self.assertFalse(editor.bloqueado)
        verificar_vinculo(self.ruta, "http", FUENTE, ANCHO, ALTO)

    def test_recupera_sidecar_legacy_tras_reemplazo_fallido(self):
        vinculo = ruta_vinculo(self.ruta)
        datos = json.loads(vinculo.read_text(encoding="utf-8"))
        datos["version"] = 2
        datos["dato_legacy"] = "conservar"
        vinculo.write_text(json.dumps(datos), encoding="utf-8")
        anterior = self.ruta.read_bytes(), vinculo.read_bytes()
        editor = self.editor()
        self.mover(editor)

        def guardar_y_fallar(*args):
            guardar_vinculo(*args)
            raise OSError("fallo tras reemplazar sidecar")

        with patch.object(aplicacion_local, "guardar_vinculo", side_effect=guardar_y_fallar):
            self.assertIsNone(editor.guardar(self.capturador, 2))
        self.assertEqual((self.ruta.read_bytes(), vinculo.read_bytes()), anterior)
        self.assertFalse(editor.bloqueado)
        self.assertFalse(self.ruta.with_name(".zones.json.guardado-pendiente").exists())
        self.assertNotEqual(editor.borrador.zonas["C1"], editor.original.zonas["C1"])

    def test_interrupcion_de_proceso_bloquea_lectura_local_y_conserva_respaldo(self):
        anterior = self.ruta.read_bytes(), ruta_vinculo(self.ruta).read_bytes()
        programa = """
import os, sys
from pathlib import Path
import numpy as np
import aplicacion_local, capture
ruta, fuente = Path(sys.argv[1]), sys.argv[2]
capturador = capture.CapturadorReciente("http", fuente, None)
capturador._publicar(np.full((360, 640, 3), 100, dtype=np.uint8),
                     "sintetica", nueva_conexion=True)
editor = aplicacion_local.EditorLocal(ruta, "http", fuente, capturador.instantanea())
aceptado, _ = editor.borrador.mover_vertice("C1", 0, 35, 63)
assert aceptado
aplicacion_local.guardar_vinculo = lambda *args: os._exit(75)
editor.guardar(capturador, 2)
"""
        resultado = subprocess.run(
            [sys.executable, "-c", programa, str(self.ruta), FUENTE],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(resultado.returncode, 75, resultado.stderr)
        self.assertNotEqual(self.ruta.read_bytes(), anterior[0])
        self.assertEqual(ruta_vinculo(self.ruta).read_bytes(), anterior[1])
        marcador = self.ruta.with_name(".zones.json.guardado-pendiente")
        self.assertTrue(marcador.is_file())
        respaldo = next((self.ruta.parent / "respaldos").iterdir())
        self.assertEqual((respaldo / self.ruta.name).read_bytes(), anterior[0])
        self.assertEqual((respaldo / ruta_vinculo(self.ruta).name).read_bytes(), anterior[1])
        with self.assertRaisesRegex(ValueError, "guardado pendiente"):
            aplicacion_local.validar_archivo_local(self.ruta, "http", FUENTE, recuperar=False)
        with self.assertRaisesRegex(ValueError, "guardado pendiente"):
            cargar_calibracion(self.ruta, ANCHO, ALTO)

    def test_fallo_al_retirar_marcador_bloquea_editor(self):
        editor = self.editor()
        self.mover(editor)
        with patch.object(aplicacion_local, "finalizar_guardado_pendiente",
                          side_effect=OSError("cierre sintetico"), create=True):
            with self.assertRaisesRegex(ValueError, "No se pudo cerrar"):
                editor.guardar(self.capturador, 2)
        self.assertTrue(editor.bloqueado)
        self.assertTrue(self.ruta.with_name(".zones.json.guardado-pendiente").is_file())
        with self.assertRaisesRegex(ValueError, "guardado pendiente"):
            cargar_calibracion(self.ruta, ANCHO, ALTO)

    def test_guardado_sin_cambios_rechaza_marcador_residual(self):
        editor = self.editor()
        marcador = self.ruta.with_name(".zones.json.guardado-pendiente")
        marcador.write_bytes(b"recuperacion pendiente")
        self.assertIsNone(editor.guardar(self.capturador, 2))
        self.assertTrue(editor.bloqueado)
        self.assertIn("guardado pendiente", editor.control.mensaje)
        self.assertEqual(marcador.read_bytes(), b"recuperacion pendiente")
        self.assertFalse((self.ruta.parent / "respaldos").exists())

    def test_fallo_restauracion_bloquea_el_editor_y_conserva_respaldo(self):
        anterior = self.ruta.read_bytes()
        editor = self.editor()
        self.mover(editor)
        with patch.object(aplicacion_local, "guardar_vinculo",
                          side_effect=OSError("fallo sintetico")), \
             patch.object(aplicacion_local, "_restaurar_json",
                          side_effect=OSError("restauracion sintetica")):
            with self.assertRaisesRegex(ValueError, "No se recupero el par anterior"):
                editor.guardar(self.capturador, 2)
        self.assertTrue(editor.bloqueado)
        self.assertIsNone(editor.tecla(ord("s")))
        self.assertTrue(self.ruta.with_name(".zones.json.guardado-pendiente").is_file())
        respaldos = list((self.ruta.parent / "respaldos").iterdir())
        self.assertEqual(len(respaldos), 1)
        self.assertEqual((respaldos[0] / self.ruta.name).read_bytes(), anterior)

    def test_error_tipo_al_restaurar_mantiene_el_bloqueo(self):
        editor = self.editor()
        self.mover(editor)
        with patch.object(aplicacion_local, "guardar_vinculo",
                          side_effect=OSError("fallo sintetico")), \
             patch.object(aplicacion_local, "_restaurar_json",
                          side_effect=TypeError("restauracion sintetica")):
            with self.assertRaisesRegex(ValueError, "No se recupero el par anterior"):
                editor.guardar(self.capturador, 2)
        self.assertTrue(editor.bloqueado)

    def test_error_recuperable_de_guardado_mantiene_el_bucle_local(self):
        anterior = self.ruta.read_bytes()
        vinculo_anterior = ruta_vinculo(self.ruta).read_bytes()
        args = argparse.Namespace(source="http", http_url=FUENTE, device=None, zones=self.ruta,
                                  headless=False, local_desktop=True, publicador=None, max_frame_age=5)
        estado = detect.inicializar_estado(self.ruta)
        pantalla_real = aplicacion_local.EditorLocal.pantalla
        editores, mensajes = [], []

        def pantalla_capturando(editor):
            if not editores:
                editores.append(editor)
                self.mover(editor)
            mensajes.append(editor.control.mensaje)
            return pantalla_real(editor)

        with patch.object(detect, "CapturadorReciente", return_value=self.capturador), \
             patch.object(self.capturador, "iniciar"), \
             patch.object(self.capturador, "detener", return_value=True), \
             patch.object(self.capturador, "esperar", side_effect=lambda *_: self.capturador.instantanea()), \
             patch.object(detect, "inferir", return_value=([], None, None)), \
             patch.object(detect.FrameQualityGuard, "inspect", return_value=(True, "")), \
             patch.object(aplicacion_local.EditorLocal, "pantalla", pantalla_capturando), \
             patch.object(aplicacion_local, "guardar_vinculo", side_effect=OSError("fallo sintetico")), \
             patch.object(detect, "_crear_ventana"), \
             patch.object(detect, "_dimensiones_ventana", return_value=(800, 941)), \
             patch.object(detect, "_mostrar_interfaz"), \
             patch.object(detect.cv2, "setMouseCallback"), \
             patch.object(detect.cv2, "imshow"), \
             patch.object(detect.cv2, "waitKey", side_effect=[ord("c"), ord("s"), 255, ord("q")]), \
             patch.object(detect, "ventana_cerrada", return_value=False):
            self.assertEqual(detect.ejecutar_directo(args, object(), estado), 0)

        self.assertTrue(any("recupero" in mensaje for mensaje in mensajes))
        self.assertEqual(len(editores), 1)
        self.assertFalse(editores[0].bloqueado)
        self.assertNotEqual(editores[0].borrador.zonas["C1"], editores[0].original.zonas["C1"])
        self.assertEqual(self.ruta.read_bytes(), anterior)
        self.assertEqual(ruta_vinculo(self.ruta).read_bytes(), vinculo_anterior)

    def test_descarta_eliminacion_creacion_ids_incompletos_y_fuente_cambiada(self):
        anterior = self.ruta.read_bytes()
        editor = self.editor()
        editor.raton(cv2.EVENT_LBUTTONDOWN, 1, 1, 0, None)
        self.assertFalse(editor.borrador.puntos_pendientes)
        editor.tecla(ord("n"))
        editor.borrador.puntos_pendientes.append((0.5, 0.5))
        self.assertIsNone(editor.guardar(self.capturador, 2))
        editor.borrador.puntos_pendientes.clear()
        editor.creando_poligono = False
        editor.borrador.vision_zone_ids["C1"] = editor.borrador.vision_zone_ids["C2"]
        self.assertIsNone(editor.guardar(self.capturador, 2))
        self.assertIn("UUID", editor.control.mensaje)
        editor = self.editor()
        self.mover(editor)
        self.capturador._publicar(self.imagen, "sintetica", nueva_conexion=True)
        self.assertIsNone(editor.guardar(self.capturador, 2))
        self.assertTrue(editor.fuente_cambiada)
        self.assertEqual(self.ruta.read_bytes(), anterior)

    def test_c9_edicion_eliminacion_c10_y_contador_despues_de_reabrir(self):
        editor = self.editor()

        def crear(etiqueta, puntos):
            editor.tecla(ord("n"))
            for x, y in puntos:
                editor.raton(cv2.EVENT_LBUTTONDOWN, x, y, 0, None)
            editor.tecla(13)
            self.assertEqual(editor.borrador.id_seleccionado, etiqueta)

        crear("C9", [(500, 200), (560, 200), (560, 260), (500, 260)])
        self.assertEqual(len(editor.borrador.zonas), 9)
        identidad_c9 = editor.borrador.vision_zone_ids["C9"]
        editor.raton(cv2.EVENT_LBUTTONDOWN, 500, 200, 0, None)
        editor.raton(cv2.EVENT_MOUSEMOVE, 505, 205, cv2.EVENT_FLAG_LBUTTON, None)
        editor.raton(cv2.EVENT_LBUTTONUP, 505, 205, 0, None)
        self.assertEqual(editor.borrador.vision_zone_ids["C9"], identidad_c9)
        self.assertNotEqual(editor.borrador.zonas["C9"], editor.original.zonas.get("C9"))

        editor.tecla(ord("d"))
        self.assertNotIn("C9", editor.borrador.zonas)
        crear("C10", [(500, 200), (570, 200), (570, 270), (500, 270)])
        self.assertEqual(len(editor.borrador.zonas), 9)
        self.assertEqual(editor.borrador.next_c_number, 11)
        self.assertEqual(editor.guardar(self.capturador, 2), "guardada")

        reabierto = self.editor()
        self.assertIn("C10", reabierto.borrador.zonas)
        self.assertNotIn("C9", reabierto.borrador.zonas)
        self.assertEqual(reabierto.borrador.next_c_number, 11)
        reabierto.tecla(ord("n"))
        for x, y in [(400, 200), (460, 200), (460, 260), (400, 260)]:
            reabierto.raton(cv2.EVENT_LBUTTONDOWN, x, y, 0, None)
        reabierto.tecla(13)
        self.assertIn("C11", reabierto.borrador.zonas)

    def test_propuesta_requiere_revision_y_admite_deshacer(self):
        editor = self.editor()
        propuesta = copy.deepcopy(editor.borrador)
        self.assertTrue(propuesta.mover_vertice("C1", 0, 35, 63)[0])
        with patch.object(aplicacion_local, "generar_candidato_automatico",
                          return_value=argparse.Namespace(calibracion=propuesta)):
            editor.tecla(ord("a"))
            self.assertEqual(editor.borrador.zonas["C1"], editor.original.zonas["C1"])
            self.assertIsNone(editor.tecla(ord("s")))
            editor.tecla(ord("r"))
            self.assertIsNone(editor.propuesta)
            editor.tecla(ord("a"))
            editor.tecla(13)
        self.assertNotEqual(editor.borrador.zonas["C1"], editor.original.zonas["C1"])
        editor.tecla(ord("z"))
        self.assertEqual(editor.borrador.zonas["C1"], editor.original.zonas["C1"])

    def test_propuesta_automatica_real_con_escena_sintetica(self):
        from calibracion_automatica import generar_candidato_automatico
        from test_calibracion_automatica import ANCHO as ancho, ALTO as alto, crear_frame_lineal

        frame, _ = crear_frame_lineal()
        calibracion = generar_candidato_automatico(frame).calibracion
        poligono = calibracion.zonas["C3"].polygon
        calibracion.zonas["C3"] = ParkingZone("C3", tuple((x + 0.015, y) for x, y in poligono))
        identidad = identidad_fuente("http", FUENTE)
        calibracion.metadata["fuente_sha256"] = identidad
        guardar_calibracion(self.ruta, calibracion, "http")
        guardar_vinculo(self.ruta, "http", FUENTE, ancho, alto)
        capturador = capture.CapturadorReciente("http", FUENTE, None)
        capturador._publicar(frame, "sintetica", nueva_conexion=True)
        editor = aplicacion_local.EditorLocal(self.ruta, "http", FUENTE, capturador.instantanea())
        anterior = self.ruta.read_bytes()
        editor.tecla(ord("a"))
        self.assertIsNotNone(editor.propuesta, editor.control.mensaje)
        self.assertEqual(self.ruta.read_bytes(), anterior)
        self.assertEqual(editor.borrador.zonas["C3"], editor.original.zonas["C3"])
        self.assertEqual(editor.propuesta.vision_zone_ids, editor.original.vision_zone_ids)
        editor.tecla(13)
        self.assertNotEqual(editor.borrador.zonas["C3"], editor.original.zonas["C3"])
        capturador._publicar(frame + np.uint8(1), "sintetica", nueva_conexion=False)
        self.assertEqual(editor.guardar(capturador, 2), "guardada")
        self.assertEqual(cargar_calibracion(self.ruta, ancho, alto).vision_zone_ids,
                         calibracion.vision_zone_ids)

    def test_escritorio_local_no_publica_en_java(self):
        args = argparse.Namespace(image=None, simulation_dir=None, source="http", http_url=FUENTE,
                                  device=None, model=Path("modelo-sintetico.pt"), zones=self.ruta,
                                  headless=False, local_desktop=True,
                                  local_calibration_dir=self.ruta.parent, publish_java=False)
        with patch.object(detect, "ejecutar_directo", return_value=0) as ejecutar, \
             patch.object(detect, "PublicadorVision") as java, \
             patch.object(detect.cv2, "destroyAllWindows"):
            self.assertEqual(detect.run(args), 0)
            java.assert_not_called()
            self.assertIsNone(ejecutar.call_args.args[0].publicador)
            args.publish_java = True
            self.assertEqual(detect.run(args), 1)
            java.assert_not_called()

    def test_loop_guardar_aplica_poligono_al_siguiente_monitor(self):
        camara = Mock()
        raton = {}
        teclas = {"n": 0}
        poligonos_inferidos = []
        mostrar_interfaz_original = detect._mostrar_interfaz
        args = argparse.Namespace(source="http", http_url=FUENTE, device=None, zones=self.ruta,
                                  model=Path("modelo-sintetico.pt"), headless=False,
                                  local_desktop=True, imgsz=64, conf=0.3,
                                  publicador=None, max_frame_age=2)
        estado = detect.inicializar_estado(self.ruta)
        inferir_original = detect.inferir

        def leer(*_args):
            time.sleep(0.005)
            return self.imagen.copy()

        def inferir(_modelo, cuadro, argumentos, guardia, estado_actual, **kwargs):
            poligonos_inferidos.append(estado_actual.zones[0].polygon)
            return inferir_original(_modelo, cuadro, argumentos, guardia, estado_actual, **kwargs)

        def mostrar_interfaz(imagen, coordenadas=None):
            mostrar_interfaz_original(imagen, coordenadas)
            if coordenadas is not None:
                raton["ajuste"] = coordenadas["ajuste"]

        def convertir_a_ventana(x, y):
            ancho, alto, ancho_renderizado, alto_renderizado, margen_x, margen_y = raton["ajuste"]
            return (
                round(margen_x + (x + 0.5) * ancho_renderizado / ancho - 0.5),
                round(margen_y + (y + 0.5) * alto_renderizado / alto - 0.5),
            )

        def esperar_tecla(_milisegundos):
            time.sleep(0.02)
            teclas["n"] += 1
            if teclas["n"] == 6:
                callback = raton["callback"]
                x, y = convertir_a_ventana(70, 100 + detect.ALTO_CABECERA)
                callback(cv2.EVENT_LBUTTONDOWN, x, y, 0, None)
                x, y = convertir_a_ventana(30, 60 + detect.ALTO_CABECERA)
                callback(cv2.EVENT_LBUTTONDOWN, x, y, 0, None)
                x, y = convertir_a_ventana(35, 63 + detect.ALTO_CABECERA)
                callback(cv2.EVENT_MOUSEMOVE, x, y, cv2.EVENT_FLAG_LBUTTON, None)
                callback(cv2.EVENT_LBUTTONUP, x, y, 0, None)
            return {4: ord("c"), 8: ord("s"), 14: ord("q")}.get(teclas["n"], 255)

        def registrar_raton(_titulo, callback):
            raton["callback"] = callback

        with patch.object(capture, "open_video_source", return_value=(camara, "fake", "fake", self.imagen)) as abrir, \
             patch.object(capture, "read_frame", side_effect=leer), \
             patch.object(detect, "load_model_from_path", return_value=object()) as modelo, \
             patch.object(detect, "inferir", side_effect=inferir), \
             patch.object(detect, "predict", return_value=(object(), 1, 1)), \
             patch.object(detect, "detections_from_result", return_value=[]), \
             patch.object(detect.FrameQualityGuard, "inspect", return_value=(True, "")), \
             patch.object(detect.cv2, "namedWindow"), patch.object(detect.cv2, "resizeWindow"), \
             patch.object(detect, "_dimensiones_ventana", return_value=(800, 941)), \
             patch.object(detect, "_mostrar_interfaz", side_effect=mostrar_interfaz), \
             patch.object(detect.cv2, "setMouseCallback", side_effect=registrar_raton), \
             patch.object(detect.cv2, "imshow"), patch.object(detect.cv2, "waitKey", side_effect=esperar_tecla), \
             patch.object(detect, "ventana_cerrada", return_value=False):
            self.assertEqual(detect.ejecutar_directo(args, detect._CARGAR_MODELO_EN_VIVO, estado), 0)
        guardada = cargar_calibracion(self.ruta, ANCHO, ALTO)
        self.assertEqual(guardada.next_c_number, self.inicial.next_c_number)
        self.assertEqual(guardada.vision_zone_ids, self.inicial.vision_zone_ids)
        self.assertNotEqual(poligonos_inferidos[0], guardada.zonas["C1"].polygon)
        self.assertEqual(poligonos_inferidos[-1], guardada.zonas["C1"].polygon)
        self.assertEqual(abrir.call_count, 1)
        self.assertEqual(modelo.call_count, 1)
        self.assertEqual(camara.release.call_count, 1)

    def test_loop_cambia_dos_veces_sin_reabrir_camara_ni_recargar_modelo(self):
        camara = Mock()
        lecturas = []
        imagenes_editor = []
        inferencias_en_editor = []
        modo = {"editor": False}
        contador = {"teclas": 0}
        args = argparse.Namespace(source="http", http_url=FUENTE, device=None, zones=self.ruta,
                                  model=Path("modelo-sintetico.pt"), headless=False,
                                  local_desktop=True, imgsz=64, conf=0.3,
                                  publicador=None, max_frame_age=2)
        estado = detect.inicializar_estado(self.ruta)
        pantalla_original = aplicacion_local.EditorLocal.pantalla
        tecla_original = aplicacion_local.EditorLocal.tecla

        def leer(*_args):
            time.sleep(0.006)
            lecturas.append(1)
            return np.full((ALTO, ANCHO, 3), 100 + len(lecturas) % 40, dtype=np.uint8)

        def pantalla(editor):
            modo["editor"] = True
            imagenes_editor.append((editor.generacion, editor.imagen.copy(), len(lecturas)))
            return pantalla_original(editor)

        def tecla_editor(editor, tecla):
            accion = tecla_original(editor, tecla)
            if accion in ("cancelar", "guardar"):
                modo["editor"] = False
            return accion

        def predecir(*_args):
            inferencias_en_editor.append(modo["editor"])
            return object(), 1.0, 1.0

        def esperar_tecla(_milisegundos):
            time.sleep(0.02)
            contador["teclas"] += 1
            return {4: ord("c"), 9: 27, 13: ord("c"), 18: ord("s"), 22: ord("q")}.get(
                contador["teclas"], 255)

        with patch.object(capture, "open_video_source", return_value=(camara, "fake", "fake", self.imagen)) as abrir, \
             patch.object(capture, "read_frame", side_effect=leer), \
             patch.object(detect, "load_model_from_path", return_value=object()) as modelo, \
             patch.object(detect, "predict", side_effect=predecir), \
             patch.object(detect, "detections_from_result", return_value=[]), \
             patch.object(detect.FrameQualityGuard, "inspect", return_value=(True, "")), \
             patch.object(aplicacion_local.EditorLocal, "pantalla", pantalla), \
             patch.object(aplicacion_local.EditorLocal, "tecla", tecla_editor), \
             patch.object(detect.cv2, "namedWindow"), patch.object(detect.cv2, "resizeWindow"), \
             patch.object(detect.cv2, "setMouseCallback"), patch.object(detect.cv2, "imshow"), \
             patch.object(detect.cv2, "waitKey", side_effect=esperar_tecla), \
             patch.object(detect, "ventana_cerrada", return_value=False):
            self.assertEqual(detect.ejecutar_directo(args, detect._CARGAR_MODELO_EN_VIVO, estado), 0)
        self.assertEqual(abrir.call_count, 1)
        self.assertEqual(modelo.call_count, 1)
        self.assertEqual(camara.release.call_count, 1)
        self.assertGreaterEqual(len(imagenes_editor), 8)
        primera, segunda = imagenes_editor[:4], imagenes_editor[4:]
        self.assertTrue(all(np.array_equal(primera[0][1], item[1]) for item in primera))
        self.assertGreater(primera[-1][2], primera[0][2])
        self.assertGreater(segunda[-1][2], segunda[0][2])
        self.assertTrue(inferencias_en_editor)
        self.assertFalse(any(inferencias_en_editor))


if __name__ == "__main__":
    unittest.main()
