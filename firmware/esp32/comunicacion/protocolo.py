"""Recibe los mensajes del equipo y los dirige al lector o la barrera correspondiente."""


class Protocolo:
    """Organiza los mensajes que entran y salen de la placa."""

    def __init__(self, puerto, captura, reloj, entrada_rfid2=None, salida_rfid3=None,
                 salida_manual=None):
        self.puerto = puerto
        self.captura = captura
        self.entrada_rfid2 = entrada_rfid2
        self.salida_rfid3 = salida_rfid3
        self.salida_manual = salida_manual
        self.reloj = reloj
        self.detener = False
        self.version_lector = None
        self.error_lector = None
        self.ultimo_ping = reloj()

    def atender(self):
        """Atiende los mensajes disponibles y los envíos que siguen pendientes."""
        if self.salida_rfid3 is not None:
            self.salida_rfid3.actualizar(self.reloj())
        if self.salida_manual is not None:
            self.salida_manual.actualizar(self.reloj())
        atender_salida = getattr(self.puerto, "atender_salida", None)
        if atender_salida is not None:
            atender_salida()
        for linea in self.puerto.leer_lineas():
            self.procesar_linea(linea)

    def procesar_linea(self, texto):
        """Responde cuando comprueban la conexión y entrega cada orden a quien corresponde."""
        partes = texto.split(",")
        tipo = partes[0]
        if tipo == "PING" and len(partes) == 1:
            self.puerto.enviar_linea("PONG")
            self.ultimo_ping = self.reloj()
            if self.version_lector is not None:
                self.puerto.enviar_linea("RFID_READER,READY,%02X" % self.version_lector)
            elif self.error_lector is not None:
                self.puerto.enviar_linea("RFID_READER,ERROR,{}".format(self.error_lector))
            return
        if tipo == "STOP" and len(partes) == 1:
            self.detener = True
        elif tipo == "ENROLL_ARM" and len(partes) == 2:
            self.captura.iniciar_enrolamiento(partes[1])
        elif tipo == "ENROLL_REARM" and len(partes) == 3:
            self.captura.rearmar_rechazo(partes[1], partes[2])
        elif tipo == "ENROLL_CANCEL" and len(partes) == 2:
            self.captura.cancelar_enrolamiento(partes[1])
        elif tipo == "ACK" and len(partes) == 2:
            self.captura.confirmar(partes[1])
        elif tipo == "RESULT" and len(partes) == 3:
            self.captura.resultado(partes[1], partes[2])
        elif tipo == "RFID2_RESULT" and len(partes) == 3 and self.entrada_rfid2 is not None:
            self.entrada_rfid2.recibir_resultado(partes[1], partes[2])
        elif tipo == "RFID3_RESULT" and len(partes) == 3 and self.salida_rfid3 is not None:
            self.salida_rfid3.recibir_resultado(partes[1], partes[2])
        elif tipo == "SM_PREP" and len(partes) == 2 and self.salida_manual is not None:
            self.salida_manual.preparar(partes[1])
        elif tipo == "SM_EXEC" and len(partes) == 5 and self.salida_manual is not None:
            self.salida_manual.ejecutar(partes[1], partes[2], partes[3], partes[4])
        elif tipo == "SM_GET" and len(partes) == 3 and self.salida_manual is not None:
            self.salida_manual.consultar(partes[1], partes[2])
        elif tipo == "SM_PROBE" and len(partes) == 2 and self.salida_manual is not None:
            self.salida_manual.sondear(partes[1])
