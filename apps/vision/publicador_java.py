"""Envía al sistema del estacionamiento la ocupación confirmada cuando se habilita esa opción."""

from __future__ import annotations

import ipaddress
import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID, uuid4


_MAX_EDAD = 10.0
_INTERVALO = 1.0
_TIMEOUT = 2.0


@dataclass(frozen=True)
class ConfiguracionPublicador:
    """Reúne la dirección, la clave de acceso y las identidades de las zonas.

    La clave no se muestra al convertir estos datos en texto.
    """

    url: str
    fuente_id: str
    token: str = field(repr=False)
    identidades: dict[str, str]


def cargar_configuracion(ruta_zonas: Path, zonas, entorno=None):
    """Prepara el envío cuando se han indicado todos los datos necesarios.

    Si la información está incompleta o no coincide con las zonas guardadas,
    informa el error; si no se indicó ningún dato, deja el envío desactivado.
    """
    entorno = os.environ if entorno is None else entorno
    claves = ("VISION_JAVA_URL", "VISION_FUENTE_ID", "VISION_TOKEN_ARCHIVO")
    valores = [entorno.get(clave, "").strip() for clave in claves]
    if not any(valores):
        return None
    if not all(valores):
        raise ValueError("La configuracion de publicacion Vision esta incompleta.")
    url, fuente, ruta_token = valores
    partes = urlsplit(url)
    if (partes.scheme not in ("http", "https") or not partes.hostname
            or partes.username is not None or partes.password is not None
            or partes.path not in ("", "/") or partes.query or partes.fragment):
        raise ValueError("La URL de la API Vision debe ser un origen HTTP(S) sin credenciales.")
    try:
        _ = partes.port
        fuente = str(UUID(fuente))
    except (TypeError, ValueError) as error:
        raise ValueError("La identidad o el puerto de Vision no es valido.") from error
    if partes.scheme == "http":
        host = partes.hostname.lower()
        try:
            direccion = ipaddress.ip_address(host)
            privado = direccion.is_private or direccion.is_loopback
        except ValueError:
            privado = host == "localhost"
        if not privado and entorno.get("VISION_JAVA_HTTP_PRIVADO") != "1":
            raise ValueError("HTTP hacia la API requiere red privada declarada explicitamente.")
    from configuracion_local import verificar_sin_guardado_pendiente

    verificar_sin_guardado_pendiente(ruta_zonas)
    try:
        token = Path(ruta_token).read_text(encoding="utf-8").strip()
        contenido = ruta_zonas.read_bytes()
        datos = json.loads(contenido)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("No se pudo leer el token o la calibracion privada de Vision.") from error
    verificar_sin_guardado_pendiente(ruta_zonas)
    if not token or any(caracter.isspace() for caracter in token):
        raise ValueError("El token de Vision debe ser un valor opaco sin espacios.")
    try:
        registros = datos["zones"]
        identidades = {registro["id"]: str(UUID(registro["vision_zone_id"]))
                       for registro in registros}
        geometria = {registro["id"]: tuple(tuple(punto) for punto in registro["polygon"])
                     for registro in registros}
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise ValueError("La integracion requiere UUID persistentes en cada zona.") from error
    geometria_cargada = {zona.identifier: zona.polygon for zona in zonas}
    if (not identidades or len(identidades) != len(registros)
            or len(set(identidades.values())) != len(identidades)
            or geometria != geometria_cargada):
        raise ValueError("Las zonas o identidades no coinciden con la calibracion cargada.")
    return ConfiguracionPublicador(url.rstrip("/"), fuente, token, identidades)


