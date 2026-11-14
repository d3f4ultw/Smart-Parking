"""Cliente HTTP dedicado a la recepción técnica de RFID 1."""

import errno
import ipaddress
import json
import re
import select
import socket
import time
import urllib.parse
import uuid


RUTA_LECTURAS = "/api/v1/dispositivos/rfid-1/lecturas"
TIEMPO_ESPERA_MAXIMO = 3.0
CODIGOS_REINTENTABLES = frozenset((502, 503, 504))
TAMANO_MAXIMO_RESPUESTA = 4096
TAMANO_MAXIMO_CABECERAS = 16384
TAMANO_MAXIMO_LINEA_HTTP = 8192
PATRON_UID = re.compile(r"(?:[0-9A-Fa-f]{8}|[0-9A-Fa-f]{14}|[0-9A-Fa-f]{20})\Z")
PATRON_TOKEN = re.compile(r"[\x21-\x7e]{1,512}\Z")


class ErrorApi(Exception):
    """Indica que la API no confirmó una operación RFID válida."""

    def __init__(self, mensaje, estado_http=None):
        super().__init__(mensaje)
        self.estado_http = estado_http


def validar_url_local(url):
    """Limita el envío de UID a un origen HTTP de loopback."""
    try:
        analizada = urllib.parse.urlsplit(url)
        hostname = analizada.hostname
        puerto = analizada.port
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError("La URL del API RFID 1 no es válida.") from error
    if (
        analizada.scheme != "http"
        or not hostname
        or analizada.username
        or analizada.password
        or analizada.path not in ("", "/")
        or analizada.query
        or analizada.fragment
    ):
        raise ValueError("La URL del API RFID 1 debe ser HTTP local.")
    try:
        direccion = ipaddress.ip_address(hostname)
    except ValueError:
        if hostname.lower() != "localhost":
            raise ValueError("La URL del API RFID 1 debe permanecer en loopback.")
        direccion = ipaddress.ip_address("127.0.0.1")
    else:
        if not direccion.is_loopback:
            raise ValueError("La URL del API RFID 1 debe permanecer en loopback.")
    if "%" in hostname:
        raise ValueError("La URL del API RFID 1 no admite zonas IPv6.")
    hostname = direccion.compressed
    if puerto is not None and not 1 <= puerto <= 65535:
        raise ValueError("El puerto del API RFID 1 no es válido.")
    return "http://{}{}".format(
        "[{}]".format(hostname) if ":" in hostname else hostname,
        ":{}".format(puerto) if puerto is not None else "",
    )


