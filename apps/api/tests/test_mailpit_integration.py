"""Smoke opcional del flujo de invitaciones contra Mailpit local."""

from __future__ import annotations

import builtins
import json
import os
import re
import time
from datetime import UTC, datetime, timedelta
from email import policy
from email.parser import BytesParser
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select, update
from sqlalchemy.orm import Session

import main as modulo_main
from app.api.rutas import activaciones_operador, autenticacion, operadores
from app.cli import crear_admin
from app.cli.invitaciones_admin import crear_callback_entrega_admin
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models import ActivacionCuenta, Usuario
from app.servicios.administradores import reenviar_invitacion_administrador

pytestmark = pytest.mark.skipif(
    os.environ.get("SP033_MAILPIT_INTEGRATION") != "1",
    reason="Requiere Mailpit local y SP033_MAILPIT_INTEGRATION=1.",
)

RUTA_ACTIVACION = "/api/autenticacion/activacion-operador"
RUTA_OPERADORES = "/api/admin/operadores"
CONTRASENA_ADMIN = "Activacion SP033 ADMIN 123"
CONTRASENA_OPERADOR = "Activacion SP033 OPERADOR 123"


def _asegurar(condicion: bool, mensaje: str) -> None:
    """Falla con texto fijo para no filtrar enlaces ni tokens capturados."""

    if not condicion:
        raise AssertionError(mensaje)


def _url_api_mailpit() -> str:
    return os.environ.get(
        "SP033_MAILPIT_API_URL",
        "http://mailpit:8025",
    ).rstrip("/")


def _solicitar_mailpit(
    ruta: str,
    *,
    metodo: str = "GET",
    cuerpo: dict[str, Any] | None = None,
) -> dict[str, Any] | str:
    datos = None if cuerpo is None else json.dumps(cuerpo).encode("utf-8")
    solicitud = Request(
        f"{_url_api_mailpit()}{ruta}",
        data=datos,
        headers={"Content-Type": "application/json"},
        method=metodo,
    )
    try:
        with urlopen(solicitud, timeout=5) as respuesta:
            _asegurar(
                respuesta.status == 200,
                "Mailpit devolvió un estado HTTP inesperado.",
            )
            contenido = respuesta.read().decode("utf-8")
    except HTTPError, URLError, OSError, TimeoutError:
        raise AssertionError("La API local de Mailpit no respondió.") from None
    if ruta.endswith("/raw"):
        return contenido
    if not contenido:
        return ""
    try:
        return json.loads(contenido)
    except json.JSONDecodeError:
        return contenido


