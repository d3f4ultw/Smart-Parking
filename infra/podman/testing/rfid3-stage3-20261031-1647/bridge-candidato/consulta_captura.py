"""Consulta RFID 1 en segundo plano sin acceso al puerto serial."""

import queue
import threading

from cliente_smartparking import ErrorApi


class ConsultaCaptura:
    """Limita a una consulta concurrente y entrega el resultado al bucle serial."""

    def __init__(self, cliente):
        self.cliente = cliente
        self.en_curso = False
        self.resultados = queue.Queue(maxsize=1)

    def obtener(self):
        if not self.en_curso:
            self.en_curso = True
            threading.Thread(target=self._consultar, daemon=True).start()
        try:
            correcto, captura = self.resultados.get_nowait()
        except queue.Empty:
            return ...
        self.en_curso = False
        if not correcto:
            raise ErrorApi("No se pudo consultar la captura RFID 1.")
        return captura

    def _consultar(self):
        try:
            captura = self.cliente.consultar_captura_activa()
        except Exception:
            self.resultados.put((False, None))
        else:
            self.resultados.put((True, captura))
