"""una sola parte del programa intercambia mensajes con la placa ESP32 para evitar que se mezclen"""

import queue
import threading
import time

from puerto_serie import ErrorProtocolo


MAXIMO_TRAMAS = 64


class BucleSerial:
    """controla el puerto de la placa ESP32 y limita cuántos mensajes pueden quedar en espera"""

    def __init__(self, sesion, puerto, detener):
        self.sesion = sesion
        self.puerto = puerto
        self.detener = detener
        self.finalizar = threading.Event()
        self.recibidas = queue.Queue(maxsize=MAXIMO_TRAMAS)
        self.por_enviar = queue.Queue(maxsize=MAXIMO_TRAMAS)
        self.error = None
        self.hilo = threading.Thread(target=self._ejecutar, daemon=True)

    def iniciar(self):
        self.hilo.start()

    def cerrar(self):
        """pide cerrar la comunicación con la placa ESP32 y avisa si no termina en tres segundos y medio"""
        self.finalizar.set()
        self.hilo.join(timeout=3.5)
        if self.hilo.is_alive():
            raise TimeoutError("No terminó el hilo serial.")

    def escribir_linea(self, linea):
        """deja el mensaje en espera para enviarlo a la placa ESP32 y avisa si ya hay demasiados pendientes"""
        try:
            self.por_enviar.put_nowait(linea)
        except queue.Full:
            raise OSError("La cola de salida serial está llena.") from None

    def leer_linea(self, tiempo_espera):
        """entrega el mensaje recibido o indica que no llegó ninguno dentro del plazo e informa si falla la comunicación"""
        if self.error is not None:
            raise self.error
        try:
            return self.recibidas.get(timeout=tiempo_espera)
        except queue.Empty:
            if self.error is not None:
                raise self.error
            return None

    def _ejecutar(self):
        """comprueba que la placa ESP32 responda y atiende las salidas RFID 3 mientras otras consultas esperan"""
        inicio = time.monotonic()
        siguiente_ping = 0.0
        try:
            while not self.finalizar.is_set() and (self.detener is None or not self.detener.is_set()):
                ahora = time.monotonic()
                if ahora >= siguiente_ping:
                    self.puerto.escribir_linea("PING")
                    siguiente_ping = ahora + self.sesion.intervalo_ping
                self._enviar_pendientes()
                self.sesion.salida_rfid3.atender(self.puerto)
                conectado = (
                    self.sesion.ultimo_pong is not None
                    and not self.sesion._perdio_handshake(ahora, inicio)
                )
                self.sesion.estado_dispositivo.actualizar(conectado)
                try:
                    linea = self.puerto.leer_linea(self.sesion.intervalo_lectura)
                except ErrorProtocolo:
                    print("Se ignoró una trama serial mal formada.")
                    continue
                if linea == "PONG":
                    self.sesion.procesar_linea(linea, self.puerto)
                elif linea and linea.startswith("RFID3,"):
                    self.sesion.salida_rfid3.recibir(linea, self.puerto)
                elif linea:
                    try:
                        self.recibidas.put_nowait(linea)
                    except queue.Full:
                        print("Se descartó una trama por saturación serial.")
                if self.sesion._perdio_handshake(time.monotonic(), inicio):
                    raise TimeoutError("El ESP32 no respondió PONG.")
        except (OSError, TimeoutError, ErrorProtocolo) as error:
            self.error = error
        except Exception:
            self.error = OSError("Falló el bucle serial.")
        finally:
            self.sesion.estado_dispositivo.actualizar(False)

    def _enviar_pendientes(self):
        """envía a la placa ESP32 hasta 64 mensajes pendientes cada vez que revisa la lista"""
        # Todos los mensajes salen completos desde esta misma parte del programa.
        for _ in range(MAXIMO_TRAMAS):
            try:
                linea = self.por_enviar.get_nowait()
            except queue.Empty:
                return
            self.puerto.escribir_linea(linea)