class _SinRedireccion(HTTPRedirectHandler):
    """Impide enviar la solicitud a otra dirección si el servidor intenta redirigirla."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class _Muestra:
    """Guarda la ocupación y el momento de la imagen para descartar información antigua."""

    zonas: tuple[tuple[str, str], ...]
    observado_en: datetime
    monotono: float
    generacion: int


class PublicadorVision:
    """Envía la ocupación confirmada al sistema y conserva la actualización más reciente."""

    def __init__(self, config: ConfiguracionPublicador, iniciada_en=None):
        self.config = config
        self._condicion = threading.Condition()
        self._detencion = threading.Event()
        self._pendiente = None
        self._generacion = 0
        self._hilo = threading.Thread(target=self._ejecutar, name="vision-publicador", daemon=True)
        self._opener = build_opener(ProxyHandler({}), _SinRedireccion())
        self._solicitud_sesion = str(uuid4())
        inicio = datetime.now(timezone.utc) if iniciada_en is None else iniciada_en
        self._iniciada_en = inicio.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        self._sesion = None
        self._secuencia = 0
        self._ultima_fecha = None
        self._ultimo_envio = 0.0
        self.rechazada = False

    def iniciar(self):
        """Comienza a enviar la ocupación sin detener la lectura de imágenes."""
        self._hilo.start()

    def detener(self):
        """Pide terminar los envíos, espera el tiempo previsto e indica si finalizaron."""
        self._detencion.set()
        with self._condicion:
            self._condicion.notify_all()
        if self._hilo.is_alive():
            self._hilo.join(timeout=_TIMEOUT + 0.5)
        return not self._hilo.is_alive()

    def invalidar(self):
        """Descarta el envío pendiente para evitar información que dejó de ser válida."""
        with self._condicion:
            self._generacion += 1
            self._pendiente = None
            self._condicion.notify_all()

    def ofrecer(self, estados, *, observado_en=None, momento_observacion=None):
        """Conserva la observación más reciente de todas las zonas y el momento de la imagen.

        Si falta alguna zona o no se puede confirmar si está libre u ocupada,
        descarta el envío que estuviera pendiente.
        """
        observados = {estado.snapshot.identifier: estado.efectivo for estado in estados}
        if (len(observados) != len(estados) or set(observados) != set(self.config.identidades)
                or any(valor not in ("LIBRE", "OCUPADO") for valor in observados.values())):
            self.invalidar()
            return
        zonas = tuple(sorted((self.config.identidades[identificador], valor)
                             for identificador, valor in observados.items()))
        if observado_en is None:
            observado_en = datetime.now(timezone.utc)
        if momento_observacion is None:
            momento_observacion = time.monotonic()
        with self._condicion:
            self._generacion += 1
            self._pendiente = _Muestra(zonas, observado_en, momento_observacion, self._generacion)
            self._condicion.notify()

    def _post(self, ruta, cuerpo):
        request = Request(self.config.url + ruta,
                          data=json.dumps(cuerpo, separators=(",", ":")).encode("utf-8"),
                          headers={"Content-Type": "application/json",
                                   "Authorization": "Bearer " + self.config.token}, method="POST")
        try:
            with self._opener.open(request, timeout=_TIMEOUT) as respuesta:
                return respuesta.status, respuesta.read(4096)
        except HTTPError as error:
            return error.code, b""
        except (URLError, OSError, TimeoutError):
            return 0, b""

    def _solicitar_calibracion(self, metodo, cuerpo=None):
        data = None if cuerpo is None else json.dumps(
            cuerpo, separators=(",", ":"),
        ).encode("utf-8")
        headers = {"Authorization": "Bearer " + self.config.token}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(
            self.config.url + f"/api/v1/vision/fuentes/{self.config.fuente_id}/calibracion",
            data=data,
            headers=headers,
            method=metodo,
        )
        try:
            with self._opener.open(request, timeout=_TIMEOUT) as respuesta:
                return respuesta.status, respuesta.read()
        except HTTPError as error:
            return error.code, b""
        except (URLError, OSError, TimeoutError):
            return 0, b""

    def activar_calibracion(self, zonas):
        """Envía todas las zonas al sistema, que asigna un cajón a las zonas nuevas."""
        return self._solicitar_calibracion("PUT", {"zonas": zonas})[0]

    def consultar_calibracion(self):
        """Consulta al sistema qué cajón corresponde actualmente a cada zona."""
        codigo, contenido = self._solicitar_calibracion("GET")
        if codigo != 200:
            raise OSError(f"Java no pudo devolver la calibracion (HTTP {codigo}).")
        try:
            respuesta = json.loads(contenido)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("Java devolvio una calibracion ilegible.") from error
        if not isinstance(respuesta, dict):
            raise ValueError("Java devolvio una calibracion invalida.")
        return respuesta

    @staticmethod
    def _transitorio(codigo):
        return codigo == 0 or codigo in (408, 429) or 500 <= codigo < 600

    def _advertir_detencion(self):
        print("Publicacion Vision detenida por rechazo o cambio de calibracion; "
              "la deteccion local continua.", file=sys.stderr, flush=True)
        self.rechazada = True
        self._detencion.set()

    def _esperar(self, segundos):
        return self._detencion.wait(max(0, segundos))

    def _abrir_sesion(self):
        intento = 0
        cuerpo = {"fuenteId": self.config.fuente_id, "solicitudId": self._solicitud_sesion,
                  "iniciadaEn": self._iniciada_en}
        while not self._detencion.is_set():
            with self._condicion:
                muestra = self._pendiente
                if muestra is None or time.monotonic() - muestra.monotono > _MAX_EDAD:
                    self._pendiente = None
                    return None
            codigo, respuesta = self._post("/api/v1/dispositivos/vision/sesiones", cuerpo)
            if 200 <= codigo < 300:
                try:
                    self._sesion = str(UUID(json.loads(respuesta)["sesionId"]))
                    return True
                except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                    self._advertir_detencion()
                    return False
            if not self._transitorio(codigo):
                self._advertir_detencion()
                return False
            if self._esperar(min(0.25 * (2 ** min(intento, 4)), 4.0)):
                return False
            intento += 1
        return False

    def _es_actual(self, muestra):
        with self._condicion:
            return (muestra.generacion == self._generacion
                    and time.monotonic() - muestra.monotono <= _MAX_EDAD)

    def _ejecutar(self):
        while not self._detencion.is_set():
            with self._condicion:
                while self._pendiente is None and not self._detencion.is_set():
                    self._condicion.wait()
            if self._detencion.is_set():
                return
            if self._sesion is None:
                apertura = self._abrir_sesion()
                if apertura is False:
                    return
                if apertura is None:
                    continue
            if self._esperar(_INTERVALO - (time.monotonic() - self._ultimo_envio)):
                return
            with self._condicion:
                muestra = self._pendiente
                self._pendiente = None
            if muestra is None or not self._es_actual(muestra):
                continue
            if self._ultima_fecha is not None and muestra.observado_en <= self._ultima_fecha:
                continue
            self._secuencia += 1
            self._ultima_fecha = muestra.observado_en
            cuerpo = {
                "fuenteId": self.config.fuente_id, "sesionId": self._sesion,
                "secuencia": self._secuencia, "solicitudId": str(uuid4()),
                "observadoEn": muestra.observado_en.isoformat().replace("+00:00", "Z"),
                "zonas": [{"visionZoneId": zona, "estado": estado} for zona, estado in muestra.zonas],
            }
            intento = 0
            while self._es_actual(muestra) and not self._detencion.is_set():
                self._ultimo_envio = time.monotonic()
                codigo, _ = self._post("/api/v1/dispositivos/vision/observaciones", cuerpo)
                if 200 <= codigo < 300:
                    break
                if not self._transitorio(codigo):
                    # Si se rechaza una sesión reemplazada, no se inicia otra:
                    # una ejecución anterior podría desplazar la sesión actual.
                    self._advertir_detencion()
                    return
                if self._esperar(min(0.25 * (2 ** min(intento, 3)), 2.0)):
                    return
                intento += 1
