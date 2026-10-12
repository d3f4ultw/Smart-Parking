"""Envía el estado físico de los cajones a la API de Smart Parking."""

try:
    import urequests
except ImportError:
    urequests = None

try:
    import ujson as json
except ImportError:
    import json


_CATEGORIAS_REINTENTABLES = (
    "TRANSPORT_ERROR",
    "SERVER_ERROR",
    "DEVICE_API_DISABLED",
    "PROTOCOL_ERROR",
    "UNEXPECTED_HTTP",
)


def _crear_resultado(
    categoria,
    cajon_id,
    status_code=None,
    estado_fisico=None,
    cambio_aplicado=None,
):
    """Devuelve un resultado pequeño y seguro para el controlador."""

    return {
        "category": categoria,
        "ok": categoria == "SUCCESS",
        "retryable": categoria in _CATEGORIAS_REINTENTABLES,
        "cajon_id": cajon_id,
        "status_code": status_code,
        "estado_fisico": estado_fisico,
        "cambio_aplicado": cambio_aplicado,
    }


def _clasificar_http(status_code):
    """Clasifica errores HTTP sin leer ni mostrar el cuerpo de respuesta."""

    if status_code == 401:
        return "AUTH_ERROR"
    if status_code == 404:
        return "SLOT_NOT_FOUND"
    if status_code == 422:
        return "CONTRACT_ERROR"
    if status_code == 503:
        return "DEVICE_API_DISABLED"
    if 500 <= status_code <= 599:
        return "SERVER_ERROR"
    return "UNEXPECTED_HTTP"


class ApiClient:
    """Envía reportes autenticados y valida su confirmación."""

    def __init__(
        self,
        api_base_url,
        bearer_token,
        transport=None,
        json_module=None,
        timeout_seconds=2,
    ):
        self.api_base_url = api_base_url.rstrip("/")
        self.bearer_token = bearer_token
        self._transport = transport if transport is not None else urequests
        self._json = json_module if json_module is not None else json
        self.timeout_seconds = timeout_seconds

    def check_health(self):
        """Comprueba /health y cierra la respuesta incluso si falla."""

        response = None
        try:
            if self._transport is None:
                raise OSError
            response = self._transport.get(
                self.api_base_url + "/health",
                timeout=self.timeout_seconds,
            )
            print("HTTP:", response.status_code)
            return response.status_code == 200
        except Exception:
            print("Error al conectar con FastAPI")
            return False
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass

    def send_physical_state(self, cajon_id, ocupado):
        """Envía una lectura y valida que la API confirme el mismo estado."""

        if type(cajon_id) is not int or cajon_id < 1:
            return _crear_resultado("CONTRACT_ERROR", cajon_id)
        if type(ocupado) is not bool:
            return _crear_resultado("CONTRACT_ERROR", cajon_id)
        if not isinstance(self.bearer_token, str) or not self.bearer_token:
            return _crear_resultado("AUTH_ERROR", cajon_id)
        if self._transport is None:
            return _crear_resultado("TRANSPORT_ERROR", cajon_id)

        try:
            cuerpo = self._json.dumps({"ocupado": ocupado}).encode("utf-8")
        except Exception:
            return _crear_resultado("PROTOCOL_ERROR", cajon_id)

        url = "{}/api/cajones/{}/estado-fisico".format(
            self.api_base_url,
            cajon_id,
        )
        headers = {
            "Authorization": "Bearer " + self.bearer_token,
            "Content-Type": "application/json",
        }
        response = None

        try:
            response = self._transport.put(
                url,
                data=cuerpo,
                headers=headers,
                timeout=self.timeout_seconds,
            )
        except Exception:
            return _crear_resultado("TRANSPORT_ERROR", cajon_id)

        try:
            status_code = response.status_code
            if type(status_code) is not int:
                return _crear_resultado("PROTOCOL_ERROR", cajon_id)
            if status_code != 200:
                return _crear_resultado(
                    _clasificar_http(status_code),
                    cajon_id,
                    status_code=status_code,
                )

            acknowledgement = response.json()
            if not isinstance(acknowledgement, dict):
                return _crear_resultado(
                    "PROTOCOL_ERROR",
                    cajon_id,
                    status_code=status_code,
                )

            estado_esperado = "OCUPADO" if ocupado else "LIBRE"
            respuesta_id = acknowledgement.get("cajon_id")
            estado_recibido = acknowledgement.get("estado_fisico")
            cambio_aplicado = acknowledgement.get("cambio_aplicado")
            if (
                type(respuesta_id) is not int
                or respuesta_id != cajon_id
                or estado_recibido != estado_esperado
                or type(cambio_aplicado) is not bool
            ):
                return _crear_resultado(
                    "PROTOCOL_ERROR",
                    cajon_id,
                    status_code=status_code,
                )

            return _crear_resultado(
                "SUCCESS",
                cajon_id,
                status_code=status_code,
                estado_fisico=estado_recibido,
                cambio_aplicado=cambio_aplicado,
            )
        except Exception:
            return _crear_resultado(
                "PROTOCOL_ERROR",
                cajon_id,
                status_code=200,
            )
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
