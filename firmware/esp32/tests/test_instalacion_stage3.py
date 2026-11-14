"""Pruebas de instalacion y validacion previa de Stage 3."""

import json
import unittest
from pathlib import Path

from soporte_instalacion_stage3 import (
    SoporteInstalacionStage3,
    huella,
    instalacion,
    promocion,
)


class PruebaInstalacionStage3(SoporteInstalacionStage3):
    def test_instala_con_resguardos_y_evidencia(self):
        resultado = self.ejecutar()
        self.assertIs(resultado["sesion"], self.repl)
        self.assertEqual(resultado["temporal"], self.temporal)
        for nombre in instalacion.ARCHIVOS:
            self.assertEqual(self.repl.archivos["/" + nombre], (self.candidato / nombre).read_bytes())
        for nombre in instalacion.ARCHIVOS[:-1]:
            for carpeta in ("resguardo", "original"):
                self.assertEqual(self.repl.archivos[self.temporal + "/" + carpeta + "/" + nombre],
                                 self.originales[nombre])
        self.assertEqual(self.repl.archivos["/maintenance.flag"], b"1\n")

    def test_candidato_alterado_falla_antes_de_tocar_la_sesion(self):
        (self.candidato / "config.py").write_bytes(b"alterado")
        with self.assertRaises(instalacion.ErrorInstalacion) as error:
            self.ejecutar()
        self.assertIsNone(error.exception.recuperado)
        self.assertIn("sin cambios remotos", str(error.exception))
        self.assertEqual(self.repl.transferencias, 0)
        self.assertEqual(self.repl.operaciones, 0)
        self.verificar_originales()

    def test_instala_un_subconjunto_de_archivos_existentes_y_resguarda_rutas_anidadas(self):
        archivos = ("aplicacion.py", "rfid/lector.py", "rfid/rc522.py")
        candidatos = {
            "aplicacion.py": b"aplicacion candidata",
            "rfid/lector.py": b"lector candidato",
            "rfid/rc522.py": b"rc522 candidato",
        }
        candidato_salud = Path(self.temp.name) / "candidato_salud"
        candidato_salud.mkdir()
        for nombre, datos in candidatos.items():
            ruta = candidato_salud / nombre
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_bytes(datos)
        (candidato_salud / "sha256.json").write_text(json.dumps({
            nombre: huella(datos) for nombre, datos in candidatos.items()
        }))

        resultado = instalacion.instalar_archivos(
            repl=self.repl,
            candidato=candidato_salud,
            respaldo=self.respaldo,
            temporal="/sp_rfid_salud_test",
            promocion=promocion,
            inventariar=lambda repl: repl.inventario(),
            resincronizar=self.resincronizar,
            verificar_arranque=lambda _repl: self.resultado,
            archivos=archivos,
        )

        self.assertEqual(resultado["temporal"], "/sp_rfid_salud_test")
        for nombre, datos in candidatos.items():
            self.assertEqual(self.repl.archivos["/" + nombre], datos)
            for carpeta in ("resguardo", "original"):
                self.assertEqual(
                    self.repl.archivos["/sp_rfid_salud_test/{}/{}".format(carpeta, nombre)],
                    self.originales[nombre],
                )


if __name__ == "__main__":
    unittest.main()