class ClienteSmartParking:
    """Envía lecturas con Bearer e idempotencia por evento."""

    def __init__(self, url_base, token, tiempo_espera=TIEMPO_ESPERA_MAXIMO):
        if not isinstance(token, str) or PATRON_TOKEN.fullmatch(token) is None:
            raise ValueError("Falta una credencial válida para RFID 1.")
        if not 0 < tiempo_espera <= TIEMPO_ESPERA_MAXIMO:
            raise ValueError("El timeout HTTP RFID 1 debe ser de hasta 3 segundos.")
        self.url_base = validar_url_local(url_base)
        self.token = token
        self.tiempo_espera = tiempo_espera

    def enviar_lectura(self, secuencia, uid, clave_idempotencia=None):
        """Publica una lectura; conserva la clave mientras realiza reintentos."""
        if type(secuencia) is not int or not 0 <= secuencia <= 0xFFFF:
            raise ValueError("La secuencia serial no es válida.")
        if not isinstance(uid, str) or PATRON_UID.fullmatch(uid) is None:
            raise ValueError("El UID serial no es válido.")
        clave = self._normalizar_clave(clave_idempotencia)
        cuerpo = json.dumps(
            {"secuencia": secuencia, "uid": uid.upper()},
            separators=(",", ":"),
        ).encode("utf-8")
        encabezados = {
            "Accept": "application/json",
            "Authorization": "Bearer " + self.token,
            "Content-Type": "application/json",
            "Idempotency-Key": clave,
        }
        self._solicitar_una_lectura(cuerpo, encabezados)

    @staticmethod
    def _normalizar_clave(clave):
        if clave is None:
            return str(uuid.uuid4())
        try:
            return str(uuid.UUID(clave))
        except (AttributeError, TypeError, ValueError) as error:
            raise ValueError("La clave de idempotencia debe ser UUID.") from error

    def _solicitar_una_lectura(self, cuerpo, encabezados):
        limite = time.monotonic() + self.tiempo_espera
        destino = urllib.parse.urlsplit(self.url_base)
        puerto = destino.port or 80
        solicitud = self._crear_solicitud(
            destino.hostname, puerto, cuerpo, encabezados
        )
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
                        raise ErrorApi("La API RFID 1 rechazó la lectura.")
                elif estado != 202:
                    raise ErrorApi("La API RFID 1 rechazó la lectura.")
                else:
                    contenido = self._leer_cuerpo(
                        conexion, buffer, cabeceras, limite
                    )
                    self._validar_respuesta(contenido)
                    return
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
    def _crear_solicitud(host, puerto, cuerpo, encabezados):
        autoridad = "[{}]".format(host) if ":" in host else host
        autoridad += ":{}".format(puerto)
        lineas = [
            "POST {} HTTP/1.1".format(RUTA_LECTURAS),
            "Host: {}".format(autoridad),
            "Connection: close",
            "Content-Length: {}".format(len(cuerpo)),
        ]
        for nombre, valor in encabezados.items():
            if any(caracter in nombre + valor for caracter in "\r\n"):
                raise ValueError("Un encabezado HTTP no es válido.")
            lineas.append("{}: {}".format(nombre, valor))
        return ("\r\n".join(lineas) + "\r\n\r\n").encode("ascii") + cuerpo

    @staticmethod
    def _conectar(host, puerto, limite):
        direccion = ipaddress.ip_address(host)
        familia = socket.AF_INET if direccion.version == 4 else socket.AF_INET6
        sockaddr = (
            (direccion.compressed, puerto)
            if familia == socket.AF_INET
            else (direccion.compressed, puerto, 0, 0)
        )
        conexion = socket.socket(familia, socket.SOCK_STREAM)
        conexion.setblocking(False)
        try:
            resultado = conexion.connect_ex(sockaddr)
            if resultado not in (0, errno.EISCONN):
                ClienteSmartParking._esperar(conexion, False, limite)
                error = conexion.getsockopt(
                    socket.SOL_SOCKET, socket.SO_ERROR
                )
                if error:
                    raise OSError(error, "Falló la conexión local.")
            return conexion
        except Exception:
            conexion.close()
            raise

    @staticmethod
    def _esperar(conexion, lectura, limite):
        while True:
            restante = limite - time.monotonic()
            if restante <= 0:
                raise TimeoutError("Se agotó el deadline HTTP.")
            lectores = [conexion] if lectura else []
            escritores = [] if lectura else [conexion]
            try:
                listos_lectura, listos_escritura, errores = select.select(
                    lectores, escritores, [conexion], restante
                )
            except InterruptedError:
                continue
            if errores:
                raise OSError("Falló la conexión HTTP local.")
            if listos_lectura or listos_escritura:
                return
            raise TimeoutError("Se agotó el deadline HTTP.")

    @staticmethod
    def _enviar(conexion, datos, limite):
        vista = memoryview(datos)
        while vista:
            ClienteSmartParking._esperar(conexion, False, limite)
            try:
                enviados = conexion.send(vista)
            except BlockingIOError:
                continue
            if enviados <= 0:
                raise OSError("La conexión HTTP se cerró al enviar.")
            vista = vista[enviados:]

    @staticmethod
    def _recibir(conexion, buffer, limite, permitir_fin=False):
        while True:
            ClienteSmartParking._esperar(conexion, True, limite)
            try:
                fragmento = conexion.recv(4096)
            except BlockingIOError:
                continue
            if not fragmento:
                if permitir_fin:
                    return False
                raise OSError("La API cerró la respuesta HTTP.")
            buffer.extend(fragmento)
            return True

    @staticmethod
    def _leer_linea_http(conexion, buffer, limite, tamano_maximo):
        while True:
            separador = buffer.find(b"\r\n")
            if separador >= 0:
                if separador > tamano_maximo:
                    raise ErrorApi("Una línea HTTP excede el límite.")
                linea = bytes(buffer[:separador])
                del buffer[:separador + 2]
                return linea
            if len(buffer) > tamano_maximo:
                raise ErrorApi("Una línea HTTP excede el límite.")
            ClienteSmartParking._recibir(conexion, buffer, limite)

    @classmethod
    def _leer_cabeceras(cls, conexion, buffer, limite):
        linea_estado = cls._leer_linea_http(
            conexion, buffer, limite, TAMANO_MAXIMO_LINEA_HTTP
        )
        partes = linea_estado.split(b" ", 2)
        if (
            len(partes) < 2
            or partes[0] not in (b"HTTP/1.0", b"HTTP/1.1")
            or len(partes[1]) != 3
            or not partes[1].isdigit()
        ):
            raise ErrorApi("El status HTTP no es válido.")
        estado = int(partes[1])
        total = len(linea_estado) + 2
        cabeceras = {}
        while True:
            linea = cls._leer_linea_http(
                conexion, buffer, limite, TAMANO_MAXIMO_LINEA_HTTP
            )
            total += len(linea) + 2
            if total > TAMANO_MAXIMO_CABECERAS:
                raise ErrorApi("Las cabeceras HTTP exceden el límite.")
            if not linea:
                return estado, cabeceras
            if linea[:1] in (b" ", b"\t") or b":" not in linea:
                raise ErrorApi("Una cabecera HTTP no es válida.")
            nombre, valor = linea.split(b":", 1)
            try:
                clave = nombre.decode("ascii").lower()
                contenido = valor.decode("latin-1").strip()
            except UnicodeDecodeError:
                raise ErrorApi("Una cabecera HTTP no es válida.") from None
            if clave in cabeceras:
                raise ErrorApi("La respuesta repite una cabecera HTTP.")
            cabeceras[clave] = contenido

    @classmethod
    def _leer_cuerpo(cls, conexion, buffer, cabeceras, limite):
        transferencia = cabeceras.get("transfer-encoding", "").lower()
        if transferencia:
            if transferencia.split(",") != ["chunked"]:
                raise ErrorApi("La codificación del cuerpo HTTP no es compatible.")
            return cls._leer_cuerpo_chunked(conexion, buffer, limite)
        longitud = cabeceras.get("content-length")
        if longitud is not None:
            if re.fullmatch(r"[0-9]{1,10}", longitud) is None:
                raise ErrorApi("La respuesta de la API RFID 1 no es válida.")
            tamano = int(longitud)
            if tamano > TAMANO_MAXIMO_RESPUESTA:
                raise ErrorApi("La respuesta de la API RFID 1 es demasiado grande.")
            return cls._leer_exactos(conexion, buffer, tamano, limite)
        return cls._leer_hasta_cierre(conexion, buffer, limite)

    @classmethod
    def _leer_cuerpo_chunked(cls, conexion, buffer, limite):
        contenido = bytearray()
        while True:
            linea = cls._leer_linea_http(
                conexion, buffer, limite, 128
            )
            tamano_hex = linea.split(b";", 1)[0]
            if (
                len(tamano_hex) > 8
                or re.fullmatch(rb"[0-9A-Fa-f]{1,8}", tamano_hex) is None
            ):
                raise ErrorApi("El cuerpo chunked no es válido.")
            try:
                tamano = int(tamano_hex, 16)
            except (ValueError, OverflowError):
                raise ErrorApi("El cuerpo chunked no es válido.") from None
            if tamano < 0 or len(contenido) + tamano > TAMANO_MAXIMO_RESPUESTA:
                raise ErrorApi("La respuesta de la API RFID 1 es demasiado grande.")
            if tamano == 0:
                cls._leer_trailers(conexion, buffer, limite)
                return bytes(contenido)
            contenido.extend(
                cls._leer_exactos(conexion, buffer, tamano, limite)
            )
            if cls._leer_exactos(conexion, buffer, 2, limite) != b"\r\n":
                raise ErrorApi("El cuerpo chunked no es válido.")

    @classmethod
    def _leer_trailers(cls, conexion, buffer, limite):
        total = 0
        while True:
            linea = cls._leer_linea_http(
                conexion, buffer, limite, TAMANO_MAXIMO_LINEA_HTTP
            )
            total += len(linea) + 2
            if total > TAMANO_MAXIMO_CABECERAS:
                raise ErrorApi("Los trailers HTTP exceden el límite.")
            if not linea:
                return
            if b":" not in linea:
                raise ErrorApi("Un trailer HTTP no es válido.")

    @staticmethod
    def _leer_exactos(conexion, buffer, tamano, limite):
        while len(buffer) < tamano:
            ClienteSmartParking._recibir(conexion, buffer, limite)
        resultado = bytes(buffer[:tamano])
        del buffer[:tamano]
        return resultado

    @staticmethod
    def _leer_hasta_cierre(conexion, buffer, limite):
        contenido = bytearray(buffer)
        buffer.clear()
        if len(contenido) > TAMANO_MAXIMO_RESPUESTA:
            raise ErrorApi("La respuesta de la API RFID 1 es demasiado grande.")
        while ClienteSmartParking._recibir(
            conexion, buffer, limite, permitir_fin=True
        ):
            contenido.extend(buffer)
            buffer.clear()
            if len(contenido) > TAMANO_MAXIMO_RESPUESTA:
                raise ErrorApi("La respuesta de la API RFID 1 es demasiado grande.")
        return bytes(contenido)

    @staticmethod
    def _validar_respuesta(contenido):
        try:
            respuesta = json.loads(contenido.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ErrorApi("La respuesta de la API RFID 1 no es válida.") from None
        if respuesta != {"estado": "RECIBIDA", "accion": "NINGUNA"}:
            raise ErrorApi("La respuesta de la API RFID 1 no es válida.")
