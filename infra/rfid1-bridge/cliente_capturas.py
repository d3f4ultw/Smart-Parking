"""consulta al servicio local las capturas RFID 1 y envía solicitudes de entrada, salida y salida manual"""

import json
import re
import time
import urllib.parse
import uuid

from cliente_smartparking import (
    CODIGOS_REINTENTABLES,
    ClienteSmartParking,
    ErrorApi,
    PATRON_UID,
)


RUTA_CAPTURA_ACTIVA = "/api/v1/dispositivos/rfid-1/capturas/activa"
RUTA_LECTURAS = "/api/v1/dispositivos/rfid-1/lecturas"
RUTA_ESTADO_DISPOSITIVO = "/api/v1/dispositivos/rfid-1/estado"
RUTA_ENTRADAS_RFID2 = "/api/v1/dispositivos/rfid-2/entradas"
RUTA_SALIDAS_RFID3 = "/api/v1/dispositivos/rfid-3/salidas"
RUTA_SALIDAS_MANUALES = "/api/v1/dispositivos/rfid-3/salidas-manuales"
PATRON_TOKEN_MANUAL = re.compile(r"[A-Za-z0-9_-]{21}[AQgw]\Z")
PATRON_FIRMA_MANUAL = re.compile(r"[A-Za-z0-9_-]{16}\Z")
PATRON_CAPTURA = re.compile(r"[0-9a-f]{32}\Z")
PATRON_SOLICITUD = re.compile(r"[0-9A-Fa-f]{1,4}\Z")
PATRON_UUID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z"
)


