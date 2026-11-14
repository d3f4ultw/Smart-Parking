import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from calibracion_automatica import (
    ErrorCalibracionAutomatica,
    _agrupar_segmentos,
    generar_candidato_automatico,
)
from calibracion_zonas import (
    CalibracionZonas,
    cargar_calibracion,
    guardar_calibracion,
)
from configuracion_local import identidad_fuente, ruta_vinculo, verificar_vinculo
from temporal_validation import ParkingZone


ANCHO = 1600
ALTO = 900


def crear_frame_lineal() -> tuple[np.ndarray, dict[str, tuple[tuple[float, float], ...]]]:
    frame = np.full((ALTO, ANCHO, 3), 58, dtype=np.uint8)
    esperadas = {}
    filas = (
        (100, 340, (90, 415, 740, 1065, 1410), (110, 430, 750, 1070, 1425)),
        (590, 850, (60, 380, 700, 1020, 1420), (80, 400, 720, 1040, 1440)),
    )
    for fila, (y_superior, y_inferior, xs_superiores, xs_inferiores) in enumerate(filas):
        cv2.line(frame, (xs_superiores[0], y_superior), (xs_superiores[-1], y_superior),
                 (238, 238, 238), 7)
        cv2.line(frame, (xs_inferiores[0], y_inferior), (xs_inferiores[-1], y_inferior),
                 (238, 238, 238), 7)
        for columna in range(5):
            cv2.line(frame, (xs_superiores[columna], y_superior),
                     (xs_inferiores[columna], y_inferior), (238, 238, 238), 7)
        for columna in range(4):
            etiqueta = f"C{fila * 4 + columna + 1}"
            poligono = (
                (xs_superiores[columna] / (ANCHO - 1), y_superior / (ALTO - 1)),
                (xs_superiores[columna + 1] / (ANCHO - 1), y_superior / (ALTO - 1)),
                (xs_inferiores[columna + 1] / (ANCHO - 1), y_inferior / (ALTO - 1)),
                (xs_inferiores[columna] / (ANCHO - 1), y_inferior / (ALTO - 1)),
            )
            esperadas[etiqueta] = poligono
    return frame, esperadas


def calcular_iou(primero, segundo) -> float:
    escala = 1024
    mascaras = []
    for poligono in (primero, segundo):
        mascara = np.zeros((escala, escala), dtype=np.uint8)
        puntos = np.asarray(
            [(round(x * (escala - 1)), round(y * (escala - 1))) for x, y in poligono],
            dtype=np.int32,
        )
        cv2.fillPoly(mascara, [puntos], 1)
        mascaras.append(mascara.astype(bool))
    union = np.logical_or(mascaras[0], mascaras[1]).sum()
    interseccion = np.logical_and(mascaras[0], mascaras[1]).sum()
    return float(interseccion / union) if union else 0.0


