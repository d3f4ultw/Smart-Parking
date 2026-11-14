"""Comprueba recuperación ante interrupciones de promoción en memoria."""

import hashlib
import unittest

from promocion_firmware import promover, recuperar


def huella(datos):
    return hashlib.sha256(datos.encode()).hexdigest()


class RemotoSimulado:
    def __init__(self, archivos, interrumpir=None, antes=False):
        self.archivos = dict(archivos)
        self.interrumpir = interrumpir
        self.antes = antes
        self.operaciones = 0

    def existe(self, nombre):
        return nombre in self.archivos

    def sha256_remoto(self, nombre):
        return huella(self.archivos[nombre])

    def renombrar(self, origen, destino):
        if destino in self.archivos:
            raise RuntimeError("Destino existente")
        if self.antes and self.operaciones + 1 == self.interrumpir:
            raise TimeoutError("Rename interrumpido antes de ejecutarse")
        self.archivos[destino] = self.archivos.pop(origen)
        self.operaciones += 1
        if self.operaciones == self.interrumpir:
            raise TimeoutError("Resultado de rename incierto")

    def eliminar(self, nombre):
        if self.antes and self.operaciones + 1 == self.interrumpir:
            raise TimeoutError("Delete interrumpido antes de ejecutarse")
        del self.archivos[nombre]
        self.operaciones += 1
        if self.operaciones == self.interrumpir:
            raise TimeoutError("Resultado de delete incierto")


class PruebaPromocion(unittest.TestCase):
    def preparar(self, interrumpir=None):
        nombres = ["config.py", "aplicacion.py", "buzzer.py", "entrada_rfid2.py",
                   "comunicacion/serial.py", "comunicacion/protocolo.py"]
        archivos = {n: (huella("viejo-" + n), huella("nuevo-" + n)) for n in nombres}
        archivos["salida_rfid3.py"] = (None, huella("nuevo-salida_rfid3.py"))
        datos = {n: "viejo-" + n for n in nombres}
        datos.update({"nuevo/" + n: "nuevo-" + n for n in archivos})
        return RemotoSimulado(datos, interrumpir), archivos, nombres

    def test_recupera_trece_interrupciones_con_rename_ya_confirmado(self):
        for interrupcion in range(1, 14):
            with self.subTest(interrupcion=interrupcion):
                remoto, archivos, originales = self.preparar(interrupcion)
                with self.assertRaises(TimeoutError):
                    promover(remoto, archivos, "nuevo", "original")
                remoto.interrumpir = None
                recuperar(remoto, archivos, "original")
                for nombre in originales:
                    self.assertEqual(remoto.archivos[nombre], "viejo-" + nombre)
                self.assertNotIn("salida_rfid3.py", remoto.archivos)

    def test_recupera_interrupciones_antes_de_cada_rename(self):
        for interrupcion in range(1, 14):
            with self.subTest(interrupcion=interrupcion):
                remoto, archivos, originales = self.preparar(interrupcion)
                remoto.antes = True
                with self.assertRaises(TimeoutError):
                    promover(remoto, archivos, "nuevo", "original")
                remoto.interrumpir = None
                recuperar(remoto, archivos, "original")
                for nombre in originales:
                    self.assertEqual(remoto.archivos[nombre], "viejo-" + nombre)
                self.assertNotIn("salida_rfid3.py", remoto.archivos)

    def test_recuperacion_reintentable_ante_interrupcion(self):
        for antes in (False, True):
            for interrupcion in range(1, 14):
                with self.subTest(antes=antes, interrupcion=interrupcion):
                    remoto, archivos, originales = self.preparar()
                    promover(remoto, archivos, "nuevo", "original")
                    remoto.operaciones = 0
                    remoto.interrumpir = interrupcion
                    remoto.antes = antes
                    with self.assertRaises(TimeoutError):
                        recuperar(remoto, archivos, "original")
                    remoto.interrumpir = None
                    recuperar(remoto, archivos, "original")
                    for nombre in originales:
                        self.assertEqual(remoto.archivos[nombre], "viejo-" + nombre)
                    self.assertNotIn("salida_rfid3.py", remoto.archivos)

    def test_recupera_despues_de_promocion_completa(self):
        remoto, archivos, originales = self.preparar()
        promover(remoto, archivos, "nuevo", "original")
        recuperar(remoto, archivos, "original")
        for nombre in originales:
            self.assertEqual(remoto.archivos[nombre], "viejo-" + nombre)
        self.assertNotIn("salida_rfid3.py", remoto.archivos)

    def test_rechaza_bytes_desconocidos_sin_borrarlos(self):
        remoto, archivos, _ = self.preparar()
        promover(remoto, archivos, "nuevo", "original")
        remoto.archivos["salida_rfid3.py"] = "desconocido"
        with self.assertRaises(RuntimeError):
            recuperar(remoto, archivos, "original")
        self.assertEqual(remoto.archivos["salida_rfid3.py"], "desconocido")


if __name__ == "__main__":
    unittest.main()
