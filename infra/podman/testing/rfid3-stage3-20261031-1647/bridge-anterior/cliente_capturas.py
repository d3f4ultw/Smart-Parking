"""Cliente HTTP de loopback para reconciliar y completar capturas RFID 1."""

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
PATRON_CAPTURA = re.compile(r"[0-9a-f]{32}\Z")
PATRON_SOLICITUD = re.compile(r"[0-9A-Fa-f]{1,4}\Z")
PATRON_UUID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z"
)


class ClienteCapturas(ClienteSmartParking):
    """Usa el transporte HTTP limitado a loopback de Stage 1."""

    def consultar_captura_activa(self):
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
        """Devuelve solo la decisión confirmada de entrada; conserva el UUID."""
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
                "TARJETA_DESCONOCIDA", "TARJETA_CANCELADA", "ENTRADA_PENDIENTE"
            )
        ):
            return "DENEGADA"
        raise ErrorApi("La API no confirmó la decisión RFID 2.", estado_http)

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
                    raise ErrorApi("La API RFID 1 no respondió.") from None
            finally:
                if conexion is not None:
                    conexion.close()
            if time.monotonic() < limite:
                time.sleep(min(0.1, limite - time.monotonic()))
        raise ErrorApi("La API RFID 1 no respondió.")

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
