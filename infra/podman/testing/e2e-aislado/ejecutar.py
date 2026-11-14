#!/usr/bin/env python3
"""Levanta un sandbox efímero para preparar la futura aceptación software."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath

RAIZ = Path(__file__).resolve().parents[4]
CARPETA = Path(__file__).resolve().parent
BASE_DATOS = "smartparking_e2e"
USUARIO_DB = "smartparking_e2e"
HOST_DB = "db"
PUERTO_DB = "5432"
VERSION_PLAYWRIGHT = "1.64.1"
VARIABLES_PROHIBIDAS = (
    "POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "POSTGRES_USER",
    "POSTGRES_PASSWORD", "SPRING_DATASOURCE_URL", "SPRING_DATASOURCE_USERNAME",
    "SPRING_DATASOURCE_PASSWORD", "DATABASE_URL", "JDBC_DATABASE_URL",
    "TEST_API_BASE_URL", "TEST_WEB_BASE_URL", "BASE_URL", "TEST_MAILPIT_BASE_URL",
    "SPNEXT_TEST_FIXTURE_NONCE", "STRIPE_API_KEY", "STRIPE_WEBHOOK_SECRET",
    "SMTP_HOST", "SMTP_PORT", "TEST_RFID1_FISICA", "CONTAINER_HOST",
    "CONTAINER_CONNECTION", "PODMAN_HOST", "PODMAN_CONNECTION", "DOCKER_HOST",
)


class ErrorSandbox(RuntimeError):
    """La preparación no cumple una guarda del sandbox."""


def validar_entorno(entorno: dict[str, str]) -> None:
    presentes = [nombre for nombre in VARIABLES_PROHIBIDAS if entorno.get(nombre)]
    if presentes:
        raise ErrorSandbox("Variables externas no admitidas: " + ", ".join(presentes))


def validar_destino_base(host: str, puerto: str, base: str) -> None:
    if (host, puerto, base) != (HOST_DB, PUERTO_DB, BASE_DATOS):
        raise ErrorSandbox("El destino PostgreSQL no pertenece al sandbox efímero.")


def validar_urls_internas(web: dict[str, str], browser: dict[str, str]) -> None:
    esperadas = {
        "BASE_URL": "http://web:3000",
        "TEST_WEB_BASE_URL": "http://web:3000",
        "TEST_API_BASE_URL": "http://api:8080",
        "TEST_MAILPIT_BASE_URL": "http://mailpit:8025",
    }
    if web.get("NUXT_API_INTERNAL_BASE") != "http://api:8080":
        raise ErrorSandbox("La Web no apunta a la API de pruebas aislada.")
    if any(browser.get(nombre) != valor for nombre, valor in esperadas.items()):
        raise ErrorSandbox("El navegador no usa exclusivamente destinos del sandbox.")


def validar_spec(spec: str, disponibles: set[str]) -> str:
    ruta = PurePosixPath(spec)
    if (
        ruta.is_absolute()
        or not spec.endswith(".spec.ts")
        or ".." in ruta.parts
        or any("fisic" in parte.lower() for parte in ruta.parts)
        or spec not in disponibles
    ):
        raise ErrorSandbox("Spec no permitido: solo se aceptan pruebas software inventariadas.")
    return spec


def specs_software(carpeta: Path) -> set[str]:
    return {
        ruta.relative_to(carpeta).as_posix()
        for ruta in carpeta.rglob("*.spec.ts")
        if ruta.is_file() and not any("fisic" in parte.lower() for parte in ruta.parts)
    }


def ejecutar_podman(*argumentos: str, comprobar: bool = True, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    resultado = subprocess.run(
        ["podman", *argumentos], text=True, capture_output=True, timeout=timeout, check=False,
    )
    if comprobar and resultado.returncode:
        # Los comandos nunca incluyen los valores de los archivos env privados.
        raise ErrorSandbox("Podman falló en " + argumentos[0] + ": " + resultado.stderr.strip())
    return resultado


def inspeccionar(tipo: str, nombre: str) -> dict:
    salida = ejecutar_podman(tipo, "inspect", nombre).stdout
    return json.loads(salida)[0]


def volumen_dependencias(nombre: str) -> Path:
    info = inspeccionar("volume", nombre)
    ruta = Path(info["Mountpoint"])
    if not ruta.is_dir():
        raise ErrorSandbox("No existe el volumen de dependencias solicitado.")
    return ruta


def dependencias_browser() -> Path:
    volumenes = ejecutar_podman("volume", "ls", "--format", "{{.Name}}").stdout.splitlines()
    for nombre in sorted(volumenes):
        if not nombre.endswith("_browser_node_modules"):
            continue
        ruta = volumen_dependencias(nombre)
        paquete = ruta / ".pnpm" / f"@playwright+test@{VERSION_PLAYWRIGHT}" / "node_modules/@playwright/test/package.json"
        if paquete.is_file() and json.loads(paquete.read_text()).get("version") == VERSION_PLAYWRIGHT:
            return ruta
    raise ErrorSandbox("No se encontró una copia local de las dependencias de Playwright 1.64.1.")


def copiar_fuentes(origen: Path, destino: Path) -> None:
    ignorar = shutil.ignore_patterns(
        "node_modules", "target", ".nuxt", ".output", ".env", ".env.*",
        "__pycache__", "playwright-artifacts", "coverage", ".git",
    )
    shutil.copytree(origen, destino, symlinks=True, ignore=ignorar)


def escribir_env(ruta: Path, valores: dict[str, str]) -> None:
    descriptor = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as archivo:
        for nombre, valor in valores.items():
            if "\n" in valor or "\r" in valor:
                raise ErrorSandbox("Valor de entorno sintético inválido.")
            archivo.write(f"{nombre}={valor}\n")


def esperar(descripcion: str, comprobacion, segundos: int = 180) -> None:
    fin = time.monotonic() + segundos
    while time.monotonic() < fin:
        if comprobacion():
            print(descripcion + ": listo", flush=True)
            return
        time.sleep(1)
    raise ErrorSandbox(descripcion + ": no estuvo listo dentro del límite.")


class Sandbox:
    def __init__(self, directorio: Path):
        self.directorio = directorio
        self.identificador = "smartparking-e2e-" + secrets.token_hex(6)
        self.red = self.identificador + "-red"
        self.contenedores: list[str] = []
        self.red_creada = False
        self.clave_db = secrets.token_urlsafe(32)
        self.nonce = secrets.token_urlsafe(32)
        self.clave_dueno = secrets.token_urlsafe(32) + "Aa1!"
        self.correo_dueno = self.identificador + "@example.invalid"

    def crear_contenedor(self, nombre: str, argumentos: list[str], imagen: str, comando: list[str]) -> str:
        resultado = ejecutar_podman(
            "create", "--rm", "--pull=never", "--name", self.identificador + "-" + nombre,
            "--label", "io.smartparking.e2e=" + self.identificador,
            "--network", self.red, "--network-alias", nombre, *argumentos, imagen, *comando,
        )
        identificador = resultado.stdout.strip()
        self.contenedores.append(identificador)
        ejecutar_podman("start", identificador)
        return identificador

    def comprobar_contenedor(self, identificador: str) -> dict:
        info = inspeccionar("container", identificador)
        redes = set((info.get("NetworkSettings") or {}).get("Networks") or {})
        enlaces = (info.get("HostConfig") or {}).get("PortBindings") or {}
        if redes != {self.red} or enlaces:
            raise ErrorSandbox("Un contenedor tiene redes o puertos ajenos al sandbox.")
        if (info.get("Config") or {}).get("Labels", {}).get("io.smartparking.e2e") != self.identificador:
            raise ErrorSandbox("Un contenedor no pertenece a esta ejecución.")
        return info

    def preparar_archivos(self) -> None:
        print("Copiando fuentes y dependencias a un directorio privado...", flush=True)
        copiar_fuentes(RAIZ / "services/api", self.directorio / "api")
        copiar_fuentes(RAIZ / "apps/web", self.directorio / "web")
        copiar_fuentes(RAIZ / "apps/web/tests/browser", self.directorio / "browser")
        shutil.copytree(Path.home() / ".m2/repository", self.directorio / "m2", symlinks=True)
        shutil.copytree(
            volumen_dependencias("smartparking_web_node_modules"),
            self.directorio / "web/node_modules", symlinks=True,
        )
        shutil.copytree(dependencias_browser(), self.directorio / "browser/node_modules", symlinks=True)
        shutil.copy2(CARPETA / "playwright.software.config.ts", self.directorio / "browser/playwright.software.config.ts")
        escribir_env(self.directorio / "db.env", {
            "POSTGRES_USER": USUARIO_DB, "POSTGRES_DB": BASE_DATOS,
            "POSTGRES_PASSWORD": self.clave_db, "PGDATA": "/var/lib/postgresql/data/pgdata",
        })
        escribir_env(self.directorio / "api.env", {
            "SPRING_APPLICATION_NAME": "smartparking-api-e2e-aislado", "SPRING_PROFILE": "test",
            "API_BIND_ADDRESS": "0.0.0.0", "API_PORT": "8080", "POSTGRES_HOST": HOST_DB,
            "POSTGRES_PORT": PUERTO_DB, "POSTGRES_DB": BASE_DATOS, "POSTGRES_USER": USUARIO_DB,
            "POSTGRES_PASSWORD": self.clave_db, "SPNEXT_TEST_FIXTURE_NONCE": self.nonce,
            "SESSION_COOKIE_SECURE": "false", "SMTP_ENABLED": "true", "SMTP_HOST": "mailpit",
            "SMTP_PORT": "1025", "OPERADORES_ORIGEN_ACTIVACION": "http://localhost:3000",
            "OPERADORES_PERMITIR_HTTP_LOCAL": "true", "STRIPE_API_KEY": "", "STRIPE_WEBHOOK_SECRET": "",
        })
        escribir_env(self.directorio / "web.env", {
            "NODE_ENV": "development", "NUXT_API_INTERNAL_BASE": "http://api:8080",
            "NUXT_TELEMETRY_DISABLED": "1", "__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS": "web",
        })
        escribir_env(self.directorio / "browser.env", {
            "BASE_URL": "http://web:3000", "TEST_WEB_BASE_URL": "http://web:3000",
            "TEST_API_BASE_URL": "http://api:8080", "TEST_MAILPIT_BASE_URL": "http://mailpit:8025",
            "TEST_OWNER_EMAIL": self.correo_dueno, "TEST_OWNER_PASSWORD": self.clave_dueno,
            "SPNEXT_TEST_FIXTURE_NONCE": self.nonce, "TEST_RFID1_FISICA": "0",
            "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1", "PLAYWRIGHT_BROWSERS_PATH": "/ms-playwright",
        })

    def iniciar(self) -> None:
        validar_destino_base(HOST_DB, PUERTO_DB, BASE_DATOS)
        ejecutar_podman("network", "create", "--internal", "--label",
                        "io.smartparking.e2e=" + self.identificador, self.red)
        self.red_creada = True
        red = inspeccionar("network", self.red)
        if not red.get("internal") or red.get("labels", {}).get("io.smartparking.e2e") != self.identificador:
            raise ErrorSandbox("La red creada no es interna o no pertenece a esta ejecución.")
        db = self.crear_contenedor("db", [
            "--env-file", str(self.directorio / "db.env"),
            "--tmpfs", "/var/lib/postgresql:rw,size=512m",
        ], "docker.io/library/postgres:18.6-bookworm", [])
        info_db = self.comprobar_contenedor(db)
        montajes = (info_db.get("HostConfig") or {}).get("Tmpfs") or {}
        if "/var/lib/postgresql" not in montajes or info_db.get("Mounts"):
            raise ErrorSandbox("PostgreSQL no tiene almacenamiento exclusivo y efímero.")
        esperar("PostgreSQL", lambda: ejecutar_podman(
            "exec", db, "pg_isready", "-h", "127.0.0.1", "-p", PUERTO_DB,
            "-U", USUARIO_DB, "-d", BASE_DATOS, comprobar=False,
        ).returncode == 0, 60)

        mail = self.crear_contenedor("mailpit", [], "docker.io/axllent/mailpit:v1.32.0", [])
        self.comprobar_contenedor(mail)
        api = self.crear_contenedor("api", [
            "--env-file", str(self.directorio / "api.env"),
            "--volume", str(self.directorio / "api") + ":/workspace:rw",
            "--volume", str(self.directorio / "m2") + ":/qa-m2:rw",
            "--workdir", "/workspace",
        ], "docker.io/library/maven:3.10.0-eclipse-temurin-27", [
            "mvn", "-o", "-Dmaven.repo.local=/qa-m2", "-DskipTests",
            "-Dspring-boot.run.main-class=mx.smartparking.api.integracion.unificacion.SandboxTestApplication",
            "test-compile", "spring-boot:test-run",
        ])
        api_info = self.comprobar_contenedor(api)
        api_env = dict(elemento.split("=", 1) for elemento in api_info["Config"]["Env"] if "=" in elemento)
        validar_destino_base(api_env.get("POSTGRES_HOST", ""), api_env.get("POSTGRES_PORT", ""),
                            api_env.get("POSTGRES_DB", ""))
        if api_env.get("SPRING_PROFILE") != "test" or api_env.get("SPNEXT_TEST_FIXTURE_NONCE") != self.nonce:
            raise ErrorSandbox("La API no tiene el perfil y nonce sintéticos esperados.")
        if api_env.get("STRIPE_API_KEY") or api_env.get("STRIPE_WEBHOOK_SECRET"):
            raise ErrorSandbox("El sandbox no admite credenciales Stripe.")

        web = self.crear_contenedor("web", [
            "--env-file", str(self.directorio / "web.env"),
            "--volume", str(self.directorio / "web") + ":/workspace:rw", "--workdir", "/workspace",
        ], "localhost/smartparking-web-dev:local", ["pnpm", "run", "dev", "--host", "0.0.0.0"])
        web_info = self.comprobar_contenedor(web)
        web_env = dict(elemento.split("=", 1) for elemento in web_info["Config"]["Env"] if "=" in elemento)
        browser = self.crear_contenedor("browser", [
            "--env-file", str(self.directorio / "browser.env"),
            "--volume", str(self.directorio / "web") + ":/proyecto:ro",
            "--volume", str(self.directorio / "browser") + ":/proyecto/tests/browser:rw",
            "--workdir", "/proyecto/tests/browser",
            "--entrypoint", "sleep",
        ], "mcr.microsoft.com/playwright:v1.64.1-noble", ["3600"])
        browser_info = self.comprobar_contenedor(browser)
        browser_env = dict(elemento.split("=", 1) for elemento in browser_info["Config"]["Env"] if "=" in elemento)
        validar_urls_internas(web_env, browser_env)
        if browser_env.get("SPNEXT_TEST_FIXTURE_NONCE") != self.nonce or browser_env.get("TEST_RFID1_FISICA") != "0":
            raise ErrorSandbox("El navegador no tiene nonce sintético o gate físico seguro.")
        comprobar_http = (
            "fetch(process.argv[1]).then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
        )
        esperar("API de pruebas", lambda: ejecutar_podman(
            "exec", browser, "node", "-e", comprobar_http, "http://api:8080/actuator/health",
            comprobar=False,
        ).returncode == 0)
        esperar("Web", lambda: ejecutar_podman(
            "exec", browser, "node", "-e", comprobar_http, "http://web:3000/panel",
            comprobar=False,
        ).returncode == 0)
        esperar("Mailpit sintético", lambda: ejecutar_podman(
            "exec", browser, "node", "-e", comprobar_http, "http://mailpit:8025/api/v1/messages?limit=1",
            comprobar=False,
        ).returncode == 0, 60)
        correo_vacio = (
            "fetch(process.argv[1]).then(r=>r.json()).then(x=>"
            "process.exit(Number(x.total??x.Total??x.messages?.length??0)===0?0:1))"
            ".catch(()=>process.exit(1))"
        )
        if ejecutar_podman(
            "exec", browser, "node", "-e", correo_vacio, "http://mailpit:8025/api/v1/messages?limit=1",
            comprobar=False,
        ).returncode:
            raise ErrorSandbox("La inicialización inesperadamente generó correo sintético.")
        print("Mailpit sintético: sin mensajes.", flush=True)
        ejecutando = ejecutar_podman("top", api, "args").stdout
        if "SandboxTestApplication" not in ejecutando:
            raise ErrorSandbox("La API no arrancó la aplicación del classpath de pruebas.")
        clases = ejecutar_podman("exec", api, "sh", "-c",
            "test -f target/test-classes/mx/smartparking/fixture/SandboxFixtureControlador.class")
        if clases.returncode:
            raise ErrorSandbox("No se compiló el controlador de fixture.")
        procesos_java = ejecutar_podman("exec", api, "jcmd", "-l").stdout.splitlines()
        aplicacion = [
            campos[0] for linea in procesos_java
            if len(campos := linea.split()) > 1
            and campos[1] == "mx.smartparking.api.integracion.unificacion.SandboxTestApplication"
        ]
        if len(aplicacion) != 1:
            raise ErrorSandbox("No se identificó un único proceso de API de pruebas.")
        clases_vivas = ejecutar_podman("exec", api, "jcmd", aplicacion[0], "GC.class_histogram", timeout=60).stdout
        if "mx.smartparking.fixture.SandboxFixtureControlador" not in clases_vivas:
            raise ErrorSandbox("El controlador de fixture no está cargado en la API de pruebas.")
        lista = ejecutar_podman("exec", browser, "./node_modules/.bin/playwright", "test",
                                "--config=playwright.software.config.ts", "--list", timeout=90).stdout
        if "rfid1-asociacion-fisica.spec.ts" in lista or "flujo-completo.spec.ts" not in lista:
            raise ErrorSandbox("El listado no excluyó el spec físico o no incluye el flujo de fixture.")
        print("Perfil test, classpath de fixture y nonce compartido: verificados.", flush=True)
        print("Playwright: spec físico excluido; listado software disponible.", flush=True)
        self.browser = browser

    def correr_spec(self, spec: str) -> None:
        disponibles = specs_software(self.directorio / "browser")
        seleccionado = validar_spec(spec, disponibles)
        resultado = ejecutar_podman(
            "exec", self.browser, "./node_modules/.bin/playwright", "test",
            "--config=playwright.software.config.ts", seleccionado, comprobar=False, timeout=1200,
        )
        # La salida del test podría contener datos sintéticos; no se imprime automáticamente.
        if resultado.returncode:
            raise ErrorSandbox("El spec software terminó con código " + str(resultado.returncode))
        print("Spec software finalizado correctamente.", flush=True)

    def limpiar(self) -> None:
        for identificador in reversed(self.contenedores):
            ejecutar_podman("stop", "--time", "5", identificador, comprobar=False, timeout=15)
            ejecutar_podman("rm", identificador, comprobar=False, timeout=15)
        if self.red_creada:
            ejecutar_podman("network", "rm", self.red, comprobar=False, timeout=15)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("accion", choices=("verificar", "ejecutar"))
    parser.add_argument("--spec", help="Spec software relativo a apps/web/tests/browser.")
    argumentos = parser.parse_args()

    def interrumpir(_numero, _marco):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrumpir)
    try:
        validar_entorno(dict(os.environ))
        disponibles = specs_software(RAIZ / "apps/web/tests/browser")
        if argumentos.accion == "ejecutar":
            if not argumentos.spec:
                raise ErrorSandbox("Indica un spec software explícito con --spec.")
            validar_spec(argumentos.spec, disponibles)
        elif argumentos.spec:
            raise ErrorSandbox("--spec solo corresponde a la acción ejecutar.")
        with tempfile.TemporaryDirectory(prefix="smartparking-e2e-") as temporal:
            directorio = Path(temporal)
            directorio.chmod(0o700)
            sandbox = Sandbox(directorio)
            try:
                sandbox.preparar_archivos()
                sandbox.iniciar()
                if argumentos.accion == "ejecutar":
                    sandbox.correr_spec(argumentos.spec)
            finally:
                sandbox.limpiar()
        return 0
    except (ErrorSandbox, OSError, subprocess.TimeoutExpired) as error:
        print("Sandbox detenido: " + str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Sandbox interrumpido; se retiraron sus recursos.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