class ClienteCapturas(ClienteSmartParking):
    """comparte la conexión local con el servicio para consultar capturas y enviar entradas y salidas RFID"""

    def consultar_captura_activa(self):
        """devuelve la captura activa o indica que no hay ninguna"""
        estado_http, contenido = self._solicitar(
            "GET", RUTA_CAPTURA_ACTIVA, None, (200, 204)
        )
        if estado_http == 204:
            return None
        respuesta = self._decodificar_json(contenido)
        captura_id = respuesta.get("capturaId")
        estado = respuesta.get("estado")
        expira_en = respuesta.get("expiraEn")
        if (
            set(respuesta) != {"capturaId", "estado", "expiraEn"}
            or not isinstance(captura_id, str)
            or PATRON_CAPTURA.fullmatch(captura_id) is None
            or estado not in ("PENDIENTE", "ESCANEANDO", "VISTA_PREVIA")
            or not isinstance(expira_en, str)
            or not expira_en
            or len(expira_en) > 64
        ):
            raise ErrorApi("La respuesta de captura RFID 1 no es válida.")
        return {"capturaId": captura_id, "estado": estado}

    def informar_escaneando(self, captura_id):
        """pide al servicio que marque la captura como en lectura antes de activar el lector"""
        self._validar_captura(captura_id)
        ruta = RUTA_CAPTURA_ACTIVA.rsplit("/", 1)[0]
        ruta += "/{}/estado".format(captura_id)
        _, contenido = self._solicitar(
            "POST", ruta, {"estado": "ESCANEANDO"}, (204,)
        )
        return contenido

    def informar_estado_dispositivo(self, conectado):
        if type(conectado) is not bool:
            raise ValueError("El estado RFID debe ser booleano.")
        self._solicitar(
            "POST", RUTA_ESTADO_DISPOSITIVO, {"conectado": conectado}, (204,)
        )

    def enviar_lectura_capturada(self, captura_id, request_id, uid):
        """mantiene el mismo identificador al repetir la lectura para que el servicio la reconozca"""
        self._validar_captura(captura_id)
        if (
            not isinstance(request_id, str)
            or PATRON_SOLICITUD.fullmatch(request_id) is None
            or not isinstance(uid, str)
            or PATRON_UID.fullmatch(uid) is None
        ):
            raise ValueError("La lectura de captura RFID 1 no es válida.")
        solicitud = request_id.upper()
        clave = str(uuid.uuid5(uuid.UUID(captura_id), solicitud))
        cuerpo = {
            "capturaId": captura_id,
            "requestId": solicitud,
            "uid": uid.upper(),
        }
        estado_http, contenido = self._solicitar(
            "POST", RUTA_LECTURAS, cuerpo, (200, 409), clave
        )
        respuesta = self._decodificar_json(contenido)
        if estado_http == 409:
            if (
                respuesta.get("codigo") != "TARJETA_YA_REGISTRADA"
                or set(respuesta) not in (
                    {"codigo", "error"},
                    {"codigo", "mensaje"},
                )
            ):
                raise ErrorApi("La API RFID 1 rechazó la lectura.", 409)
            return {
                "capturaId": captura_id,
                "estado": "ESCANEANDO",
                "resultado": "TARJETA_YA_REGISTRADA",
            }
        if respuesta != {
            "capturaId": captura_id,
            "estado": "VISTA_PREVIA",
            "resultado": "PREVIEW_READY",
        }:
            raise ErrorApi("La API RFID 1 no confirmó la vista previa.")
        return respuesta

    def registrar_entrada_rfid2(self, uid, lectura_id):
        """envía la entrada con el mismo identificador al repetirla y devuelve solo la decisión confirmada"""
        if not isinstance(uid, str) or PATRON_UID.fullmatch(uid) is None:
            raise ValueError("La lectura RFID 2 no es válida.")
        if not isinstance(lectura_id, str) or PATRON_UUID.fullmatch(lectura_id) is None:
            raise ValueError("La lectura RFID 2 no es válida.")
        lectura_id = str(uuid.UUID(lectura_id))
        estado_http, contenido = self._solicitar(
            "POST",
            RUTA_ENTRADAS_RFID2,
            {"uid": uid.upper(), "lecturaId": lectura_id},
            (200,),
            lectura_id,
        )
        respuesta = self._decodificar_json(contenido)
        if (
            respuesta.get("resultado") == "AUTORIZADA"
            and set(respuesta) in ({"resultado"}, {"resultado", "motivo"})
            and respuesta.get("motivo") is None
        ):
            return "AUTORIZADA"
        if (
            set(respuesta) == {"resultado", "motivo"}
            and respuesta.get("resultado") == "DENEGADA"
            and respuesta.get("motivo") in (
                "TARJETA_DESCONOCIDA", "TARJETA_CANCELADA", "ENTRADA_PENDIENTE",
                "FUERA_DE_HORARIO", "CAPACIDAD_COMPLETA", "MEMBRESIA_NO_VIGENTE"
            )
        ):
            return "DENEGADA"
        raise ErrorApi("La API no confirmó la decisión RFID 2.", estado_http)

    def registrar_salida_rfid3(self, uid, lectura_id):
        """envía el mismo identificador en cada intento y devuelve solo una decisión válida del servicio"""
        if not isinstance(uid, str) or PATRON_UID.fullmatch(uid) is None:
            raise ValueError("La lectura RFID 3 no es válida.")
        if not isinstance(lectura_id, str) or PATRON_UUID.fullmatch(lectura_id) is None:
            raise ValueError("La lectura RFID 3 no es válida.")
        lectura_id = str(uuid.UUID(lectura_id))
        estado, contenido = self._solicitar(
            "POST", RUTA_SALIDAS_RFID3,
            {"uid": uid.upper(), "lecturaId": lectura_id}, (200,)
        )
        respuesta = self._decodificar_json(contenido)
        if respuesta == {"resultado": "AUTORIZADA"}:
            return "AUTORIZADA"
        if (set(respuesta) == {"resultado", "motivo"}
                and respuesta.get("resultado") == "DENEGADA"
                and respuesta.get("motivo") in (
                    "TARJETA_DESCONOCIDA", "TARJETA_CANCELADA", "SIN_ENTRADA_ABIERTA",
                    "SALIDA_MANUAL_EN_CURSO"
                )):
            return "DENEGADA"
        raise ErrorApi("La API no confirmó la decisión RFID 3.", estado)

    def consultar_salida_manual(self, despues=None):
        """busca la siguiente salida manual y recupera los datos necesarios para averiguar qué ocurrió"""
        ruta = RUTA_SALIDAS_MANUALES + "/pendiente"
        if despues is not None:
            if not isinstance(despues, str) or PATRON_UUID.fullmatch(despues) is None:
                raise ValueError("El cursor de salida manual no es válido.")
            ruta += "?" + urllib.parse.urlencode({"despues": str(uuid.UUID(despues))})
        estado, contenido = self._solicitar(
            "GET", ruta, None, (200, 204)
        )
        if estado == 204:
            return None
        respuesta = self._decodificar_json(contenido)
        operacion = respuesta.get("operacionId")
        estado = respuesta.get("estado")
        if not isinstance(operacion, str) or PATRON_UUID.fullmatch(operacion) is None:
            raise ErrorApi("La operación manual recibida no es válida.")
        if estado == "PENDIENTE" and set(respuesta) == {"operacionId", "estado"}:
            return {"operacionId": str(uuid.UUID(operacion)), "estado": estado}
        boot = respuesta.get("bootId")
        ticket = respuesta.get("ticketId")
        if (estado in ("EMITIDA", "INCIERTA")
                and set(respuesta) == {"operacionId", "estado", "bootId", "ticketId"}
                and isinstance(boot, str) and PATRON_TOKEN_MANUAL.fullmatch(boot)
                and isinstance(ticket, str) and PATRON_TOKEN_MANUAL.fullmatch(ticket)):
            return {"operacionId": str(uuid.UUID(operacion)), "estado": estado,
                    "bootId": boot, "ticketId": ticket}
        raise ErrorApi("La operación manual recibida no es válida.")

    def solicitar_desafio_salida_manual(self):
        """pide un código temporal para comprobar que la placa ESP32 responde a la prueba previa de salida manual"""
        _, contenido = self._solicitar(
            "GET", RUTA_SALIDAS_MANUALES + "/capacidad/desafio", None, (200,)
        )
        respuesta = self._decodificar_json(contenido)
        desafio = respuesta.get("desafioId")
        if (set(respuesta) != {"desafioId"} or not isinstance(desafio, str)
                or PATRON_TOKEN_MANUAL.fullmatch(desafio) is None):
            raise ErrorApi("El desafío de capacidad manual no es válido.")
        return desafio

    def confirmar_capacidad_salida_manual(self, desafio, boot, firma):
        """envía al servicio el código temporal y la respuesta de la placa ESP32 para que confirme que la salida manual está disponible"""
        if (not isinstance(desafio, str) or PATRON_TOKEN_MANUAL.fullmatch(desafio) is None
                or not isinstance(boot, str) or PATRON_TOKEN_MANUAL.fullmatch(boot) is None
                or not isinstance(firma, str) or PATRON_FIRMA_MANUAL.fullmatch(firma) is None):
            raise ValueError("La respuesta de capacidad manual no es válida.")
        self._solicitar("POST", RUTA_SALIDAS_MANUALES + "/capacidad",
                        {"desafioId": desafio, "bootId": boot, "firma": firma}, (204,))

    def invalidar_capacidad_salida_manual(self):
        """avisa al servicio que la comprobación anterior ya no debe considerarse válida"""
        self._solicitar("POST", RUTA_SALIDAS_MANUALES + "/capacidad", {"conectado": False}, (204,))

    def emitir_salida_manual(self, operacion, boot, ticket):
        """solicita autorización y devuelve el permiso que la placa ESP32 necesita para ejecutar una salida manual"""
        self._validar_salida_manual(operacion, boot)
        if not isinstance(ticket, str) or PATRON_TOKEN_MANUAL.fullmatch(ticket) is None:
            raise ValueError("El ticket manual no es válido.")
        _, contenido = self._solicitar(
            "POST", RUTA_SALIDAS_MANUALES + "/{}/emitir".format(operacion),
            {"bootId": boot, "ticketId": ticket}, (200,)
        )
        respuesta = self._decodificar_json(contenido)
        firma = respuesta.get("firma")
        if (set(respuesta) != {"autorizada", "firma"} or respuesta.get("autorizada") is not True
                or not isinstance(firma, str) or PATRON_FIRMA_MANUAL.fullmatch(firma) is None):
            raise ErrorApi("La API no confirmó el permiso manual.")
        return firma

    def informar_resultado_salida_manual(self, operacion, boot, ticket, resultado, firma):
        """envía el resultado informado por la placa ESP32; repetir la solicitud no ejecuta otra vez la salida"""
        self._validar_salida_manual(operacion, boot)
        if resultado not in ("EJECUTADA", "NO_EJECUTADA"):
            raise ValueError("El resultado manual no es válido.")
        if (not isinstance(ticket, str) or PATRON_TOKEN_MANUAL.fullmatch(ticket) is None
                or not isinstance(firma, str) or PATRON_FIRMA_MANUAL.fullmatch(firma) is None):
            raise ValueError("El resultado manual no es válido.")
        _, contenido = self._solicitar(
            "POST", RUTA_SALIDAS_MANUALES + "/{}/resultado".format(operacion),
            {"bootId": boot, "ticketId": ticket, "resultado": resultado, "firma": firma}, (200,)
        )
        respuesta = self._decodificar_json(contenido)
        if (respuesta.get("operacionId") != operacion
                or respuesta.get("estado") not in ("CONFIRMADA", "NO_EJECUTADA", "ANULADA")
                or not isinstance(respuesta.get("movimientoId"), (str, int))):
            raise ErrorApi("La API no confirmó el resultado manual.")
        return respuesta

    @staticmethod
    def _validar_salida_manual(operacion, boot):
        if (not isinstance(operacion, str) or PATRON_UUID.fullmatch(operacion) is None
                or not isinstance(boot, str) or PATRON_TOKEN_MANUAL.fullmatch(boot) is None):
            raise ValueError("La operación manual no es válida.")

    @staticmethod
    def _validar_captura(captura_id):
        if not isinstance(captura_id, str) or PATRON_CAPTURA.fullmatch(captura_id) is None:
            raise ValueError("El identificador de captura RFID 1 no es válido.")

    @staticmethod
    def _decodificar_json(contenido):
        try:
            respuesta = json.loads(contenido.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ErrorApi("La respuesta de captura RFID 1 no es válida.") from None
        if type(respuesta) is not dict:
            raise ErrorApi("La respuesta de captura RFID 1 no es válida.")
        return respuesta

    def _solicitar(self, metodo, ruta, cuerpo, estados_esperados, clave=None):
        """envía la solicitud con un tiempo máximo; ante un fallo temporal, la repite con el mismo identificador si lo recibió"""
        destino = urllib.parse.urlsplit(self.url_base)
        puerto = destino.port or 80
        datos = b"" if cuerpo is None else json.dumps(
            cuerpo, separators=(",", ":")
        ).encode("utf-8")
        encabezados = {
            "Accept": "application/json",
            "Authorization": "Bearer " + self.token,
        }
        if cuerpo is not None:
            encabezados["Content-Type"] = "application/json"
        if clave is not None:
            encabezados["Idempotency-Key"] = clave
        solicitud = self._crear_solicitud_captura(
            metodo, destino.hostname, puerto, ruta, datos, encabezados
        )
        limite = time.monotonic() + self.tiempo_espera

        for intento in range(2):
            conexion = None
            try:
                conexion = self._conectar(destino.hostname, puerto, limite)
                self._enviar(conexion, solicitud, limite)
                buffer = bytearray()
                estado, cabeceras = self._leer_cabeceras(
                    conexion, buffer, limite
                )
                if estado in CODIGOS_REINTENTABLES:
                    if intento == 1:
                        raise ErrorApi(
                            "La API RFID 1 no confirmó la solicitud.", estado
                        )
                elif estado not in estados_esperados:
                    raise ErrorApi(
                        "La API RFID 1 rechazó la solicitud de captura.", estado
                    )
                elif estado == 204:
                    return estado, b""
                else:
                    contenido = self._leer_cuerpo(
                        conexion, buffer, cabeceras, limite
                    )
                    return estado, contenido
            except ErrorApi:
                raise
            except (OSError, TimeoutError):
                if intento == 1:
                    raise ErrorApi(
                        "La API RFID 1 no respondió.", origen="COMUNICACION"
                    ) from None
            finally:
                if conexion is not None:
                    conexion.close()
            if time.monotonic() < limite:
                time.sleep(min(0.1, limite - time.monotonic()))
        raise ErrorApi("La API RFID 1 no respondió.", origen="COMUNICACION")

    @staticmethod
    def _crear_solicitud_captura(metodo, host, puerto, ruta, cuerpo, encabezados):
        if metodo not in ("GET", "POST") or not ruta.startswith("/api/v1/"):
            raise ValueError("La ruta de captura RFID 1 no es válida.")
        if any(caracter in ruta for caracter in "\r\n "):
            raise ValueError("La ruta de captura RFID 1 no es válida.")
        autoridad = "[{}]".format(host) if ":" in host else host
        autoridad += ":{}".format(puerto)
        lineas = [
            "{} {} HTTP/1.1".format(metodo, ruta),
            "Host: {}".format(autoridad),
            "Connection: close",
            "Content-Length: {}".format(len(cuerpo)),
        ]
        for nombre, valor in encabezados.items():
            if any(caracter in nombre + valor for caracter in "\r\n"):
                raise ValueError("Un encabezado HTTP no es válido.")
            lineas.append("{}: {}".format(nombre, valor))
        return ("\r\n".join(lineas) + "\r\n\r\n").encode("ascii") + cuerpo
