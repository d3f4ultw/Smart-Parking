import time


class WifiManager:
    """Inicia Wi-Fi sin detener el sondeo mientras se asocia el ESP32."""

    def __init__(
        self,
        ssid,
        password,
        reconnect_interval_ms,
        tick_source=None,
        network_module=None,
    ):
        if network_module is None:
            import network as network_module

        self._network = network_module
        self._ssid = ssid
        self._password = password
        self.reconnect_interval_ms = reconnect_interval_ms
        self._ticks = tick_source if tick_source is not None else time
        self._wlan = None
        self._was_connected = None
        self._next_connect_at = None

    def start(self):
        """Activa STA_IF e inicia la asociación sin esperar su resultado."""

        try:
            self._wlan = self._network.WLAN(self._network.STA_IF)
            self._wlan.active(True)
        except Exception:
            pass

        self.update()
        return self

    def is_connected(self):
        """Indica si la interfaz tiene una conexión Wi-Fi utilizable."""

        if self._wlan is None:
            return False

        try:
            return bool(self._wlan.isconnected())
        except Exception:
            return False

    def _obtener_status(self):
        if self._wlan is None:
            return None

        try:
            return self._wlan.status()
        except Exception:
            return None

    def update(self):
        """Registra cambios de conexión e intenta reconectar con límite."""

        conectado = self.is_connected()
        if self._was_connected is None or conectado != self._was_connected:
            estado = "conectado" if conectado else "desconectado"
            print("Wi-Fi: {}".format(estado))
            self._was_connected = conectado

        if not conectado:
            self._reconectar_si_corresponde()

        return conectado

    def _reconectar_si_corresponde(self):
        if self._wlan is None:
            return

        status = self._obtener_status()
        status_connecting = getattr(self._network, "STAT_CONNECTING", None)
        if status_connecting is not None and status == status_connecting:
            return

        ahora = self._ticks.ticks_ms()
        if self._next_connect_at is not None:
            if self._ticks.ticks_diff(ahora, self._next_connect_at) < 0:
                return

        try:
            self._wlan.connect(self._ssid, self._password)
        except Exception:
            pass
        ahora = self._ticks.ticks_ms()
        self._next_connect_at = getattr(self._ticks, "ticks_add")(
            ahora,
            self.reconnect_interval_ms,
        )
