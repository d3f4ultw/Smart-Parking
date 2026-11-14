"""envía al servicio las solicitudes de entrada RFID 2 que recibe de la placa ESP32 y le devuelve la decisión confirmada"""

import re
import time

from cliente_smartparking import ErrorApi


PATRON_TRAMA = re.compile(
    r"RFID2,([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}),"
    r"([0-9A-Fa-f]{8}|[0-9A-Fa-f]{14}|[0-9A-Fa-f]{20})\Z"
)


def procesar_trama_entrada_rfid2(linea, cliente, puerto):
    """envía el código de tarjeta al servicio y comunica solo su decisión confirmada; si algo falla, deniega la entrada"""
    coincidencia = PATRON_TRAMA.fullmatch(linea)
    if coincidencia is None:
        print("Se ignoró una trama RFID 2 mal formada.")
        return
    lectura_id, uid = coincidencia.groups()
    lectura_id = lectura_id.lower()
    inicio = time.monotonic()
    origen = "API"
    estado_http = None
    try:
        resultado = cliente.registrar_entrada_rfid2(uid.upper(), lectura_id)
    except ErrorApi as error:
        resultado = "DENEGADA"
        estado_http = error.estado_http
        origen = error.origen or (
            "HTTP" if estado_http is not None else "RESPUESTA_INVALIDA"
        )
    except Exception:
        resultado = "DENEGADA"
        origen = "ERROR_INTERNO"
    if resultado not in ("AUTORIZADA", "DENEGADA"):
        resultado = "DENEGADA"
        origen = "RESPUESTA_INVALIDA"
    puerto.escribir_linea(
        "RFID2_RESULT,{},{}".format(lectura_id, resultado)
    )
    duracion_ms = round((time.monotonic() - inicio) * 1000)
    if origen == "API":
        print("RFID2: API confirmó {} en {} ms.".format(resultado, duracion_ms))
    elif origen == "COMUNICACION":
        print("RFID2: sin respuesta API (timeout/comunicación); cierre seguro en {} ms."
              .format(duracion_ms))
    elif origen == "HTTP":
        print("RFID2: HTTP {} sin decisión confirmada; cierre seguro en {} ms."
              .format(estado_http, duracion_ms))
    else:
        print("RFID2: sin decisión API confirmada ({}); cierre seguro en {} ms."
              .format(origen.lower(), duracion_ms))
