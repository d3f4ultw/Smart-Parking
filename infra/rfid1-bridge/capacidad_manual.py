"""comprueba si la placa ESP32 responde a la prueba previa del servicio para una salida manual, sin pedir que se abra la barrera"""

import queue
import re
import threading
import time


TOKEN = r"[A-Za-z0-9_-]{21}[AQgw]"
PATRON_RESPUESTA = re.compile(
    r"SM_PROBE_OK,({0}),({0}),([A-Za-z0-9_-]{{16}})\Z".format(TOKEN)
)
INTERVALO_SONDEO = 3.0
INTERVALO_REINTENTO = 1.0
LIMITE_RESPUESTA = 2.0
LIMITE_HTTP = 4.0


class CapacidadManual:
    """coordina la comprobación con el servicio y la placa ESP32, sin guardar la clave secreta que permite comprobar el origen de la respuesta"""

    def __init__(self, cliente, reloj=time.monotonic):
        self.cliente = cliente
        self.reloj = reloj
        self.habilitada = all(callable(getattr(cliente, nombre, None)) for nombre in (
            "solicitar_desafio_salida_manual", "confirmar_capacidad_salida_manual",
            "invalidar_capacidad_salida_manual",
        ))
        self.epoca = 0
        self.conectado = False
        self.estado = "INACTIVA"
        self.desafio = None
        self.limite = 0.0
        self.proximo_sondeo = 0.0
        self.verificada_hasta = 0.0
        self.inicio_verificacion = 0.0
        self.trabajos = queue.Queue(maxsize=4)
        self.resultados = queue.Queue(maxsize=8)
        self.hilo = None

    def conectar(self):
        """al conectar, descarta la comprobación anterior y pide al servicio que también la invalide"""
        if not self.habilitada:
            return
        self._iniciar_hilo()
        self.epoca += 1
        self.conectado = True
        self.estado = "INACTIVA"
        self.desafio = None
        self.verificada_hasta = 0.0
        self.proximo_sondeo = 0.0
        self._vaciar_trabajos()
        self._agendar("invalidar")

    def desconectar(self):
        """al desconectar, deja de considerar válida la comprobación y pide al servicio que la invalide"""
        if not self.habilitada:
            return
        self.epoca += 1
        self.conectado = False
        self.estado = "INACTIVA"
        self.desafio = None
        self.verificada_hasta = 0.0
        self._vaciar_trabajos()
        self._agendar("invalidar")

    def cerrar(self):
        """pide invalidar la comprobación y terminar las solicitudes pendientes; espera hasta tres segundos y medio"""
        if self.hilo is None:
            return
        self.desconectar()
        self.trabajos.put((self.epoca, "cerrar", ()), timeout=0.5)
        self.hilo.join(timeout=3.5)

    def disponible(self):
        """indica si el servicio aceptó recientemente la respuesta de la placa ESP32 y si aún está vigente"""
        return (self.habilitada and self.conectado
                and self.reloj() < self.verificada_hasta)

    def atender(self, puerto):
        """procesa las respuestas del servicio y de la placa ESP32, e inicia otra comprobación cuando corresponde"""
        if not self.habilitada or not self.conectado:
            return
        ahora = self.reloj()
        while True:
            try:
                epoca, tipo, valor, error = self.resultados.get_nowait()
            except queue.Empty:
                break
            if epoca != self.epoca:
                continue
            if tipo == "desafio" and self.estado == "SOLICITANDO":
                if error is not None:
                    self._fallar(ahora)
                    continue
                self.desafio = valor
                self.estado = "ESPERANDO"
                self.limite = ahora + LIMITE_RESPUESTA
                puerto.escribir_linea("SM_PROBE,{}".format(valor))
            elif tipo == "confirmar" and self.estado == "VERIFICANDO":
                if error is not None:
                    self._fallar(ahora)
                else:
                    self.estado = "INACTIVA"
                    self.desafio = None
                    # La comprobación vale seis segundos, por debajo de los ocho segundos de validez del servicio.
                    # El plazo empieza antes de pedir la confirmación.
                    self.verificada_hasta = self.inicio_verificacion + 6.0
                    self.proximo_sondeo = ahora + INTERVALO_SONDEO
        if self.estado != "INACTIVA" and ahora >= self.limite:
            self._fallar(ahora)
        if self.estado == "INACTIVA" and ahora >= self.proximo_sondeo:
            if self._agendar("desafio"):
                self.estado = "SOLICITANDO"
                self.limite = ahora + LIMITE_HTTP

    def recibir(self, linea):
        """acepta solo la respuesta al código temporal vigente y la envía al servicio para que compruebe que provino de la placa ESP32"""
        if not self.conectado or self.estado != "ESPERANDO":
            return
        coincidencia = PATRON_RESPUESTA.fullmatch(linea)
        if coincidencia is None:
            return
        desafio, boot, firma = coincidencia.groups()
        ahora = self.reloj()
        if desafio != self.desafio or ahora >= self.limite:
            return
        if self._agendar("confirmar", desafio, boot, firma):
            self.estado = "VERIFICANDO"
            self.inicio_verificacion = ahora
            self.limite = ahora + LIMITE_HTTP
        else:
            self._fallar(ahora)

    def _fallar(self, ahora):
        """si la comprobación falla o vence, descarta respuestas tardías, avisa al servicio y vuelve a intentarlo después"""
        # Se ignoran respuestas tardías antes de pedir al servicio que invalide la comprobación anterior.
        self.epoca += 1
        self.estado = "INACTIVA"
        self.desafio = None
        self.verificada_hasta = 0.0
        self.proximo_sondeo = ahora + INTERVALO_REINTENTO
        self._vaciar_trabajos()
        self._agendar("invalidar")

    def _agendar(self, tipo, *argumentos):
        try:
            self.trabajos.put_nowait((self.epoca, tipo, argumentos))
            return True
        except queue.Full:
            return False

    def _vaciar_trabajos(self):
        while True:
            try:
                self.trabajos.get_nowait()
            except queue.Empty:
                return

    def _iniciar_hilo(self):
        if self.hilo is None:
            self.hilo = threading.Thread(target=self._trabajar, daemon=True,
                                         name="smartparking-capacidad-manual")
            self.hilo.start()

    def _trabajar(self):
        """envía las consultas al servicio por separado y guarda sus respuestas para que el puente las revise"""
        funciones = {
            "desafio": self.cliente.solicitar_desafio_salida_manual,
            "confirmar": self.cliente.confirmar_capacidad_salida_manual,
            "invalidar": self.cliente.invalidar_capacidad_salida_manual,
        }
        while True:
            epoca, tipo, argumentos = self.trabajos.get()
            if tipo == "cerrar":
                return
            if epoca != self.epoca:
                continue
            try:
                valor = funciones[tipo](*argumentos)
                error = None
            except Exception as fallo:
                valor, error = None, fallo
            try:
                self.resultados.put_nowait((epoca, tipo, valor, error))
            except queue.Full:
                pass
