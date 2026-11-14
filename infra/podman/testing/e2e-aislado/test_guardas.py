"""Pruebas de las guardas del entorno E2E, sin Podman ni red."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from ejecutar import (
    ErrorSandbox,
    escribir_env,
    specs_software,
    validar_destino_base,
    validar_entorno,
    validar_spec,
    validar_urls_internas,
)


class GuardasSandboxTest(unittest.TestCase):
    def test_rechaza_overrides_de_db_url_y_gate_fisico_sin_exponer_valores(self):
        for nombre in (
            "POSTGRES_HOST", "POSTGRES_DB", "SPRING_DATASOURCE_URL", "DATABASE_URL",
            "TEST_API_BASE_URL", "SPNEXT_TEST_FIXTURE_NONCE", "TEST_RFID1_FISICA",
            "STRIPE_API_KEY", "CONTAINER_HOST",
        ):
            with self.subTest(nombre=nombre):
                with self.assertRaises(ErrorSandbox) as error:
                    validar_entorno({nombre: "valor-no-mostrado"})
                self.assertNotIn("valor-no-mostrado", str(error.exception))
        validar_entorno({})

    def test_destino_postgres_solo_admite_alias_y_base_del_sandbox(self):
        validar_destino_base("db", "5432", "smartparking_e2e")
        for valores in (
            ("127.0.0.1", "5432", "smartparking_e2e"),
            ("db", "5433", "smartparking_e2e"),
            ("db", "5432", "smartparking_local"),
        ):
            with self.subTest(valores=valores):
                with self.assertRaises(ErrorSandbox):
                    validar_destino_base(*valores)

    def test_seleccion_explicitamente_excluye_fisicos_y_rutas_externas(self):
        permitidos = {"unificacion/flujo-completo.spec.ts", "login.spec.ts"}
        self.assertEqual(
            "unificacion/flujo-completo.spec.ts",
            validar_spec("unificacion/flujo-completo.spec.ts", permitidos),
        )
        for ruta in (
            "rfid1-asociacion-fisica.spec.ts", "RFID-FISICO.spec.ts",
            "../login.spec.ts", "/tmp/login.spec.ts", "inexistente.spec.ts",
        ):
            with self.subTest(ruta=ruta):
                with self.assertRaises(ErrorSandbox):
                    validar_spec(ruta, permitidos)

    def test_destinos_web_y_navegador_no_admiten_urls_externas(self):
        web = {"NUXT_API_INTERNAL_BASE": "http://api:8080"}
        browser = {
            "BASE_URL": "http://web:3000",
            "TEST_WEB_BASE_URL": "http://web:3000",
            "TEST_API_BASE_URL": "http://api:8080",
            "TEST_MAILPIT_BASE_URL": "http://mailpit:8025",
        }
        validar_urls_internas(web, browser)
        with self.assertRaises(ErrorSandbox):
            validar_urls_internas({"NUXT_API_INTERNAL_BASE": "http://127.0.0.1:8080"}, browser)
        with self.assertRaises(ErrorSandbox):
            validar_urls_internas(web, {**browser, "TEST_API_BASE_URL": "http://example.invalid"})

    def test_inventario_omite_specs_fisicos(self):
        with tempfile.TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            (raiz / "login.spec.ts").touch()
            (raiz / "rfid1-asociacion-fisica.spec.ts").touch()
            self.assertEqual({"login.spec.ts"}, specs_software(raiz))

    def test_archivo_env_es_privado_y_no_sobrescribe(self):
        with tempfile.TemporaryDirectory() as temporal:
            ruta = Path(temporal) / "api.env"
            escribir_env(ruta, {"TOKEN": "sintetico"})
            self.assertEqual(0o600, os.stat(ruta).st_mode & 0o777)
            with self.assertRaises(FileExistsError):
                escribir_env(ruta, {"TOKEN": "otro"})
            self.assertEqual("TOKEN=sintetico\n", ruta.read_text())


if __name__ == "__main__":
    unittest.main()
