"""coordina las solicitudes de salida manual entre la placa ESP32 y el servicio, sin repetir una orden que pudo ejecutarse"""

import collections
import base64
import queue
import re
import threading
import time
import uuid

from cliente_smartparking import ErrorApi


TOKEN = r"[A-Za-z0-9_-]{21}[AQgw]"
PATRON_LISTA = re.compile(r"SM_LISTA,({0}),({0}),({0})\Z".format(TOKEN))
PATRON_RESULTADO = re.compile(
    r"SM_RES,({0}),({0}),({0}),(E|N),([A-Za-z0-9_-]{{16}})\Z".format(TOKEN)
)
PATRON_OCUPADA = re.compile(r"SM_OCUPADA,({0}),({0})\Z".format(TOKEN))
INTERVALO_CONSULTA = 0.8
INTERVALO_PREPARAR = 1.0
INTERVALO_RESULTADO = 1.0
LIMITE_ENVIO_EJECUTAR = 4.0
LIMITE_PREPARACION = 5.0
MAXIMO_RESULTADOS = 32


def _comprimir_uuid(operacion):
    return base64.urlsafe_b64encode(uuid.UUID(operacion).bytes).rstrip(b"=").decode("ascii")


def _expandir_uuid(token):
    return str(uuid.UUID(bytes=base64.urlsafe_b64decode(token + "==")))


