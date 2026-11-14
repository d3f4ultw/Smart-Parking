"""Un único hilo posee el puerto y atiende PING y RFID 3 sin esperar HTTP."""

import queue
import threading
import time

from puerto_serie import ErrorProtocolo


MAXIMO_TRAMAS = 64


class BucleSerial:
    """Encapsula el puerto real y transfiere las demás tramas por colas acotadas."""

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
        self.finalizar.set()
        self.hilo.join(timeout=3.5)
        if self.hilo.is_alive():
            raise TimeoutError("No terminó el hilo serial.")

    def escribir_linea(self, linea):
        try:
            self.por_enviar.put_nowait(linea)
        except queue.Full:
            raise OSError("La cola de salida serial está llena.") from None

    def leer_linea(self, tiempo_espera):
        if self.error is not None:
            raise self.error
        try:
            return self.recibidas.get(timeout=tiempo_espera)
        except queue.Empty:
            if self.error is not None:
                raise self.error
            return None

    def _ejecutar(self):
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
                self.sesion.estado_dispositivo.actualizar(
                    self.sesion.ultimo_pong is not None
                    and not self.sesion._perdio_handshake(ahora, inicio)
                )
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
        # Todas las tramas se escriben completas desde este mismo hilo.
        for _ in range(MAXIMO_TRAMAS):
            try:
                linea = self.por_enviar.get_nowait()
            except queue.Empty:
                return
            self.puerto.escribir_linea(linea)
