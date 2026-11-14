"""informa al servicio si hay comunicación con la placa ESP32 y renueva ese estado cada cinco segundos"""

import threading
import time


INTERVALO_RENOVACION_ESTADO = 5.0


class EstadoDispositivo:
    """avisa al servicio cuando cambia la conexión con la placa ESP32"""

    def __init__(self, cliente):
        self.cliente = cliente
        self._cambio = threading.Event()
        self._detener = threading.Event()
        self._candado = threading.Lock()
        self._estado_deseado = None
        self._hilo = None

    def actualizar(self, conectado):
        """registra si hay comunicación con la placa ESP32 y avisa al servicio sin retrasar el intercambio de mensajes"""
        if type(conectado) is not bool:
            raise ValueError("El estado RFID debe ser booleano.")
        with self._candado:
            if conectado == self._estado_deseado:
                return
            self._estado_deseado = conectado
        if self._hilo is None:
            self._hilo = threading.Thread(
                target=self._mantener,
                name="smartparking-rfid1-heartbeat",
                daemon=True,
            )
            self._hilo.start()
        self._cambio.set()

    def cerrar(self):
        """pide al servicio que registre la placa ESP32 como desconectada y espera como máximo tres segundos y medio"""
        self.actualizar(False)
        self._detener.set()
        self._cambio.set()
        if self._hilo is not None:
            self._hilo.join(timeout=3.5)

    def _mantener(self):
        """avisa al servicio cuando cambia la conexión con la placa ESP32, repite el estado cada cinco segundos y reintenta si falla"""
        ultimo_estado = None
        proxima_renovacion = 0.0
        while True:
            demora = max(0.0, proxima_renovacion - time.monotonic())
            self._cambio.wait(demora)
            self._cambio.clear()
            with self._candado:
                conectado = self._estado_deseado
            if conectado is None:
                if self._detener.is_set():
                    return
                continue
            vencio_renovacion = time.monotonic() >= proxima_renovacion
            if conectado != ultimo_estado or vencio_renovacion:
                try:
                    self.cliente.informar_estado_dispositivo(conectado)
                except Exception:
                    print("No se pudo renovar el estado del lector RFID; se reintentará.")
                else:
                    ultimo_estado = conectado
                proxima_renovacion = time.monotonic() + INTERVALO_RENOVACION_ESTADO
            with self._candado:
                estado_actual = self._estado_deseado
            if self._detener.is_set() and estado_actual == conectado:
                return