class GestorSalidaManual:
    """consulta una operación a la vez y organiza los mensajes de salida manual con la placa ESP32"""

    def __init__(self, cliente, reloj=time.monotonic):
        self.cliente = cliente
        self.habilitada = all(callable(getattr(cliente, nombre, None)) for nombre in (
            "consultar_salida_manual", "emitir_salida_manual", "informar_resultado_salida_manual"
        ))
        self.reloj = reloj
        self.epoca = 0
        self.trabajo = None
        self.terminados = queue.Queue(maxsize=1)
        self.actual = None
        self.cursor = None
        self.conocidas = collections.OrderedDict()
        self.consultas = collections.OrderedDict()
        self.resultados = collections.OrderedDict()
        self.proxima_consulta = 0.0
        self.proximo_resultado = 0.0

    def conectar(self):
        """al reconectar, olvida la autorización anterior y no repite una orden que pudo ejecutarse"""
        self.epoca += 1
        self.actual = None
        self.proxima_consulta = 0.0

    def desconectar(self):
        """al desconectar, descarta la operación actual para no usar datos de la conexión anterior"""
        self.epoca += 1
        self.actual = None

    def atender(self, puerto, capacidad_disponible=True):
        """revisa la operación pendiente y deja en espera los mensajes que correspondan para la placa ESP32"""
        if not self.habilitada:
            return
        self._recoger(puerto, capacidad_disponible)
        if self.consultas:
            operacion, boot = self.consultas.popitem(last=False)
            puerto.escribir_linea("SM_GET,{},{}".format(_comprimir_uuid(operacion), boot))
        ahora = self.reloj()
        actual = self.actual
        if actual is not None and actual["estado"] == "PREPARANDO":
            if ahora - actual["inicio"] >= LIMITE_PREPARACION:
                self.actual = None
                self.proxima_consulta = 0.0
            elif capacidad_disponible and ahora >= actual["proximo_preparar"]:
                puerto.escribir_linea("SM_PREP,{}".format(actual["compacto"]))
                actual["proximo_preparar"] = ahora + INTERVALO_PREPARAR
        elif actual is not None and actual["estado"] in ("EMITIDA", "INCIERTA"):
            if ahora >= actual["proxima_verificacion"]:
                puerto.escribir_linea("SM_GET,{},{}".format(actual["compacto"], actual["boot"]))
                actual["proxima_verificacion"] = ahora + INTERVALO_RESULTADO

        if self.trabajo is not None:
            return
        if self.resultados and ahora >= self.proximo_resultado:
            clave = next(iter(self.resultados))
            self._iniciar("resultado", clave, self.cliente.informar_resultado_salida_manual, *clave)
        elif ahora >= self.proxima_consulta:
            self.proxima_consulta = ahora + INTERVALO_CONSULTA
            self._iniciar("consulta", None, self.cliente.consultar_salida_manual, self.cursor)

    def recibir(self, linea, puerto):
        """acepta mensajes que coinciden con la operación y sus permisos; ignora los de operaciones anteriores"""
        lista = PATRON_LISTA.fullmatch(linea)
        if lista is not None:
            compacto, boot, ticket = lista.groups()
            actual = self.actual
            if (actual is None or actual["estado"] != "PREPARANDO"
                    or actual["compacto"] != compacto):
                return
            actual.update({"estado": "LISTA", "boot": boot, "ticket": ticket})
            self._recordar(actual["id"], boot, ticket)
            return
        resultado = PATRON_RESULTADO.fullmatch(linea)
        if resultado is not None:
            compacto, boot, ticket, codigo, firma = resultado.groups()
            operacion = _expandir_uuid(compacto)
            if self.conocidas.get(operacion) != (boot, ticket):
                return
            valor = "EJECUTADA" if codigo == "E" else "NO_EJECUTADA"
            clave = (operacion, boot, ticket, valor, firma)
            if clave not in self.resultados and len(self.resultados) < MAXIMO_RESULTADOS:
                self.resultados[clave] = None
            return
        ocupada = PATRON_OCUPADA.fullmatch(linea)
        if ocupada is not None and self.actual is not None:
            if (self.actual["estado"] == "PREPARANDO"
                    and self.actual["compacto"] == ocupada.group(1)):
                self.actual = None
                self.proxima_consulta = self.reloj() + INTERVALO_CONSULTA

    def _recordar(self, operacion, boot, ticket):
        self.conocidas[operacion] = (boot, ticket)
        self.conocidas.move_to_end(operacion)
        while len(self.conocidas) > MAXIMO_RESULTADOS:
            self.conocidas.popitem(last=False)

    def _iniciar(self, tipo, clave, funcion, *argumentos):
        """consulta al servicio sin interrumpir el intercambio con la placa ESP32 y asocia la respuesta con la conexión que inició la consulta"""
        epoca = self.epoca
        self.trabajo = (tipo, clave, epoca)

        def ejecutar():
            try:
                valor = funcion(*argumentos)
                error = None
            except Exception as fallo:
                valor, error = None, fallo
            self.terminados.put((tipo, clave, epoca, valor, error))

        threading.Thread(target=ejecutar, daemon=True).start()

    def _recoger(self, puerto, capacidad_disponible):
        """usa la respuesta del servicio y envía la orden una vez si el permiso llega a tiempo y hay capacidad"""
        try:
            tipo, clave, epoca, valor, error = self.terminados.get_nowait()
        except queue.Empty:
            tipo = None
        if tipo is not None:
            self.trabajo = None
            if tipo == "resultado":
                if error is None or getattr(error, "estado_http", None) in (400, 404, 409):
                    self.resultados.pop(clave, None)
                    if self.actual is not None and self.actual["id"] == clave[0]:
                        self.actual = None
                self.proximo_resultado = self.reloj() + INTERVALO_RESULTADO
            elif epoca == self.epoca and tipo == "consulta" and error is None:
                self._aplicar_consulta(valor)
            elif epoca == self.epoca and tipo == "emitir":
                actual = self.actual
                if actual is not None and actual["id"] == clave:
                    actual["estado"] = "EMITIDA"
                    actual["proxima_verificacion"] = 0.0
                    if (capacidad_disponible and error is None and isinstance(valor, str) and len(valor) == 16
                            and self.reloj() - actual["inicio"] < LIMITE_ENVIO_EJECUTAR):
                        # La orden se envía una vez; si no se sabe qué ocurrió, se consulta al servicio y no se repite.
                        puerto.escribir_linea("SM_EXEC,{},{},{},{}".format(
                            actual["compacto"], actual["boot"], actual["ticket"], valor
                        ))
        actual = self.actual
        if (capacidad_disponible and self.trabajo is None and actual is not None
                and actual["estado"] == "LISTA"):
            actual["estado"] = "EMITIENDO"
            self._iniciar("emitir", actual["id"], self.cliente.emitir_salida_manual,
                          actual["id"], actual["boot"], actual["ticket"])

    def _aplicar_consulta(self, respuesta):
        """actualiza el estado con la respuesta del servicio y averigua el resultado sin repetir una orden enviada"""
        if respuesta is None:
            self.cursor = None
            # La solicitud pudo vencer o el servicio pudo confirmarla mientras se consultaba.
            if self.actual is not None and self.actual["estado"] != "EMITIENDO":
                self.actual = None
            return
        operacion = respuesta["operacionId"]
        self.cursor = operacion
        estado = respuesta["estado"]
        if estado == "PENDIENTE":
            if (self.actual is None or (self.actual["id"] != operacion
                    and self.actual["estado"] not in ("LISTA", "EMITIENDO"))):
                self.actual = {
                    "id": operacion, "compacto": _comprimir_uuid(operacion),
                    "estado": "PREPARANDO", "inicio": self.reloj(), "proximo_preparar": 0.0,
                }
        elif estado in ("EMITIDA", "INCIERTA"):
            boot = respuesta["bootId"]
            ticket = respuesta["ticketId"]
            self._recordar(operacion, boot, ticket)
            if (self.actual is None or self.actual["id"] == operacion
                    or self.actual["estado"] in ("EMITIDA", "INCIERTA")):
                self.actual = {
                    "id": operacion, "compacto": _comprimir_uuid(operacion), "boot": boot,
                    "estado": estado, "proxima_verificacion": 0.0,
                }
            elif len(self.consultas) < MAXIMO_RESULTADOS:
                self.consultas[operacion] = boot
