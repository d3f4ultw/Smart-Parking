"""Pruebas de callbacks y estados de diagnostico del firmware."""

from soporte_app_diagnostico import SoporteAplicacionDiagnostico, aplicacion


class PruebasCallbackDiagnostico(SoporteAplicacionDiagnostico):
    def test_callback_recibe_eventos_sanitizados_y_su_fallo_no_detiene_loop(self):
        eventos = []
        fallo_inyectado = {"ocurrio": False}

        def callback(evento):
            eventos.append(evento)
            if evento[1] == "ESTADO" and not fallo_inyectado["ocurrio"]:
                fallo_inyectado["ocurrio"] = True
                raise RuntimeError("callback caído")

        puerto = self.ejecutar_main(callback)

        self.assertTrue(puerto.cerrado)
        self.assertEqual(
            eventos,
            [
                ("RFID1", "ESTADO", "READY"),
                ("RFID1", "VERSION", "92"),
                ("RFID2", "ESTADO", "READY"),
                ("RFID2", "VERSION", "92"),
                ("RFID3", "ESTADO", "READY"),
                ("RFID3", "VERSION", "92"),
                ("RFID1", "DETECCION", "TARJETA_DETECTADA"),
                ("RFID2", "DETECCION", "TARJETA_DETECTADA"),
                ("RFID3", "DETECCION", "TARJETA_DETECTADA"),
            ],
        )
        self.assertTrue(all(len(evento) == 3 for evento in eventos))
        texto_eventos = repr(eventos)
        self.assertNotIn("A1B2C3D4", texto_eventos)
        self.assertNotIn("05060708", texto_eventos)
        self.assertNotIn("CAFE0102", texto_eventos)
        self.assertIn("RFID_DIAG,RFID3,READY,92", puerto.lineas)
        self.assertIn("RFID_DIAG,RFID3,DETECCION", puerto.lineas)
        diagnosticos = [linea for linea in puerto.lineas if linea.startswith("RFID_DIAG,")]
        self.assertNotIn("CAFE0102", repr(diagnosticos))
        self.assertEqual(sum(linea.startswith("RFID3,") for linea in puerto.lineas), 1)

    def test_error_de_inicializacion_no_expone_detalle_ni_afecta_deteccion_rfid1(self):
        eventos = []
        self.ejecutar_main(eventos.append, falla_rfid2=True)

        self.assertIn(("RFID2", "ESTADO", "ERROR"), eventos)
        self.assertIn(("RFID1", "DETECCION", "TARJETA_DETECTADA"), eventos)
        self.assertTrue(all(len(evento) == 3 for evento in eventos))
        self.assertNotIn("detalle privado de hardware", repr(eventos))

    def test_fallo_callback_durante_deteccion_no_se_confunde_con_fallo_rc522(self):
        eventos = []

        def callback(evento):
            eventos.append(evento)
            if evento[1] == "DETECCION":
                raise RuntimeError("salida diagnóstica no disponible")

        self.ejecutar_main(callback)

        self.assertIn(("RFID1", "DETECCION", "TARJETA_DETECTADA"), eventos)
        self.assertIn(("RFID2", "DETECCION", "TARJETA_DETECTADA"), eventos)
        self.assertIn(("RFID3", "DETECCION", "TARJETA_DETECTADA"), eventos)
        self.assertNotIn(("RFID2", "ESTADO", "ERROR"), eventos)

    def test_fallo_de_rfid3_no_afecta_rfid1_y_rfid2(self):
        eventos = []
        puerto = self.ejecutar_main(eventos.append, falla_rfid3=True)

        self.assertIn(("RFID3", "ESTADO", "ERROR"), eventos)
        self.assertIn(("RFID1", "DETECCION", "TARJETA_DETECTADA"), eventos)
        self.assertIn(("RFID2", "DETECCION", "TARJETA_DETECTADA"), eventos)
        self.assertIn("RFID_DIAG,RFID3,ERROR", puerto.lineas)
        self.assertNotIn("detalle privado de hardware", repr(eventos) + repr(puerto.lineas))

