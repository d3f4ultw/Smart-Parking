"""consulta al servicio si hay una captura activa mientras otra parte del programa atiende los mensajes de la placa ESP32"""

import queue
import threading

from cliente_smartparking import ErrorApi


class ConsultaCaptura:
    """inicia una sola consulta a la vez y entrega la respuesta a quien coordina la lectura"""

    def __init__(self, cliente):
        self.cliente = cliente
        self.en_curso = False
        self.resultados = queue.Queue(maxsize=1)

    def obtener(self):
        """inicia una consulta si no hay otra en curso e indica si aún sigue pendiente"""
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
        """pregunta al servicio si hay una captura activa y guarda la respuesta para quien coordina la lectura"""
        try:
            captura = self.cliente.consultar_captura_activa()
        except Exception:
            self.resultados.put((False, None))
        else:
            self.resultados.put((True, captura))
