"""Ejercita la instalación Stage 3 sin acceso a dispositivo ni servicios."""

import ast
import hashlib
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


RAIZ = Path(__file__).resolve().parents[3]
HERRAMIENTA = RAIZ / "firmware/esp32/tools/instalacion_stage3.py"
PROMOCION = RAIZ / "infra/podman/testing/rfid3-stage3-20261031-1647/promocion_firmware.py"


def cargar(nombre, ruta):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


instalacion = cargar("instalacion_stage3_prueba", HERRAMIENTA)
promocion = cargar("promocion_stage3_prueba", PROMOCION)


def huella(datos):
    return hashlib.sha256(datos).hexdigest()


class ReplSimulado:
    def __init__(self, archivos):
        self.archivos = {"/" + nombre: contenido for nombre, contenido in archivos.items()}
        self.archivos["/maintenance.flag"] = b"1\n"
        self.directorios = {"/", "/comunicacion", "/rfid"}
        self.operaciones = 0
        self.transferencias = 0
        self.fallos_operacion = {}
        self.fallo_transferencia = None
        self.fallo_compilacion = False
        self.fallos_preparacion = 0

    def preparar_escritura(self):
        if self.fallos_preparacion:
            self.fallos_preparacion -= 1
            raise TimeoutError("Prompt no sincronizado")

    def existe(self, ruta):
        padre = ruta.rpartition("/")[0] or "/"
        if padre not in self.directorios:
            raise FileNotFoundError("Directorio remoto inexistente")
        return ruta in self.archivos or ruta in self.directorios

    def espacio_disponible(self):
        return 1000000

    def crear_directorio(self, ruta):
        if self.existe(ruta):
            raise FileExistsError(ruta)
        self.directorios.add(ruta)

    def transferir(self, origen, destino):
        self.transferencias += 1
        modo = self.fallo_transferencia if self.fallo_transferencia and self.fallo_transferencia[0] == self.transferencias else None
        if modo and modo[1] == "antes":
            raise TimeoutError("Transferencia sin confirmar")
        if self.existe(destino):
            raise FileExistsError(destino)
        contenido = Path(origen).read_bytes()
        self.archivos[destino] = contenido
        if modo:
            raise TimeoutError("Acuse de transferencia perdido")
        return len(contenido), huella(contenido)

    def sha256_remoto(self, nombre):
        return huella(self.archivos[nombre])

    def consultar_linea(self, prefijo, _codigo):
        if prefijo == "FLAG:":
            return self.archivos["/maintenance.flag"].hex()
        if prefijo == "COMPILA:":
            if self.fallo_compilacion:
                raise TimeoutError("Compilación no confirmada")
            return "OK"
        raise AssertionError("Consulta inesperada")

    def comando(self, codigo):
        llamada = ast.parse(codigo).body[0].value
        metodo = llamada.func.attr
        argumentos = [ast.literal_eval(argumento) for argumento in llamada.args]
        self.operaciones += 1
        fallo = self.fallos_operacion.pop(self.operaciones, None)
        if fallo == "antes":
            raise TimeoutError("Operación no confirmada")
        if metodo == "rename":
            origen, destino = argumentos
            if destino in self.archivos:
                raise FileExistsError(destino)
            self.archivos[destino] = self.archivos.pop(origen)
        elif metodo == "remove":
            del self.archivos[argumentos[0]]
        else:
            raise AssertionError("Operación inesperada")
        if fallo == "despues":
            raise TimeoutError("Acuse de operación perdido")

    def inventario(self):
        return {nombre.lstrip("/"): len(datos) for nombre, datos in self.archivos.items()}


class SoporteInstalacionStage3(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.candidato = Path(self.temp.name) / "candidato"
        self.respaldo = Path(self.temp.name) / "respaldo"
        self.candidato.mkdir()
        self.respaldo.mkdir()
        self.originales = {nombre: ("original-" + nombre).encode() for nombre in instalacion.ARCHIVOS[:-1]}
        self.originales.update({"boot.py": b"boot", "main.py": b"main",
                                "comunicacion/__init__.py": b"modulo",
                                "rfid/lector.py": b"lector", "rfid/rc522.py": b"controlador"})
        registros = []
        for nombre, datos in self.originales.items():
            ruta = self.respaldo / nombre
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_bytes(datos)
            registros.append({"ruta": nombre, "bytes": len(datos), "sha256": huella(datos)})
        (self.respaldo / "manifiesto.json").write_text(json.dumps(registros))
        candidatos = {}
        for nombre in instalacion.ARCHIVOS:
            datos = ("candidato-" + nombre).encode()
            ruta = self.candidato / nombre
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_bytes(datos)
            candidatos[nombre] = huella(datos)
        (self.candidato / "sha256.json").write_text(json.dumps(candidatos))
        self.repl = ReplSimulado(self.originales)
        self.resincronizaciones = 0
        self.fallos_resincronizacion = 0
        self.temporal = "/sp_rfid3_stage3_test"
        self.resultado = {"imports": True, "lectores": {"RFID1": "READY", "RFID2": "READY", "RFID3": "READY"},
                          "pongs": 3, "reinicios_inesperados": 0, "lecturas": 0}

    def resincronizar(self, sesion):
        self.resincronizaciones += 1
        if self.fallos_resincronizacion:
            self.fallos_resincronizacion -= 1
            raise TimeoutError("No se pudo sincronizar")
        return sesion

    def ejecutar(self, callback=None):
        return instalacion.instalar_stage3(
            repl=self.repl, candidato=self.candidato, respaldo=self.respaldo,
            temporal=self.temporal, promocion=promocion, inventariar=lambda r: r.inventario(),
            resincronizar=self.resincronizar, verificar_arranque=callback or (lambda _r: self.resultado),
        )

    def verificar_originales(self):
        for nombre, datos in self.originales.items():
            self.assertEqual(self.repl.archivos["/" + nombre], datos)
        self.assertNotIn("/salida_rfid3.py", self.repl.archivos)
        self.assertEqual(self.repl.archivos["/maintenance.flag"], b"1\n")

