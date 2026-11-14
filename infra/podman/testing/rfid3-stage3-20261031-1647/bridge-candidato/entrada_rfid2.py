"""Procesa el canal operativo de entrada RFID 2."""

import re


PATRON_TRAMA = re.compile(
    r"RFID2,([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}),"
    r"([0-9A-Fa-f]{8}|[0-9A-Fa-f]{14}|[0-9A-Fa-f]{20})\Z"
)


def procesar_trama_entrada_rfid2(linea, cliente, puerto):
    """Responde únicamente con la decisión confirmada por la API."""
    coincidencia = PATRON_TRAMA.fullmatch(linea)
    if coincidencia is None:
        print("Se ignoró una trama RFID 2 mal formada.")
        return
    lectura_id, uid = coincidencia.groups()
    lectura_id = lectura_id.lower()
    try:
        resultado = cliente.registrar_entrada_rfid2(uid.upper(), lectura_id)
    except Exception:
        resultado = "DENEGADA"
    if resultado not in ("AUTORIZADA", "DENEGADA"):
        resultado = "DENEGADA"
    puerto.escribir_linea(
        "RFID2_RESULT,{},{}".format(lectura_id, resultado)
    )
    print("Decisión RFID 2 enviada: {}.".format(resultado))
