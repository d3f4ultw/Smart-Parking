"""Pruebas de recuperacion segura ante fallos de Stage 3."""

import unittest

from soporte_instalacion_stage3 import (
    ReplSimulado,
    SoporteInstalacionStage3,
    instalacion,
    promocion,
)


class PruebaRecuperacionStage3(SoporteInstalacionStage3):
    def test_errores_antes_y_despues_de_cada_paso_de_promocion(self):
        for modo in ("antes", "despues"):
            for numero in range(1, 14):
                with self.subTest(modo=modo, numero=numero):
                    self.repl = ReplSimulado(self.originales)
                    self.repl.fallos_operacion = {numero: modo}
                    with self.assertRaises(instalacion.ErrorInstalacion) as error:
                        self.ejecutar()
                    self.assertTrue(error.exception.recuperado)
                    self.verificar_originales()

    def test_recuperacion_reintenta_acuse_perdido(self):
        self.repl.fallos_operacion = {7: "despues", 8: "despues"}
        with self.assertRaises(instalacion.ErrorInstalacion) as error:
            self.ejecutar()
        self.assertTrue(error.exception.recuperado)
        self.assertEqual(self.resincronizaciones, 2)
        self.verificar_originales()

    def test_un_error_de_sincronizacion_no_se_confunde_con_recuperacion(self):
        self.repl.fallos_operacion = {1: "despues"}
        llamadas = []

        def sincronizar(sesion):
            llamadas.append(sesion)
            if len(llamadas) == 1:
                raise instalacion.ErrorInstalacion("ajena", True, sesion)
            return sesion

        with self.assertRaises(instalacion.ErrorInstalacion) as error:
            instalacion.instalar_stage3(
                repl=self.repl, candidato=self.candidato, respaldo=self.respaldo,
                temporal=self.temporal, promocion=promocion, inventariar=lambda r: r.inventario(),
                resincronizar=sincronizar, verificar_arranque=lambda _r: self.resultado,
            )
        self.assertTrue(error.exception.recuperado)
        self.assertEqual(error.exception.etapa, "promoción")
        self.assertEqual(len(llamadas), 2)
        self.verificar_originales()

    def test_fallos_en_transferencia_y_compilacion_recuperan_originales(self):
        for modo in ("antes", "despues"):
            for numero in (1, 6, 7, 13):
                with self.subTest(modo=modo, numero=numero):
                    self.repl = ReplSimulado(self.originales)
                    self.repl.fallo_transferencia = (numero, modo)
                    with self.assertRaises(instalacion.ErrorInstalacion) as error:
                        self.ejecutar()
                    self.assertTrue(error.exception.recuperado)
                    self.verificar_originales()
        self.repl = ReplSimulado(self.originales)
        self.repl.fallo_compilacion = True
        with self.assertRaises(instalacion.ErrorInstalacion) as error:
            self.ejecutar()
        self.assertTrue(error.exception.recuperado)
        self.verificar_originales()

    def test_fallo_de_arranque_revierte_y_no_divulga_la_excepcion(self):
        def fallar(_repl):
            raise RuntimeError("dato-serial-privado")

        with self.assertRaises(instalacion.ErrorInstalacion) as error:
            self.ejecutar(fallar)
        self.assertTrue(error.exception.recuperado)
        self.assertNotIn("dato-serial-privado", str(error.exception))
        self.verificar_originales()
        for nombre in instalacion.ARCHIVOS[:-1]:
            self.assertEqual(self.repl.archivos[self.temporal + "/resguardo/" + nombre],
                             self.originales[nombre])

    def test_no_acepta_evidencia_de_arranque_incompleta(self):
        for cambio in ({"imports": False}, {"lecturas": 1}, {"pongs": 2},
                       {"reinicios_inesperados": 1}, {"lectores": {"RFID1": "READY"}}):
            with self.subTest(cambio=cambio):
                self.repl = ReplSimulado(self.originales)
                incompleto = dict(self.resultado, **cambio)
                with self.assertRaises(instalacion.ErrorInstalacion) as error:
                    self.ejecutar(lambda _r: incompleto)
                self.assertTrue(error.exception.recuperado)
                self.verificar_originales()

    def test_resguardo_remoto_alterado_no_se_declara_recuperacion_verificada(self):
        def alterar_y_fallar(repl):
            repl.archivos[self.temporal + "/resguardo/config.py"] = b"desconocido"
            raise RuntimeError("Arranque interrumpido")

        with self.assertRaises(instalacion.ErrorInstalacion) as error:
            self.ejecutar(alterar_y_fallar)
        self.assertFalse(error.exception.recuperado)
        self.verificar_originales()
        self.assertEqual(self.repl.archivos[self.temporal + "/resguardo/config.py"], b"desconocido")

    def test_sin_sincronizacion_se_informa_recuperacion_incompleta(self):
        self.repl.fallos_operacion = {1: "despues"}
        self.fallos_resincronizacion = 2
        with self.assertRaises(instalacion.ErrorInstalacion) as error:
            self.ejecutar()
        self.assertFalse(error.exception.recuperado)
        self.assertEqual(self.repl.archivos["/maintenance.flag"], b"1\n")

    def test_reemplazo_de_sesion_se_conserva_si_la_preparacion_falla(self):
        anterior = self.repl
        nueva = ReplSimulado(self.originales)
        nueva.archivos = anterior.archivos
        nueva.directorios = anterior.directorios
        nueva.fallos_preparacion = 1
        vistas = []

        def cambiar(sesion):
            vistas.append(sesion)
            return nueva if len(vistas) == 1 else sesion

        with self.assertRaises(instalacion.ErrorInstalacion) as error:
            instalacion.instalar_stage3(
                repl=anterior, candidato=self.candidato, respaldo=self.respaldo,
                temporal=self.temporal, promocion=promocion, inventariar=lambda r: r.inventario(),
                resincronizar=cambiar, verificar_arranque=lambda _r: self.resultado,
            )
        self.assertTrue(error.exception.recuperado)
        self.assertIs(error.exception.sesion, nueva)
        self.assertEqual(vistas, [anterior, nueva])
        self.verificar_originales()



if __name__ == "__main__":
    unittest.main()
