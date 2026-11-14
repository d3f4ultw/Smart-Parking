import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from supervisar_droidcam_usb import Configuracion, SupervisorDroidCamUSB


class SupervisorDroidCamUsbTest(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory()
        self.raiz = Path(self.temporal.name)
        self.binario = self.raiz / "adb"
        self.binario.write_text("", encoding="utf-8")
        self.binario.chmod(0o700)
        (self.raiz / "lib").mkdir()
        self.archivo_dispositivo = self.raiz / "dispositivo.txt"
        self.archivo_dispositivo.write_text("vision-device-test\n", encoding="utf-8")
        self.archivo_dispositivo.chmod(0o600)
        self.archivo_estado = self.raiz / "forward.json"
        self.forwards = set()
        self.dispositivos = [("vision-device-test", "device")]
        self.ordenes = []
        self.configuracion = Configuracion(
            ejecutable_adb=self.binario,
            archivo_dispositivo=self.archivo_dispositivo,
            archivo_estado=self.archivo_estado,
            puerto_servidor_adb=5038,
            puerto_local=14747,
            puerto_android=4747,
        )
        self.supervisor = SupervisorDroidCamUSB(self.configuracion)
        self.ld_library_path_original = os.environ.get("LD_LIBRARY_PATH")

    def usar_deteccion_automatica(self):
        self.archivo_dispositivo.unlink()

    def tearDown(self):
        self.temporal.cleanup()

    def adb_simulado(self, comando, **opciones):
        self.ordenes.append((comando, opciones))
        argumentos = comando[1:]
        if argumentos[-1] == "get-state":
            dispositivo = argumentos[argumentos.index("-s") + 1]
            estado = dict(self.dispositivos).get(dispositivo, "device")
            codigo = 0 if estado == "device" else 1
            return subprocess.CompletedProcess(comando, codigo, f"{estado}\n", "")
        if argumentos[-1] == "devices":
            texto = "List of devices attached\n" + "".join(
                f"{dispositivo}\t{estado}\n" for dispositivo, estado in self.dispositivos
            )
            return subprocess.CompletedProcess(comando, 0, texto, "")
        if argumentos[-2:] == ["forward", "--list"]:
            texto = "".join(" ".join(forward) + "\n" for forward in sorted(self.forwards))
            return subprocess.CompletedProcess(comando, 0, texto, "")
        if "--no-rebind" in argumentos:
            dispositivo = argumentos[argumentos.index("-s") + 1]
            local = argumentos[-2]
            remoto = argumentos[-1]
            self.forwards.add((dispositivo, local, remoto))
            return subprocess.CompletedProcess(comando, 0, "", "")
        if "--remove" in argumentos:
            dispositivo = argumentos[argumentos.index("-s") + 1]
            local = argumentos[-1]
            self.forwards = {forward for forward in self.forwards if not (forward[0] == dispositivo and forward[1] == local)}
            return subprocess.CompletedProcess(comando, 0, "", "")
        self.fail(f"Orden ADB inesperada: {argumentos!r}")

    def test_override_reutiliza_forward_existente_y_ancla_sin_adoptarlo(self):
        self.forwards.add(("vision-device-test", "tcp:14747", "tcp:4747"))

        with patch("supervisar_droidcam_usb.subprocess.run", side_effect=self.adb_simulado):
            disponible = self.supervisor.ejecutar_una_vez()

        self.assertTrue(disponible)
        self.assertEqual(1, len(self.forwards))
        datos = json.loads(self.archivo_estado.read_text(encoding="utf-8"))
        self.assertFalse(datos["administradoPorVision"])
        self.assertNotIn("vision-device-test", self.archivo_estado.read_text(encoding="utf-8"))
        self.assertTrue(all(orden[0][1:3] == ["-P", "5038"] for orden in self.ordenes))

    def test_crea_solo_el_forward_reservado_y_usa_ld_library_path_privado(self):
        with patch("supervisar_droidcam_usb.subprocess.run", side_effect=self.adb_simulado):
            disponible = self.supervisor.ejecutar_una_vez()

        self.assertTrue(disponible)
        self.assertEqual({("vision-device-test", "tcp:14747", "tcp:4747")}, self.forwards)
        datos = json.loads(self.archivo_estado.read_text(encoding="utf-8"))
        self.assertTrue(datos["administradoPorVision"])
        self.assertNotIn("vision-device-test", self.archivo_estado.read_text(encoding="utf-8"))
        permisos = self.archivo_estado.stat().st_mode & 0o777
        self.assertEqual(0o600, permisos)
        entorno_adb = self.ordenes[0][1]["env"]
        self.assertTrue(entorno_adb["LD_LIBRARY_PATH"].startswith(str(self.raiz / "lib")))
        self.assertEqual(self.ld_library_path_original, os.environ.get("LD_LIBRARY_PATH"))

    def test_no_reemplaza_forward_que_ocupa_el_puerto_reservado(self):
        self.forwards.add(("otro-dispositivo", "tcp:14747", "tcp:4747"))

        with patch("supervisar_droidcam_usb.subprocess.run", side_effect=self.adb_simulado):
            disponible = self.supervisor.ejecutar_una_vez()

        self.assertFalse(disponible)
        self.assertEqual({("otro-dispositivo", "tcp:14747", "tcp:4747")}, self.forwards)
        self.assertFalse(any("--no-rebind" in orden[0] for orden in self.ordenes))
        self.assertFalse(any("--remove" in orden[0] for orden in self.ordenes))

    def test_no_crea_forward_si_el_dispositivo_no_esta_autorizado(self):
        def adb_no_autorizado(comando, **opciones):
            self.ordenes.append((comando, opciones))
            return subprocess.CompletedProcess(comando, 1, "unauthorized\n", "")

        with patch("supervisar_droidcam_usb.subprocess.run", side_effect=adb_no_autorizado):
            disponible = self.supervisor.ejecutar_una_vez()

        self.assertFalse(disponible)
        self.assertEqual(1, len(self.ordenes))
        self.assertFalse(self.archivo_estado.exists())

    def test_al_detener_retira_unicamente_forward_con_marcador_propio(self):
        self.supervisor._guardar_estado("vision-device-test", administrado=True)
        self.forwards.add(("vision-device-test", "tcp:14747", "tcp:4747"))

        with patch("supervisar_droidcam_usb.subprocess.run", side_effect=self.adb_simulado):
            self.supervisor._retirar_forward_propio()

        self.assertFalse(self.forwards)
        self.assertFalse(self.archivo_estado.exists())
        retiro = [orden[0] for orden in self.ordenes if "--remove" in orden[0]]
        self.assertEqual(1, len(retiro))
        self.assertIn("-P", retiro[0])
        self.assertIn("5038", retiro[0])

    def test_archivo_de_identidad_requiere_permisos_privados(self):
        self.archivo_dispositivo.chmod(0o644)

        with patch("supervisar_droidcam_usb.subprocess.run", side_effect=self.adb_simulado):
            disponible = self.supervisor.ejecutar_una_vez()

        self.assertFalse(disponible)
        self.assertEqual([], self.ordenes)

    def test_deteccion_automatica_acepta_un_android_autorizado(self):
        self.usar_deteccion_automatica()

        with self.assertLogs(level="INFO") as registros:
            with patch("supervisar_droidcam_usb.subprocess.run", side_effect=self.adb_simulado):
                disponible = self.supervisor.ejecutar_una_vez()

        self.assertTrue(disponible)
        self.assertEqual({("vision-device-test", "tcp:14747", "tcp:4747")}, self.forwards)
        self.assertTrue(any(orden[0][-1] == "devices" for orden in self.ordenes))
        datos = json.loads(self.archivo_estado.read_text(encoding="utf-8"))
        self.assertTrue(datos["administradoPorVision"])
        self.assertNotIn("vision-device-test", self.archivo_estado.read_text(encoding="utf-8"))
        self.assertNotIn("vision-device-test", " ".join(registros.output))

    def test_deteccion_automatica_espera_si_no_hay_dispositivos(self):
        self.usar_deteccion_automatica()
        self.dispositivos = []

        with patch("supervisar_droidcam_usb.subprocess.run", side_effect=self.adb_simulado):
            disponible = self.supervisor.ejecutar_una_vez()

        self.assertFalse(disponible)
        self.assertEqual(1, len(self.ordenes))
        self.assertEqual("devices", self.ordenes[0][0][-1])
        self.assertFalse(self.forwards)

    def test_deteccion_automatica_espera_si_el_unico_dispositivo_no_esta_autorizado(self):
        self.usar_deteccion_automatica()
        self.dispositivos = [("vision-device-test", "unauthorized")]

        with patch("supervisar_droidcam_usb.subprocess.run", side_effect=self.adb_simulado):
            disponible = self.supervisor.ejecutar_una_vez()

        self.assertFalse(disponible)
        self.assertEqual(1, len(self.ordenes))
        self.assertFalse(self.forwards)

    def test_deteccion_automatica_espera_si_hay_varios_dispositivos(self):
        self.usar_deteccion_automatica()
        self.dispositivos = [
            ("vision-device-test", "device"),
            ("otro-dispositivo", "unauthorized"),
        ]

        with patch("supervisar_droidcam_usb.subprocess.run", side_effect=self.adb_simulado):
            disponible = self.supervisor.ejecutar_una_vez()

        self.assertFalse(disponible)
        self.assertEqual(1, len(self.ordenes))
        self.assertFalse(self.forwards)

    def test_hash_anclado_impide_cambiar_android_despues_de_reconexion(self):
        self.usar_deteccion_automatica()
        self.supervisor._guardar_estado("android-original", administrado=True)
        self.dispositivos = [("android-diferente", "device")]

        with patch("supervisar_droidcam_usb.subprocess.run", side_effect=self.adb_simulado):
            disponible = self.supervisor.ejecutar_una_vez()

        self.assertFalse(disponible)
        self.assertEqual(1, len(self.ordenes))
        self.assertFalse(self.forwards)

    def test_override_no_puede_cambiar_un_android_anclado(self):
        self.supervisor._guardar_estado("android-original", administrado=True)

        with patch("supervisar_droidcam_usb.subprocess.run", side_effect=self.adb_simulado):
            disponible = self.supervisor.ejecutar_una_vez()

        self.assertFalse(disponible)
        self.assertEqual([], self.ordenes)
        self.assertFalse(self.forwards)

    def test_forward_preexistente_sin_marcador_se_reutiliza_y_nunca_se_retira(self):
        self.usar_deteccion_automatica()
        self.forwards.add(("vision-device-test", "tcp:14747", "tcp:4747"))

        with patch("supervisar_droidcam_usb.subprocess.run", side_effect=self.adb_simulado):
            disponible = self.supervisor.ejecutar_una_vez()

        self.assertTrue(disponible)
        datos = json.loads(self.archivo_estado.read_text(encoding="utf-8"))
        self.assertFalse(datos["administradoPorVision"])

        with patch("supervisar_droidcam_usb.subprocess.run", side_effect=self.adb_simulado):
            self.supervisor._retirar_forward_propio()

        self.assertEqual({("vision-device-test", "tcp:14747", "tcp:4747")}, self.forwards)
        self.assertFalse(any("--remove" in orden[0] for orden in self.ordenes))


if __name__ == "__main__":
    unittest.main()