class CalibracionAutomaticaTest(unittest.TestCase):
    def test_genera_ocho_poligonos_con_limites_visibles_y_orden_espacial(self):
        frame, esperadas = crear_frame_lineal()
        resultado = generar_candidato_automatico(frame)
        calibracion = resultado.calibracion

        self.assertEqual(list(calibracion.zonas), [f"C{numero}" for numero in range(1, 9)])
        self.assertEqual(len(resultado.evidencias), 8)
        for evidencia in resultado.evidencias:
            zona = calibracion.zonas[evidencia.etiqueta]
            self.assertEqual(len(zona.polygon), 4)
            self.assertGreaterEqual(evidencia.confianza, 0.45)
            self.assertTrue(all(0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 for x, y in zona.polygon))
            self.assertGreaterEqual(calcular_iou(zona.polygon, esperadas[evidencia.etiqueta]), 0.90)
            self.assertTrue(all(valor > 0.0 for valor in evidencia.bordes))
        self.assertTrue(all(
            calibracion.zonas[f"C{numero}"].polygon[0][1]
            < calibracion.zonas[f"C{numero + 4}"].polygon[0][1]
            for numero in range(1, 5)
        ))

    def test_borde_exterior_sin_divisores_no_desplaza_el_limite_de_cajones(self):
        frame, _ = crear_frame_lineal()
        ampliado = np.full((ALTO + 41, ANCHO, 3), 58, dtype=np.uint8)
        ampliado[:ALTO] = frame
        cv2.line(ampliado, (20, 890), (ANCHO - 20, 890), (255, 255, 255), 13)

        resultado = generar_candidato_automatico(ampliado)
        limite_inferior = resultado.calibracion.zonas["C5"].polygon[2][1] * (ampliado.shape[0] - 1)

        self.assertLess(abs(limite_inferior - 850), 10)

    def test_corrige_geometria_parcial_y_conserva_uuid_del_mismo_cajon(self):
        frame, _ = crear_frame_lineal()
        original = generar_candidato_automatico(frame).calibracion
        geometria_parcial = dict(original.zonas)
        zona = geometria_parcial["C3"]
        poligono_desplazado = tuple((x + 0.015, y) for x, y in zona.polygon)
        geometria_parcial["C3"] = ParkingZone("C3", poligono_desplazado)
        parcial = CalibracionZonas(
            ANCHO,
            ALTO,
            zonas=geometria_parcial,
            next_c_number=original.next_c_number,
            vision_zone_ids=dict(original.vision_zone_ids),
        )

        resultado = generar_candidato_automatico(frame, parcial)

        self.assertEqual(resultado.calibracion.vision_zone_ids["C3"], original.vision_zone_ids["C3"])
        self.assertNotEqual(resultado.calibracion.zonas["C3"].polygon, poligono_desplazado)
        evidencia = next(item for item in resultado.evidencias if item.etiqueta == "C3")
        self.assertIsNotNone(evidencia.cambio_geometrico)
        self.assertIn("corregido", evidencia.diagnostico)

    def test_rechaza_frame_sin_limites_y_no_fabrica_geometria(self):
        with self.assertRaises(ErrorCalibracionAutomatica):
            generar_candidato_automatico(np.zeros((ALTO, ANCHO, 3), dtype=np.uint8))

    def test_fitline_acepta_la_forma_n_por_uno_de_opencv(self):
        with patch(
            "calibracion_automatica.cv2.fitLine",
            return_value=np.asarray([[1.0], [0.0], [0.0], [10.0]], dtype=np.float32),
        ):
            lineas = _agrupar_segmentos(
                [(0, 10, 20, 10)], lambda segmento: float(segmento[1]),
                5.0, "horizontal", 10.0, 20.0,
            )

        self.assertEqual(len(lineas), 1)
        self.assertAlmostEqual(lineas[0].posicion, 10.0)

    def test_recupera_sidecar_interrumpido_desde_calibracion_canonica(self):
        frame, _ = crear_frame_lineal()
        calibracion = generar_candidato_automatico(frame).calibracion
        origen = "http://127.0.0.1:4747/video?token=valor-privado-de-prueba"
        identidad = identidad_fuente("http", origen)
        calibracion.metadata["fuente_sha256"] = identidad
        with tempfile.TemporaryDirectory() as directorio:
            ruta = Path(directorio) / "zones.json"
            guardar_calibracion(ruta, calibracion, "http")

            self.assertFalse(ruta_vinculo(ruta).exists())
            verificar_vinculo(ruta, "http", origen, ANCHO, ALTO)

            sidecar = json.loads(ruta_vinculo(ruta).read_text(encoding="utf-8"))
            principal = json.loads(ruta.read_text(encoding="utf-8"))
            self.assertEqual(sidecar["version"], 1)
            self.assertEqual(sidecar["ancho"], ANCHO)
            self.assertEqual(sidecar["alto"], ALTO)
            self.assertNotIn("zonas_sha256", sidecar)
            self.assertNotIn("revision_calibracion", sidecar)
            self.assertNotIn("revision_calibracion", principal["metadata"])
            self.assertNotIn("calibration_sha256", principal["metadata"])
            self.assertNotIn("geometry_fingerprint", principal["metadata"])
            self.assertNotIn(b"valor-privado-de-prueba", ruta.read_bytes())
            self.assertNotIn(b"valor-privado-de-prueba", ruta_vinculo(ruta).read_bytes())

    def test_rechaza_reuso_con_otras_dimensiones_aunque_conserven_aspecto(self):
        frame, _ = crear_frame_lineal()
        calibracion = generar_candidato_automatico(frame).calibracion
        origen = "http://127.0.0.1:4747/video"
        identidad = identidad_fuente("http", origen)
        calibracion.metadata["fuente_sha256"] = identidad
        with tempfile.TemporaryDirectory() as directorio:
            ruta = Path(directorio) / "zones.json"
            guardar_calibracion(ruta, calibracion, "http")
            from configuracion_local import guardar_vinculo
            guardar_vinculo(ruta, "http", origen, ANCHO, ALTO)
            with self.assertRaisesRegex(ValueError, "vinculo de fuente valido"):
                verificar_vinculo(ruta, "http", origen, 1280, 720)

    def test_espera_headless_hasta_calibracion_y_rechaza_arranque_grafico(self):
        from detect import esperar_calibracion_valida, parse_args

        with patch("detect.validar_calibracion_permanente", side_effect=[ValueError("pendiente"), None]):
            with patch("detect.resolver_url_http", return_value="http://127.0.0.1:4747/video"):
                with patch("detect.time.sleep") as dormir:
                    self.assertTrue(esperar_calibracion_valida(Path("zones.json"), pausa=2.0))
        dormir.assert_called_once_with(2.0)
        with patch.object(sys, "argv", ["detect.py", "--wait-for-calibration"]):
            with self.assertRaises(SystemExit):
                parse_args()

    def test_referencias_locales_solo_prueban_geometria_offline(self):
        raiz = Path(__file__).resolve().parents[1]
        for nombre in ("estacionamiento-prueba.png", "parking_test_reference.png"):
            imagen = cv2.imread(str(raiz / nombre), cv2.IMREAD_COLOR)
            self.assertIsNotNone(imagen, nombre)
            resultado = generar_candidato_automatico(imagen)
            self.assertEqual(set(resultado.calibracion.zonas), {f"C{n}" for n in range(1, 9)})


if __name__ == "__main__":
    unittest.main()
