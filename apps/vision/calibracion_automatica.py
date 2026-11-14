"""Propone zonas para los cajones a partir de las líneas visibles en la imagen."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Callable

import cv2
import numpy as np

from calibracion_zonas import CalibracionZonas
from temporal_validation import ParkingZone


@dataclass(frozen=True)
class LineaDetectada:
    """Describe una línea visible y qué tan segura fue su detección."""

    posicion: float
    pendiente: float
    intercepto: float
    confianza: float


@dataclass(frozen=True)
class EvidenciaZona:
    """Reúne qué tan visibles son los bordes de una zona y si coincide con la anterior."""

    etiqueta: str
    confianza: float
    bordes: tuple[float, float, float, float]
    cambio_geometrico: float | None
    diagnostico: str


@dataclass(frozen=True)
class ResultadoCalibracionAutomatica:
    """Reúne las zonas propuestas y los datos que permiten revisarlas antes de guardarlas."""

    calibracion: CalibracionZonas
    evidencias: tuple[EvidenciaZona, ...]


class ErrorCalibracionAutomatica(ValueError):
    """Explica por qué no se pudo preparar o aceptar una propuesta de zonas."""

    def __init__(self, motivo: str, zonas_afectadas: tuple[str, ...] = ()) -> None:
        super().__init__(motivo)
        self.zonas_afectadas = zonas_afectadas


def generar_candidato_automatico(
    imagen: np.ndarray,
    calibracion_actual: CalibracionZonas | None = None,
    *,
    confianza_minima: float = 0.45,
) -> ResultadoCalibracionAutomatica:
    """Busca las líneas de dos filas y propone ocho zonas para los cajones.

    Conserva las identidades anteriores y mantiene las zonas adicionales.
    Rechaza la propuesta si los bordes no se ven con claridad o una zona deja
    de corresponder a la que estaba guardada.
    """

    if (not isinstance(imagen, np.ndarray) or imagen.ndim != 3
            or imagen.shape[2] not in (3, 4) or min(imagen.shape[:2]) < 120):
        raise ErrorCalibracionAutomatica("Se requiere un frame BGR valido de al menos 120 px.")
    if not 0.0 <= confianza_minima <= 1.0:
        raise ValueError("La confianza minima debe quedar entre 0 y 1.")

    alto, ancho = imagen.shape[:2]
    gris = cv2.cvtColor(imagen, cv2.COLOR_BGRA2GRAY if imagen.shape[2] == 4 else cv2.COLOR_BGR2GRAY)
    gris = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gris)
    bordes = cv2.Canny(cv2.GaussianBlur(gris, (5, 5), 0), 45, 140)
    lineas = cv2.HoughLinesP(
        bordes,
        1,
        np.pi / 180,
        threshold=max(20, int(min(ancho, alto) * 0.03)),
        minLineLength=max(24, int(min(ancho, alto) * 0.035)),
        maxLineGap=max(8, int(min(ancho, alto) * 0.025)),
    )
    if lineas is None:
        raise ErrorCalibracionAutomatica("Canny/Hough no encontro bordes de estacionamiento.")

    segmentos = [tuple(int(valor) for valor in linea) for linea in lineas[:, 0]]
    limites_filas = _detectar_limites_filas(segmentos, ancho, alto)
    divisores_por_fila = []
    for indice_fila, (superior, inferior) in enumerate(limites_filas):
        try:
            divisores_por_fila.append(
                _detectar_divisores(segmentos, ancho, alto, superior, inferior)
            )
        except ErrorCalibracionAutomatica as error:
            inicio = indice_fila * 4 + 1
            afectadas = tuple(f"C{numero}" for numero in range(inicio, inicio + 4))
            raise ErrorCalibracionAutomatica(
                f"Fila {indice_fila + 1}: {error}", afectadas,
            ) from error
    divisores_por_fila = tuple(divisores_por_fila)
    candidato = _crear_geometria(limites_filas, divisores_por_fila, ancho, alto)

    zonas = candidato.zonas
    identidades = candidato.vision_zone_ids
    evidencias: list[EvidenciaZona] = []
    zonas_debilitadas: list[str] = []
    limites_debilitados: list[str] = []
    for indice in range(8):
        etiqueta = f"C{indice + 1}"
        fila = 0 if indice < 4 else 1
        columna = indice % 4
        horizontal_superior = limites_filas[fila][0]
        horizontal_inferior = limites_filas[fila][1]
        divisor_izquierdo = divisores_por_fila[fila][columna]
        divisor_derecho = divisores_por_fila[fila][columna + 1]
        confianza_bordes = (
            horizontal_superior.confianza,
            divisor_derecho.confianza,
            horizontal_inferior.confianza,
            divisor_izquierdo.confianza,
        )
        confianza = float(sum(confianza_bordes) / len(confianza_bordes))
        anterior = calibracion_actual.zonas.get(etiqueta) if calibracion_actual else None
        cambio = None
        diagnostico = "Cuatro bordes visibles y cuadrilatero convexo."
        nombres_bordes = ("superior", "derecho", "inferior", "izquierdo")
        bajos = [
            nombre for nombre, valor in zip(nombres_bordes, confianza_bordes)
            if valor < confianza_minima * 0.45
        ]
        if confianza < confianza_minima or bajos:
            zonas_debilitadas.append(etiqueta)
            limites_debilitados.extend(f"{etiqueta}/{nombre}" for nombre in bajos)
            diagnostico = "Limites con soporte visual insuficiente: " + ", ".join(bajos or nombres_bordes)
        if anterior is not None:
            cambio = _distancia_geometrica(anterior, zonas[etiqueta], ancho, alto)
            solape = _solape_relativo(anterior, zonas[etiqueta])
            if solape < 0.45:
                zonas_debilitadas.append(etiqueta)
                diagnostico = "No se confirma que el candidato corresponda al mismo cajon anterior."
            elif cambio > 0.01:
                diagnostico = (
                    f"Limite corregido con soporte visual; distancia maxima {cambio:.2%} "
                    "de la diagonal y correspondencia espacial conservada."
                )
        evidencias.append(EvidenciaZona(etiqueta, confianza, confianza_bordes, cambio, diagnostico))

    if zonas_debilitadas:
        afectadas = tuple(dict.fromkeys(zonas_debilitadas))
        detalle_limites = (
            " Limites: " + ", ".join(dict.fromkeys(limites_debilitados)) + "."
            if limites_debilitados else ""
        )
        raise ErrorCalibracionAutomatica(
            "No se guarda el candidato: revise enfoque o geometria en "
            + ", ".join(afectadas) + "." + detalle_limites,
            afectadas,
        )

    if calibracion_actual is not None:
        for etiqueta, zona in calibracion_actual.zonas.items():
            zonas.setdefault(etiqueta, zona)
        for etiqueta in zonas:
            if etiqueta in calibracion_actual.vision_zone_ids:
                identidades[etiqueta] = calibracion_actual.vision_zone_ids[etiqueta]
    metadatos = dict(calibracion_actual.metadata if calibracion_actual else {})
    metadatos["confianza_zonas"] = {
        evidencia.etiqueta: round(evidencia.confianza, 4) for evidencia in evidencias
    }
    metadatos["limites_zonas"] = {
        evidencia.etiqueta: [round(valor, 4) for valor in evidencia.bordes]
        for evidencia in evidencias
    }
    siguiente = max(9, calibracion_actual.next_c_number if calibracion_actual else 9)
    calibracion = CalibracionZonas(
        ancho,
        alto,
        zonas=zonas,
        next_c_number=siguiente,
        vision_zone_ids=identidades,
        metadata=metadatos,
    )
    return ResultadoCalibracionAutomatica(calibracion, tuple(evidencias))


def _angulo(segmento: tuple[int, int, int, int]) -> tuple[float, float]:
    x1, y1, x2, y2 = segmento
    dx, dy = x2 - x1, y2 - y1
    return abs(float(np.degrees(np.arctan2(dy, dx)))), float(np.hypot(dx, dy))


def _y_en_x(segmento: tuple[int, int, int, int], x: float) -> float:
    """Calcula la altura de una línea en una posición para poder compararla con otras."""

    x1, y1, x2, y2 = segmento
    if x2 == x1:
        return (y1 + y2) / 2
    return y1 + (y2 - y1) * (x - x1) / (x2 - x1)


def _agrupar_segmentos(
    segmentos: list[tuple[int, int, int, int]],
    posicion: Callable[[tuple[int, int, int, int]], float],
    tolerancia: float,
    eje: str,
    centro: float,
    longitud_referencia: float,
) -> list[LineaDetectada]:
    elementos = sorted(((posicion(segmento), segmento) for segmento in segmentos), key=lambda par: par[0])
    grupos: list[list[tuple[float, tuple[int, int, int, int]]]] = []
    for elemento in elementos:
        if not grupos:
            grupos.append([elemento])
            continue

        valores = [valor for valor, _ in grupos[-1]]
        valores_con_candidato = [*valores, elemento[0]]
        representante = float(np.median(valores_con_candidato))
        dispersion = max(abs(valor - representante) for valor in valores_con_candidato)
        if dispersion <= tolerancia:
            grupos[-1].append(elemento)
        else:
            grupos.append([elemento])

    lineas = []
    for grupo in grupos:
        puntos = np.array(
            [(x, y) for _, (x1, y1, x2, y2) in grupo for x, y in ((x1, y1), (x2, y2))],
            dtype=np.float32,
        )
        ajuste = np.asarray(
            cv2.fitLine(puntos, cv2.DIST_L2, 0, 0.01, 0.01),
            dtype=np.float64,
        ).reshape(-1)
        if ajuste.size != 4:
            raise ErrorCalibracionAutomatica("OpenCV devolvio una linea con forma invalida.")
        vx, vy, x0, y0 = (float(valor) for valor in ajuste)
        if eje == "horizontal":
            if abs(vx) < 0.05:
                continue
            pendiente = vy / vx
            intercepto = y0 - pendiente * x0
            posicion_central = pendiente * centro + intercepto
        else:
            if abs(vy) < 0.05:
                continue
            pendiente = vx / vy
            intercepto = x0 - pendiente * y0
            posicion_central = pendiente * centro + intercepto
        soporte = sum(_angulo(segmento)[1] for _, segmento in grupo)
        confianza = min(1.0, soporte / (longitud_referencia * 0.72))
        lineas.append(LineaDetectada(posicion_central, pendiente, intercepto, confianza))
    return sorted(lineas, key=lambda linea: linea.posicion)


def _detectar_limites_filas(
    segmentos: list[tuple[int, int, int, int]], ancho: int, alto: int
) -> tuple[tuple[LineaDetectada, LineaDetectada], tuple[LineaDetectada, LineaDetectada]]:
    horizontales = []
    for segmento in segmentos:
        angulo, longitud = _angulo(segmento)
        angulo = min(angulo, 180.0 - angulo)
        # Los coches pueden tapar las líneas de los cajones. Se agrupan sus
        # partes visibles y se comprueba que las líneas divisorias las alcancen.
        if angulo <= 18.0 and longitud >= max(40.0, ancho * 0.07):
            horizontales.append(segmento)
    lineas = _agrupar_segmentos(
        horizontales, lambda segmento: _y_en_x(segmento, (ancho - 1) / 2), alto * 0.018,
        "horizontal", ancho / 2, ancho,
    )
    candidatas = [linea for linea in lineas if alto * 0.06 < linea.posicion < alto * 0.96]
    pares = []
    for superior, inferior in combinations(candidatas, 2):
        altura_fila = inferior.posicion - superior.posicion
        if not alto * 0.09 <= altura_fila <= alto * 0.42:
            continue
        try:
            divisores = _detectar_divisores(
                segmentos, ancho, alto, superior, inferior,
            )
            soporte_superior = _contar_intersecciones_visibles(
                segmentos, superior, divisores, ancho, alto,
            )
            soporte_inferior = _contar_intersecciones_visibles(
                segmentos, inferior, divisores, ancho, alto,
            )
        except ErrorCalibracionAutomatica:
            continue
        # Cada borde debe alcanzar al menos una línea divisoria. Las demás
        # partes visibles ayudan a elegir las dos filas que mejor coinciden.
        if min(soporte_superior, soporte_inferior) < 1:
            continue
        puntaje = sum(linea.confianza for linea in (superior, inferior))
        puntaje += 0.35 * sum(linea.confianza for linea in divisores)
        puntaje += 1.5 * float(soporte_superior + soporte_inferior)
        pares.append((superior, inferior, puntaje))

    mejor = None
    mejor_puntaje = -1.0
    for primero, segundo in combinations(pares, 2):
        fila_superior, fila_inferior = sorted(
            (primero, segundo), key=lambda fila: fila[0].posicion,
        )
        inicio_superior, fin_superior, puntaje_superior = fila_superior
        inicio_inferior, fin_inferior, puntaje_inferior = fila_inferior
        y0, y1 = inicio_superior.posicion, fin_superior.posicion
        y2, y3 = inicio_inferior.posicion, fin_inferior.posicion
        alturas = (y1 - y0, y3 - y2)
        espacio = y2 - y1
        if y0 > alto * 0.44 or y2 < alto * 0.43:
            continue
        if not alto * 0.05 <= espacio <= alto * 0.50:
            continue
        puntaje = puntaje_superior + puntaje_inferior
        puntaje -= abs(alturas[0] - alturas[1]) / alto * 0.20
        if puntaje > mejor_puntaje:
            mejor = (inicio_superior, fin_superior, inicio_inferior, fin_inferior)
            mejor_puntaje = puntaje
    if mejor is None:
        raise ErrorCalibracionAutomatica(
            "No se encontraron dos filas con cinco divisores y soporte visible en ambos limites."
        )
    return ((mejor[0], mejor[1]), (mejor[2], mejor[3]))


def _contar_intersecciones_visibles(
    segmentos: list[tuple[int, int, int, int]],
    horizontal: LineaDetectada,
    divisores: tuple[LineaDetectada, ...],
    ancho: int,
    alto: int,
) -> int:
    """Cuenta cuántas líneas divisorias visibles alcanzan el borde de la fila."""

    tolerancia_y = max(10.0, alto * 0.04)
    tolerancia_x = max(12.0, ancho * 0.025)
    visibles = 0
    for divisor in divisores:
        interseccion_x, interseccion_y = _interseccion(horizontal, divisor)
        soportada = False
        for x1, y1, x2, y2 in segmentos:
            angulo, _ = _angulo((x1, y1, x2, y2))
            if angulo > 90.0:
                angulo = 180.0 - angulo
            if angulo < 66.0 or y1 == y2:
                continue
            minimo_y, maximo_y = sorted((float(y1), float(y2)))
            y_cercana = min(max(interseccion_y, minimo_y), maximo_y)
            if abs(y_cercana - interseccion_y) > tolerancia_y:
                continue
            x_cercana = x1 + (x2 - x1) * (y_cercana - y1) / (y2 - y1)
            if abs(x_cercana - interseccion_x) <= tolerancia_x:
                soportada = True
                break
        visibles += int(soportada)
    return visibles


def _detectar_divisores(
    segmentos: list[tuple[int, int, int, int]], ancho: int, alto: int,
    superior: LineaDetectada, inferior: LineaDetectada,
) -> tuple[LineaDetectada, ...]:
    y_inicio = max(0.0, superior.posicion)
    y_final = min(float(alto), inferior.posicion)
    altura_fila = y_final - y_inicio
    centro = (y_inicio + y_final) / 2
    verticales = []
    for segmento in segmentos:
        angulo, longitud = _angulo(segmento)
        if angulo > 90:
            angulo = 180 - angulo
        x1, y1, x2, y2 = segmento
        y_menor, y_mayor = sorted((y1, y2))
        solape = max(0.0, min(y_mayor, y_final) - max(y_menor, y_inicio))
        if angulo >= 66 and longitud >= altura_fila * 0.20 and solape >= altura_fila * 0.16:
            verticales.append(segmento)
    lineas = _agrupar_segmentos(
        verticales,
        lambda s: s[0] + (s[2] - s[0]) * (centro - s[1]) / (s[3] - s[1]) if s[3] != s[1] else s[0],
        ancho * 0.035,
        "vertical",
        centro,
        altura_fila,
    )
    lineas = [linea for linea in lineas if ancho * 0.015 < linea.posicion < ancho * 0.985]
    mejor = None
    mejor_puntaje = -1.0
    candidatas = sorted(lineas, key=lambda linea: linea.confianza, reverse=True)[:24]
    for seleccion in combinations(sorted(candidatas, key=lambda linea: linea.posicion), 5):
        posiciones = [linea.posicion for linea in seleccion]
        separaciones = [derecha - izquierda for izquierda, derecha in zip(posiciones, posiciones[1:])]
        if posiciones[-1] - posiciones[0] < ancho * 0.65:
            continue
        if min(separaciones) < ancho * 0.055 or max(separaciones) > ancho * 0.38:
            continue
        if max(separaciones) / min(separaciones) > 3.2:
            continue
        promedio = sum(separaciones) / len(separaciones)
        variacion = sum(abs(valor - promedio) for valor in separaciones) / promedio
        puntaje = sum(linea.confianza for linea in seleccion) + (posiciones[-1] - posiciones[0]) / ancho
        puntaje -= variacion * 0.15
        if puntaje > mejor_puntaje:
            mejor, mejor_puntaje = seleccion, puntaje
    if mejor is None:
        raise ErrorCalibracionAutomatica(
            "No se detectaron cinco lineas de division con soporte suficiente.",
        )
    return tuple(mejor)


def _interseccion(horizontal: LineaDetectada, vertical: LineaDetectada) -> tuple[float, float]:
    denominador = 1.0 - horizontal.pendiente * vertical.pendiente
    if abs(denominador) < 0.05:
        raise ErrorCalibracionAutomatica("Dos limites casi paralelos no forman una zona valida.")
    x = (vertical.pendiente * horizontal.intercepto + vertical.intercepto) / denominador
    return x, horizontal.pendiente * x + horizontal.intercepto


def _crear_geometria(limites, divisores_por_fila, ancho: int, alto: int) -> CalibracionZonas:
    zonas = {}
    for fila, (superior, inferior) in enumerate(limites):
        divisores = divisores_por_fila[fila]
        for columna in range(4):
            puntos = (
                _interseccion(superior, divisores[columna]),
                _interseccion(superior, divisores[columna + 1]),
                _interseccion(inferior, divisores[columna + 1]),
                _interseccion(inferior, divisores[columna]),
            )
            poligono = tuple((x / (ancho - 1), y / (alto - 1)) for x, y in puntos)
            etiqueta = f"C{fila * 4 + columna + 1}"
            try:
                zonas[etiqueta] = ParkingZone(etiqueta, poligono)
            except ValueError as error:
                raise ErrorCalibracionAutomatica(
                    f"El limite de {etiqueta} genera un poligono invalido: {error}", (etiqueta,),
                ) from error
    _validar_solapamientos(zonas)
    return CalibracionZonas(ancho, alto, zonas=zonas, next_c_number=9)


def _validar_solapamientos(zonas: dict[str, ParkingZone]) -> None:
    poligonos = {
        etiqueta: np.asarray([(x, y) for x, y in zona.polygon], dtype=np.float32)
        for etiqueta, zona in zonas.items()
    }
    areas = {etiqueta: abs(cv2.contourArea(puntos)) for etiqueta, puntos in poligonos.items()}
    for primero, segundo in combinations(sorted(zonas), 2):
        interseccion, _ = cv2.intersectConvexConvex(poligonos[primero], poligonos[segundo])
        proporcion = interseccion / max(1e-9, min(areas[primero], areas[segundo]))
        indice_primero = int(primero[1:]) - 1
        indice_segundo = int(segundo[1:]) - 1
        misma_fila = indice_primero // 4 == indice_segundo // 4
        vecinos = misma_fila and abs(indice_primero - indice_segundo) == 1
        limite = 0.02 if vecinos else 0.0
        if proporcion > limite:
            raise ErrorCalibracionAutomatica(
                f"Solape de {proporcion:.2%} entre {primero} y {segundo}; revise esos limites.",
                (primero, segundo),
            )


def _distancia_geometrica(anterior: ParkingZone, candidato: ParkingZone, ancho: int, alto: int) -> float:
    distancias = [
        np.hypot((x1 - x2) * ancho, (y1 - y2) * alto) / np.hypot(ancho, alto)
        for (x1, y1), (x2, y2) in zip(anterior.polygon, candidato.polygon)
    ]
    return float(max(distancias))


def _solape_relativo(anterior: ParkingZone, candidato: ParkingZone) -> float:
    poligonos = [
        np.asarray([(x, y) for x, y in zona.polygon], dtype=np.float32)
        for zona in (anterior, candidato)
    ]
    areas = [abs(cv2.contourArea(poligono)) for poligono in poligonos]
    interseccion, _ = cv2.intersectConvexConvex(poligonos[0], poligonos[1])
    return float(interseccion / max(1e-9, min(areas)))
