import time


class ParkingController:
    """Lee cajones continuamente y sincroniza su estado más reciente."""

    _MENSAJES_ERROR_API = {
        "AUTH_ERROR": "error de autenticación",
        "SLOT_NOT_FOUND": "cajón no encontrado",
        "CONTRACT_ERROR": "error de contrato",
        "DEVICE_API_DISABLED": "API de dispositivos no disponible",
        "SERVER_ERROR": "error del servidor",
        "TRANSPORT_ERROR": "error de conexión",
        "PROTOCOL_ERROR": "respuesta inválida",
        "UNEXPECTED_HTTP": "respuesta HTTP inesperada",
    }

    _CATEGORIAS_TERMINALES = (
        "AUTH_ERROR",
        "SLOT_NOT_FOUND",
        "CONTRACT_ERROR",
    )

    def __init__(
        self,
        sensors,
        poll_interval_ms,
        api_client,
        wifi_manager=None,
        api_retry_ms=5000,
        api_disabled_retry_ms=15000,
        tick_source=None,
    ):
        self.sensors = list(sensors)
        self.poll_interval_ms = poll_interval_ms
        self.api_client = api_client
        self.wifi_manager = wifi_manager
        self.api_retry_ms = api_retry_ms
        self.api_disabled_retry_ms = api_disabled_retry_ms
        self._ticks = tick_source if tick_source is not None else time
        self.slot_states = {}
        self._sensor_by_id = {}
        self._round_robin_cursor = 0

        for sensor in self.sensors:
            cajon_id = sensor.cajon_id
            self._sensor_by_id[cajon_id] = sensor
            self.slot_states[cajon_id] = {
                "current_state": None,
                "last_acknowledged_state": None,
                "pending_sync": True,
                "next_retry_at": None,
                "blocked_reason": None,
            }

    def scan_once(self):
        """Lee todos los sensores y, como máximo, envía un estado pendiente."""

        for sensor in self.sensors:
            estado_actual = sensor.is_occupied()
            self._actualizar_lectura(sensor, estado_actual)

        if not self._actualizar_wifi():
            return

        indice = self._buscar_cajon_elegible()
        if indice is None:
            return

        self._round_robin_cursor = (indice + 1) % len(self.sensors)
        sensor = self.sensors[indice]
        self._sincronizar_sensor(sensor)

    def _actualizar_lectura(self, sensor, estado_actual):
        """Guarda la lectura física más reciente antes de usar la red."""

        estado = self.slot_states[sensor.cajon_id]
        estado_anterior = estado["current_state"]
        estado["current_state"] = estado_actual

        if estado_anterior is None or estado_actual != estado_anterior:
            etiqueta = "OCUPADO" if estado_actual else "LIBRE"
            print("Cajón {}: {}".format(sensor.cajon_id, etiqueta))

        self._recalcular_pendiente(estado)

    def _recalcular_pendiente(self, estado):
        estado_actual = estado["current_state"]
        reconocido = estado["last_acknowledged_state"]
        estado["pending_sync"] = (
            estado_actual is None
            or reconocido is None
            or estado_actual != reconocido
        )

        if not estado["pending_sync"]:
            estado["next_retry_at"] = None

    def _actualizar_wifi(self):
        if self.wifi_manager is None:
            return True

        try:
            self.wifi_manager.update()
            return self.wifi_manager.is_connected()
        except Exception:
            return False

    def _buscar_cajon_elegible(self):
        cantidad = len(self.sensors)
        if cantidad == 0:
            return None

        ahora = self._ticks.ticks_ms()
        for desplazamiento in range(cantidad):
            indice = (self._round_robin_cursor + desplazamiento) % cantidad
            sensor = self.sensors[indice]
            estado = self.slot_states[sensor.cajon_id]

            if not estado["pending_sync"]:
                continue
            if estado["current_state"] is None:
                continue
            if estado["blocked_reason"] is not None:
                continue
            if not self._reintento_vencido(ahora, estado["next_retry_at"]):
                continue
            return indice

        return None

    def _reintento_vencido(self, ahora, limite):
        if limite is None:
            return True
        return self._ticks.ticks_diff(ahora, limite) >= 0

    def _sincronizar_sensor(self, sensor):
        cajon_id = sensor.cajon_id
        estado = self.slot_states[cajon_id]
        estado_enviado = estado["current_state"]

        try:
            resultado = self.api_client.send_physical_state(
                cajon_id,
                estado_enviado,
            )
        except Exception:
            resultado = {"category": "TRANSPORT_ERROR"}

        categoria = self._obtener_categoria(resultado)
        if categoria == "SUCCESS":
            if self._reconocimiento_valido(
                resultado,
                cajon_id,
                estado_enviado,
            ):
                estado["last_acknowledged_state"] = estado_enviado
                estado["next_retry_at"] = None
                self._imprimir_exito(cajon_id, resultado)
            else:
                categoria = "PROTOCOL_ERROR"

        if categoria in ("TRANSPORT_ERROR", "SERVER_ERROR"):
            self._programar_reintento(
                estado,
                self.api_retry_ms,
            )
            self._imprimir_error_reintentable(cajon_id, categoria)
        elif categoria in (
            "DEVICE_API_DISABLED",
            "PROTOCOL_ERROR",
            "UNEXPECTED_HTTP",
        ):
            self._programar_reintento(
                estado,
                self.api_disabled_retry_ms,
            )
            self._imprimir_error_reintentable(cajon_id, categoria)
        elif categoria in self._CATEGORIAS_TERMINALES:
            self._bloquear_cajon(estado, cajon_id, categoria)
        elif categoria != "SUCCESS":
            self._programar_reintento(
                estado,
                self.api_disabled_retry_ms,
            )
            self._imprimir_error_reintentable(cajon_id, "PROTOCOL_ERROR")

        self._releer_sensor(sensor)
        self._recalcular_pendiente(estado)

    def _obtener_categoria(self, resultado):
        if not isinstance(resultado, dict):
            return "PROTOCOL_ERROR"

        categoria = resultado.get("category")
        if categoria == "SUCCESS" or (
            isinstance(categoria, str)
            and categoria in self._MENSAJES_ERROR_API
        ):
            return categoria
        return "PROTOCOL_ERROR"

    def _reconocimiento_valido(self, resultado, cajon_id, estado_enviado):
        estado_esperado = "OCUPADO" if estado_enviado else "LIBRE"
        estado_recibido = resultado.get("estado_fisico")

        return (
            resultado.get("ok") is True
            and type(resultado.get("cajon_id")) is int
            and resultado.get("cajon_id") == cajon_id
            and type(resultado.get("status_code")) is int
            and resultado.get("status_code") == 200
            and estado_recibido == estado_esperado
            and type(resultado.get("cambio_aplicado")) is bool
        )

    def _imprimir_exito(self, cajon_id, resultado):
        if resultado.get("cambio_aplicado") is False:
            print("Cajón {}: API sincronizada (sin cambio)".format(cajon_id))
            return
        print("Cajón {}: API sincronizada".format(cajon_id))

    def _imprimir_error_reintentable(self, cajon_id, categoria):
        mensaje = self._MENSAJES_ERROR_API.get(
            categoria,
            "error de sincronización",
        )
        print("Cajón {}: {}; reintento pendiente".format(cajon_id, mensaje))

    def _programar_reintento(self, estado, demora_ms):
        ahora = self._ticks.ticks_ms()
        estado["next_retry_at"] = self._ticks.ticks_add(ahora, demora_ms)

    def _bloquear_cajon(self, estado, cajon_id, categoria):
        if estado["blocked_reason"] is not None:
            return

        estado["blocked_reason"] = categoria
        estado["next_retry_at"] = None
        mensaje = self._MENSAJES_ERROR_API.get(
            categoria,
            "error de sincronización",
        )
        print("Cajón {}: {}; bloqueado hasta reinicio".format(cajon_id, mensaje))

    def _releer_sensor(self, sensor):
        try:
            estado_actual = sensor.is_occupied()
        except Exception:
            return

        self._actualizar_lectura(sensor, estado_actual)

    def monitor(self):
        """Mantiene el sondeo local al intervalo configurado."""

        while True:
            self.scan_once()
            time.sleep_ms(self.poll_interval_ms)