def _buscar_mensajes(
    correo: str,
    *,
    inicio: int = 0,
    limite: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    consulta = urlencode(
        {
            "query": f'to:"{correo}"',
            "start": str(inicio),
            "limit": str(limite),
        }
    )
    resultado = _solicitar_mailpit(f"/api/v1/search?{consulta}")
    if not isinstance(resultado, dict):
        raise AssertionError("Mailpit devolvió una búsqueda inválida.")
    mensajes = resultado.get("messages")
    cantidad = resultado.get("messages_count")
    if not isinstance(mensajes, list) or type(cantidad) is not int:
        raise AssertionError("Mailpit devolvió una estructura de búsqueda inválida.")
    mensajes_validos: list[dict[str, Any]] = []
    for mensaje in mensajes:
        if not isinstance(mensaje, dict):
            raise AssertionError("Mailpit devolvió un mensaje sin ID válido.")
        identificador = mensaje.get("ID")
        if not isinstance(identificador, str) or not identificador:
            raise AssertionError("Mailpit devolvió un mensaje sin ID válido.")
        mensajes_validos.append(cast(dict[str, Any], mensaje))
    return mensajes_validos, cantidad


def _ids_de_mensajes(correo: str) -> list[str]:
    mensajes, _cantidad = _buscar_mensajes(correo)
    return [mensaje["ID"] for mensaje in mensajes]


def _asegurar_cantidad_mensajes(correo: str, cantidad_esperada: int) -> list[str]:
    mensajes, cantidad = _buscar_mensajes(correo)
    _asegurar(
        len(mensajes) == cantidad_esperada and cantidad == cantidad_esperada,
        "Mailpit devolvió una cantidad inesperada para el destinatario sintético.",
    )
    return [mensaje["ID"] for mensaje in mensajes]


def _esperar_mensajes(correo: str, cantidad: int) -> list[str]:
    limite = time.monotonic() + 5
    ids: list[str] = []
    while time.monotonic() < limite:
        ids = _ids_de_mensajes(correo)
        if len(ids) >= cantidad:
            return ids
        time.sleep(0.1)
    _asegurar(False, "Mailpit no recibió la cantidad esperada de mensajes.")
    return ids


def _eliminar_mensajes(ids: set[str] | list[str]) -> None:
    ids_unicos = sorted(set(ids))
    _asegurar(bool(ids_unicos), "Se rechazó un borrado Mailpit sin IDs explícitos.")
    respuesta = _solicitar_mailpit(
        "/api/v1/messages",
        metodo="DELETE",
        cuerpo={"IDs": ids_unicos},
    )
    _asegurar(respuesta == "ok", "Mailpit no confirmó el borrado solicitado.")


def _limpiar_mensajes(correos: list[str]) -> None:
    ids = {
        identificador
        for correo in correos
        for identificador in _ids_de_mensajes(correo)
    }
    if ids:
        _eliminar_mensajes(ids)
    for correo in correos:
        _asegurar_cantidad_mensajes(correo, 0)


def _enviar_mensaje_sintetico(correo: str, etiqueta: str) -> str:
    respuesta = _solicitar_mailpit(
        "/api/v1/send",
        metodo="POST",
        cuerpo={
            "From": {"Email": "no-reply@example.test"},
            "To": [{"Email": correo}],
            "Subject": f"Prueba local Mailpit {etiqueta}",
            "Text": "Mensaje sintético para verificar borrado por ID.",
        },
    )
    if not isinstance(respuesta, dict):
        raise AssertionError("Mailpit no devolvió el ID del mensaje sintético enviado.")
    identificador = respuesta.get("ID")
    if not isinstance(identificador, str) or not identificador:
        raise AssertionError("Mailpit no devolvió el ID del mensaje sintético enviado.")
    return identificador


def _ids_inventario_mailpit() -> set[str]:
    inicio = 0
    ids: set[str] = set()
    while True:
        consulta = urlencode({"start": str(inicio), "limit": "50"})
        resultado = _solicitar_mailpit(f"/api/v1/messages?{consulta}")
        if not isinstance(resultado, dict):
            raise AssertionError("Mailpit devolvió un inventario inválido.")
        mensajes = resultado.get("messages")
        total = resultado.get("total")
        if not isinstance(mensajes, list) or type(total) is not int:
            raise AssertionError("Mailpit devolvió una página de inventario inválida.")
        for mensaje in mensajes:
            if not isinstance(mensaje, dict):
                raise AssertionError(
                    "Mailpit devolvió un mensaje de inventario sin ID válido."
                )
            identificador = mensaje.get("ID")
            if not isinstance(identificador, str) or not identificador:
                raise AssertionError(
                    "Mailpit devolvió un mensaje de inventario sin ID válido."
                )
            ids.add(identificador)
        siguiente = inicio + len(mensajes)
        if siguiente >= total:
            if len(ids) < total:
                raise AssertionError(
                    "Mailpit terminó la paginación antes de cubrir el total del buzón."
                )
            return ids
        if not mensajes:
            raise AssertionError(
                "Mailpit terminó la paginación antes de cubrir el total del buzón."
            )
        inicio = siguiente


def test_mailpit_limpieza_por_id_preserva_control() -> None:
    """Regresión determinista de búsqueda, borrado exacto y preservación."""

    sufijo = uuid4().hex
    correo_objetivo = f"sp033-limpieza-target-{sufijo}@example.test"
    correo_control = f"sp033-limpieza-control-{sufijo}@example.test"
    correos = [correo_objetivo, correo_control]
    ids_sinteticos: set[str] = set()

    try:
        _solicitar_mailpit("/readyz")
        with pytest.raises(
            AssertionError,
            match="borrado Mailpit sin IDs explícitos",
        ):
            _eliminar_mensajes([])
        id_objetivo_enviado = _enviar_mensaje_sintetico(
            correo_objetivo,
            "target",
        )
        ids_sinteticos.add(id_objetivo_enviado)
        id_control_enviado = _enviar_mensaje_sintetico(correo_control, "control")
        ids_sinteticos.add(id_control_enviado)

        ids_objetivo = _asegurar_cantidad_mensajes(correo_objetivo, 1)
        ids_control = _asegurar_cantidad_mensajes(correo_control, 1)
        (id_objetivo,) = ids_objetivo
        (id_control,) = ids_control
        _asegurar(
            id_objetivo == id_objetivo_enviado and id_control == id_control_enviado,
            "La búsqueda no encontró los IDs exactos devueltos por Mailpit.",
        )

        _eliminar_mensajes([id_objetivo])
        _asegurar_cantidad_mensajes(correo_objetivo, 0)

        ids_buzon = _ids_inventario_mailpit()
        _asegurar(
            id_objetivo not in ids_buzon and id_control in ids_buzon,
            "El borrado por ID no eliminó solo el mensaje objetivo.",
        )
    finally:
        ids_limpieza = set(ids_sinteticos)
        for correo in correos:
            ids_limpieza.update(_ids_de_mensajes(correo))
        if ids_limpieza:
            _eliminar_mensajes(ids_limpieza)
        for correo in correos:
            _asegurar_cantidad_mensajes(correo, 0)


def _cuerpos_mensaje(identificador: str) -> tuple[str, str]:
    fuente = _solicitar_mailpit(f"/api/v1/message/{identificador}/raw")
    if not isinstance(fuente, str):
        raise AssertionError("Mailpit devolvió un mensaje inválido.")
    mensaje = BytesParser(policy=policy.default).parsebytes(fuente.encode("utf-8"))
    plano = mensaje.get_body(preferencelist=("plain",))
    html = mensaje.get_body(preferencelist=("html",))
    return (
        str(plano.get_content()) if plano else "",
        str(html.get_content()) if html else "",
    )


def _leer_invitacion(
    identificador: str,
    settings: Settings,
) -> tuple[str, str, str]:
    plano, html = _cuerpos_mensaje(identificador)
    enlaces = re.findall(r"https?://[^\s<>\"']+", f"{plano}\n{html}")
    enlaces = [enlace.rstrip(".,;)]}") for enlace in enlaces]
    enlaces_activacion = [
        enlace for enlace in enlaces if urlsplit(enlace).path == "/activar-cuenta"
    ]
    enlaces_unicos = set(enlaces_activacion)
    _asegurar(
        len(enlaces_unicos) == 1,
        "La invitación no contiene exactamente un enlace lógico de activación.",
    )
    enlace = next(iter(enlaces_unicos))
    partes = urlsplit(enlace)
    origen = urlsplit(settings.app_public_url)
    consulta = parse_qs(partes.query)
    _asegurar(
        (partes.scheme, partes.netloc) == (origen.scheme, origen.netloc),
        "La invitación no usa APP_PUBLIC_URL.",
    )
    _asegurar(
        set(consulta) == {"token"} and len(consulta["token"]) == 1,
        "La invitación no usa el contrato token-only.",
    )
    texto = f"{plano}\n{html}".casefold()
    _asegurar(
        "codigo de verificacion" not in texto
        and "código de verificación" not in texto
        and "contraseña temporal" not in texto
        and "contrasena temporal" not in texto
        and "smart_parking_activation_challenge" not in texto,
        "La invitación incluye credenciales que deben permanecer fuera del correo.",
    )
    return enlace, consulta["token"][0], texto


def _activar_cuenta(client: TestClient, token: str, contrasena: str) -> list[str]:
    respuestas = [
        client.post(f"{RUTA_ACTIVACION}/enlace", json={"token": token}),
        client.get(f"{RUTA_ACTIVACION}/desafio"),
        client.post(
            f"{RUTA_ACTIVACION}/completar",
            json={"nueva_contrasena": contrasena},
        ),
    ]
    _asegurar(
        respuestas[0].status_code == 204, "No se pudo canjear el enlace capturado."
    )
    _asegurar(
        respuestas[1].status_code == 200 and respuestas[1].json().get("valido") is True,
        "La cookie de desafío de activación no fue aceptada.",
    )
    _asegurar(
        respuestas[2].status_code == 200
        and respuestas[2].json().get("estado") == "cuenta_activada",
        "No se pudo completar la activación capturada.",
    )
    return [respuesta.text for respuesta in respuestas]


def test_sp033_invitaciones_resend_y_activacion_con_mailpit(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    valores = get_settings()
    settings = valores.model_copy(
        update={
            "app_environment": "development",
            "correo_transporte": "smtp",
            "app_public_url": os.environ.get(
                "APP_PUBLIC_URL",
                "http://localhost:3000",
            ),
            "smtp_host": "mailpit",
            "smtp_port": "1025",
            "smtp_username": "",
            "smtp_password": SecretStr(""),
            "smtp_from_email": "no-reply@example.test",
            "smtp_from_name": "Smart Parking",
            "smtp_security": "none",
        }
    )
    if settings.smtp_password is None:
        raise AssertionError("El perfil Mailpit requiere SMTP_PASSWORD vacía.")
    _asegurar(
        settings.smtp_host == "mailpit"
        and settings.smtp_security == "none"
        and not settings.smtp_username
        and not settings.smtp_password.get_secret_value(),
        "El smoke debe usar solo el SMTP local sin autenticación.",
    )
    _solicitar_mailpit("/readyz")

    sufijo = uuid4().hex
    correo_admin = f"sp033-admin-{sufijo}@example.com"
    correo_operador = f"sp033-operador-{sufijo}@example.com"
    correos = [correo_admin, correo_operador]
    salidas_cli: list[str] = []
    respuestas_http: list[str] = []
    tokens: list[str] = []

    def entregar_db() -> Any:
        yield db

    monkeypatch.setitem(modulo_main.app.dependency_overrides, get_db, entregar_db)
    monkeypatch.setattr(modulo_main, "get_settings", lambda: settings)
    monkeypatch.setattr(activaciones_operador, "get_settings", lambda: settings)
    monkeypatch.setattr(autenticacion, "get_settings", lambda: settings)
    monkeypatch.setattr(operadores, "get_settings", lambda: settings)

    try:
        respuestas_cli = iter(["Ada", "Lovelace", "Byron", correo_admin])
        monkeypatch.setattr(builtins, "input", lambda _prompt: next(respuestas_cli))
        _asegurar(
            crear_admin.main(db=db, settings=settings) == 0,
            "El CLI ADMIN no completó la creación de invitación.",
        )
        salida = capsys.readouterr()
        salidas_cli.extend((salida.out, salida.err))
        _asegurar(
            "Correo de activacion enviado." in salida.out
            and "/activar-cuenta?token=" not in salida.out + salida.err,
            "El CLI ADMIN no reportó éxito neutral.",
        )

        ids_admin = _esperar_mensajes(correo_admin, 1)
        _asegurar(len(ids_admin) == 1, "Mailpit no recibió la invitación ADMIN.")
        enlace_admin_1, token_admin_1, _texto_admin_1 = _leer_invitacion(
            ids_admin[0],
            settings,
        )
        tokens.append(token_admin_1)

        usuario_admin = db.scalar(select(Usuario).where(Usuario.correo == correo_admin))
        if usuario_admin is None:
            raise AssertionError("No se creó el ADMIN sintético de prueba.")
        db.commit()
        reenviar_invitacion_administrador(
            db,
            usuario_admin.id,
            cooldown_segundos=settings.activacion_reenvio_cooldown_segundos,
            duracion_token_horas=settings.activation_token_ttl_hours,
            entregar_invitacion=crear_callback_entrega_admin(settings=settings),
            ahora=datetime.now(UTC) + timedelta(minutes=2),
        )
        ids_admin = _esperar_mensajes(correo_admin, 2)
        _asegurar(len(ids_admin) == 2, "Mailpit no recibió el reenvío ADMIN.")
        enlace_admin_2, token_admin_2, _texto_admin_2 = _leer_invitacion(
            ids_admin[0],
            settings,
        )
        tokens.append(token_admin_2)
        _asegurar(
            token_admin_1 != token_admin_2,
            "El reenvío ADMIN no generó un token distinto.",
        )

        with TestClient(modulo_main.app) as client:
            respuestas_http.extend(
                _activar_cuenta(client, token_admin_2, CONTRASENA_ADMIN)
            )
            login = client.post(
                "/api/autenticacion/login",
                json={"correo": correo_admin, "contrasena": CONTRASENA_ADMIN},
            )
            respuestas_http.append(login.text)
            _asegurar(
                login.status_code == 200 and login.json().get("rol") == "ADMIN",
                "El ADMIN activado no pudo autenticarse.",
            )

            crear_respuesta = client.post(
                RUTA_OPERADORES,
                json={
                    "nombre": "SP033",
                    "apellido_paterno": "Operador",
                    "apellido_materno": "Prueba",
                    "correo": correo_operador,
                },
            )
            respuestas_http.append(crear_respuesta.text)
            _asegurar(
                crear_respuesta.status_code == 201
                and crear_respuesta.json().get("estado") == "operador_creado",
                "El panel ADMIN no pudo crear la invitación OPERADOR.",
            )

            ids_operador = _esperar_mensajes(correo_operador, 1)
            _asegurar(
                len(ids_operador) == 1,
                "Mailpit no recibió la invitación OPERADOR.",
            )
            enlace_operador_1, token_operador_1, _texto_operador_1 = _leer_invitacion(
                ids_operador[0],
                settings,
            )
            tokens.append(token_operador_1)

            usuario_operador = db.scalar(
                select(Usuario).where(Usuario.correo == correo_operador)
            )
            if usuario_operador is None:
                raise AssertionError("No se creó el OPERADOR sintético de prueba.")
            fecha_sin_cooldown = datetime.now(UTC) - timedelta(
                seconds=settings.activacion_reenvio_cooldown_segundos + 5
            )
            db.execute(
                update(ActivacionCuenta)
                .where(ActivacionCuenta.usuario_id == usuario_operador.id)
                .values(
                    creado_en=fecha_sin_cooldown,
                    ultimo_reenvio_en=fecha_sin_cooldown,
                )
            )
            db.commit()

            reenvio_respuesta = client.post(
                f"{RUTA_OPERADORES}/{usuario_operador.id}/reenviar-invitacion"
            )
            respuestas_http.append(reenvio_respuesta.text)
            _asegurar(
                reenvio_respuesta.status_code == 200,
                "El API no pudo reenviar la invitación OPERADOR "
                f"(HTTP {reenvio_respuesta.status_code}).",
            )
            _asegurar(
                reenvio_respuesta.json().get("estado") == "invitacion_enviada",
                "El API devolvió un estado inesperado al reenviar OPERADOR.",
            )
            ids_operador = _esperar_mensajes(correo_operador, 2)
            _asegurar(
                len(ids_operador) == 2,
                "Mailpit no recibió el reenvío OPERADOR.",
            )
            enlace_operador_2, token_operador_2, _texto_operador_2 = _leer_invitacion(
                ids_operador[0],
                settings,
            )
            tokens.append(token_operador_2)
            _asegurar(
                token_operador_1 != token_operador_2,
                "El reenvío OPERADOR no generó un token distinto.",
            )
            respuestas_http.extend(
                _activar_cuenta(client, token_operador_2, CONTRASENA_OPERADOR)
            )

        salida_total = "\n".join(salidas_cli + respuestas_http + [caplog.text])
        for token in tokens:
            _asegurar(
                token not in salida_total,
                "Un token capturado apareció en salida o logs.",
            )
        for enlace in (
            enlace_admin_1,
            enlace_admin_2,
            enlace_operador_1,
            enlace_operador_2,
        ):
            _asegurar(
                enlace not in salida_total,
                "Un enlace capturado apareció en salida o logs.",
            )
    finally:
        _limpiar_mensajes(correos)
