"""Pruebas de enrolamiento y señal sonora por lector."""

from soporte_app_diagnostico import PinFalso, SoporteAplicacionDiagnostico, aplicacion


class PruebasEnrolamientoBuzzer(SoporteAplicacionDiagnostico):
    def test_enrolamiento_estacionario_programa_un_solo_pitido(self):
        sesion = "a" * 32
        puerto, zumbadores, eventos = self.ejecutar_main_con_buzzer_falso(
            [("ENROLL_ARM," + sesion,), (), ("RESULT,0001,DENY",), ()],
        )

        self.assertEqual([z.programaciones for z in zumbadores], [[1], [], []])
        self.assertEqual(eventos.count(("RFID1", "DETECCION", "TARJETA_DETECTADA")), 1)
        self.assertEqual(sum(linea.startswith("ENROLL_READ,") for linea in puerto.lineas), 1)

    def test_retransmision_de_arm_no_repite_pitido_tras_vista_previa(self):
        sesion = "b" * 32
        puerto, zumbadores, eventos = self.ejecutar_main_con_buzzer_falso(
            [
                ("ENROLL_ARM," + sesion,),
                (),
                ("RESULT,0001,DENY", "ENROLL_ARM," + sesion, "RESULT,0001,DENY"),
                (),
            ],
        )

        self.assertEqual([z.programaciones for z in zumbadores], [[1], [], []])
        self.assertEqual(eventos.count(("RFID1", "DETECCION", "TARJETA_DETECTADA")), 1)
        self.assertEqual(sum(linea.startswith("ENROLL_READ,") for linea in puerto.lineas), 1)

    def test_nueva_sesion_puede_aceptar_la_misma_tarjeta(self):
        sesion_anterior = "c" * 32
        sesion_nueva = "d" * 32
        puerto, zumbadores, eventos = self.ejecutar_main_con_buzzer_falso(
            [
                ("ENROLL_ARM," + sesion_anterior,),
                (),
                (
                    "RESULT,0001,DENY",
                    "ENROLL_CANCEL," + sesion_anterior,
                    "ENROLL_ARM," + sesion_nueva,
                ),
                (),
            ],
        )

        self.assertEqual([z.programaciones for z in zumbadores], [[1, 1], [], []])
        self.assertEqual(eventos.count(("RFID1", "DETECCION", "TARJETA_DETECTADA")), 2)
        self.assertEqual(sum(linea.startswith("ENROLL_READ,") for linea in puerto.lineas), 2)

    def test_sesion_capturada_ignora_lectura_tras_perdida_de_presencia(self):
        sesion = "e" * 32
        uid_prueba = bytes((0xA1, 0xB2, 0xC3, 0xD4))
        puerto, zumbadores, eventos = self.ejecutar_main_con_buzzer_falso(
            [
                ("ENROLL_ARM," + sesion,),
                (),
                ("RESULT,0001,DENY",),
                (),
                (),
                (),
            ],
            iteraciones=6,
            intervalo_ms=500,
            lecturas_rfid1=[
                (uid_prueba, True),
                (uid_prueba, True),
                (None, False),
                (None, False),
                (uid_prueba, True),
                (uid_prueba, True),
            ],
        )

        self.assertEqual([z.programaciones for z in zumbadores], [[1], [], []])
        self.assertEqual(eventos.count(("RFID1", "DETECCION", "TARJETA_DETECTADA")), 1)
        self.assertEqual(sum(linea.startswith("ENROLL_READ,") for linea in puerto.lineas), 1)
        self.assertEqual(sum(linea.startswith("RFID,") for linea in puerto.lineas), 1)

    def test_solo_rfid1_programa_un_pitido_por_deteccion(self):
        class ZumbadorPrueba:
            def __init__(self, pin_numero, duracion_pitido_ms):
                self.pin_numero = pin_numero
                self.duracion_pitido_ms = duracion_pitido_ms
                self.programaciones = []

            def programar(self, cantidad):
                self.programaciones.append(cantidad)

            def actualizar(self):
                pass

            def finalizar(self):
                pass

        zumbadores = []

        def crear_zumbador(*, pin_numero, duracion_pitido_ms=150):
            zumbador = ZumbadorPrueba(pin_numero, duracion_pitido_ms)
            zumbadores.append(zumbador)
            return zumbador

        original = aplicacion.ControladorZumbador
        aplicacion.ControladorZumbador = crear_zumbador
        try:
            for lector, patrones in (("RFID1", ([1], [], [])), ("RFID3", ([], [], []))):
                with self.subTest(lector=lector):
                    eventos = []
                    inicio = len(zumbadores)
                    puerto = self.ejecutar_main(eventos.append, activos={lector}, iteraciones=6)
                    nuevos = zumbadores[inicio:]
                    self.assertEqual([z.pin_numero for z in nuevos], [4, 21, 25])
                    self.assertEqual(
                        [z.duracion_pitido_ms for z in nuevos], [150, 150, 130],
                    )
                    self.assertEqual([z.programaciones for z in nuevos], list(patrones))
                    self.assertEqual(eventos.count((lector, "DETECCION", "TARJETA_DETECTADA")), 1)
                    if lector == "RFID3":
                        self.assertEqual(puerto.lineas.count("RFID_DIAG,RFID3,DETECCION"), 1)
                        self.assertEqual(sum(linea.startswith("RFID3,") for linea in puerto.lineas), 1)
        finally:
            aplicacion.ControladorZumbador = original

    def test_la_aplicacion_inicializa_los_tres_buzzers(self):
        pines_creados = []

        class PinVigilado(PinFalso):
            def __init__(self, numero, modo=None, value=None):
                pines_creados.append(numero)
                super().__init__(numero, modo, value)

        entorno = aplicacion.ControladorZumbador.__init__.__globals__
        original = entorno["Pin"]
        entorno["Pin"] = PinVigilado
        try:
            self.ejecutar_main(None, activos=set())
        finally:
            entorno["Pin"] = original
        self.assertEqual(pines_creados, [4, 21, 25])


