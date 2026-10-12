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
from app.api.rutas import (
    activaciones_operador,
    activaciones_propietario,
    autenticacion,
    gestion_propietario,
    operadores,
)
from app.cli import crear_admin
from app.cli.invitaciones_admin import crear_callback_entrega_admin
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models import (
    ActivacionCuenta,
    CuentaPropietario,
    DesvinculacionPropietario,
    RolUsuario,
    Usuario,
)
from app.seguridad.activaciones import hash_token_activacion
from app.seguridad.contrasenas import crear_hash_contrasena, verificar_contrasena
from app.servicios.administradores import reenviar_invitacion_administrador
from app.servicios.autenticacion import autenticar_admin
from app.servicios.gestion_propietario import emitir_sesion_gestion
from app.servicios.propietario import iniciar_inscripcion_propietario

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


def test_sp_owner_gestion_web_envia_y_activa_enlace_sintetico_con_mailpit(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Acepta el alta Web, la activacion OWNER y el aislamiento de sesion."""

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
    _solicitar_mailpit("/readyz")

    correo = f"sp-owner-web-{uuid4().hex}@example.com"
    apellido_materno = uuid4().hex[:8]
    contrasena_login = f"Acceso Dueño {uuid4().hex}"
    contrasena_admin = f"Admin Dueño {uuid4().hex}"
    correos = [correo]
    tokens: list[str] = []
    salida_http: list[str] = []

    def entregar_db() -> Any:
        yield db

    monkeypatch.setitem(modulo_main.app.dependency_overrides, get_db, entregar_db)
    monkeypatch.setattr(gestion_propietario, "get_settings", lambda: settings)
    monkeypatch.setattr(activaciones_propietario, "get_settings", lambda: settings)

    try:
        emision = emitir_sesion_gestion(db)
        if emision.ticket is None or emision.codigo_apareamiento is None:
            raise AssertionError("No se pudo emitir el enlace sintetico.")

        with TestClient(modulo_main.app) as client:
            reclamo = client.post(
                f"{gestion_propietario.RUTA_GESTION_PROPIETARIO}/claim",
                headers={
                    "origin": urlsplit(settings.app_public_url).scheme
                    + "://"
                    + urlsplit(settings.app_public_url).netloc
                },
                json={
                    "ticket": emision.ticket,
                    "codigo_apareamiento": emision.codigo_apareamiento,
                },
            )
            salida_http.append(reclamo.text)
            _asegurar(
                reclamo.status_code == 200 and reclamo.json().get("activa") is True,
                "El navegador sintetico no pudo reclamar su sesion.",
            )

            inicial = client.get(
                f"{gestion_propietario.RUTA_GESTION_PROPIETARIO}/estado"
            )
            _asegurar(
                inicial.status_code == 200
                and inicial.json().get("inscripciones") == [],
                "La lectura inicial no fue de solo lectura.",
            )

            alta = client.post(
                f"{gestion_propietario.RUTA_GESTION_PROPIETARIO}/inscripciones",
                headers={
                    "origin": urlsplit(settings.app_public_url).scheme
                    + "://"
                    + urlsplit(settings.app_public_url).netloc
                },
                json={"correo": correo},
            )
            salida_http.append(alta.text)
            _asegurar(
                alta.status_code == 204,
                "La accion Web no inició el correo sintetico.",
            )

            estados = client.get(
                f"{gestion_propietario.RUTA_GESTION_PROPIETARIO}/estado"
            )
            _asegurar(
                estados.status_code == 200
                and len(estados.json().get("inscripciones", [])) == 1
                and estados.json()["inscripciones"][0]["correo_inicial_enviado"]
                is True,
                "La inscripcion persistida no pudo recuperarse.",
            )

            ids = _esperar_mensajes(correo, 1)
            _asegurar(len(ids) == 1, "Mailpit no recibió el correo sintetico.")
            plano, html = _cuerpos_mensaje(ids[0])
            enlaces = re.findall(r"https?://[^\s<>\"']+", f"{plano}\n{html}")
            enlaces = [enlace.rstrip(".,;)]}") for enlace in enlaces]
            enlaces_owner = [
                enlace
                for enlace in enlaces
                if urlsplit(enlace).path == "/activar-propietario"
            ]
            _asegurar(
                len(set(enlaces_owner)) == 1,
                "El correo no contiene un enlace de activacion unico.",
            )
            consulta = parse_qs(urlsplit(enlaces_owner[0]).query)
            _asegurar(
                set(consulta) == {"token"} and len(consulta["token"]) == 1,
                "El enlace enviado no respeta el contrato de activacion OWNER.",
            )
            token = consulta["token"][0]
            tokens.append(token)
            _asegurar(
                emision.ticket not in f"{plano}\n{html}"
                and emision.codigo_apareamiento not in f"{plano}\n{html}",
                "El correo expuso credenciales de gestion Web.",
            )

            enlace = client.post(
                f"{activaciones_propietario.RUTA_ACTIVACION_PROPIETARIO}/enlace",
                json={"token": token},
            )
            salida_http.append(enlace.text)
            _asegurar(
                enlace.status_code == 204,
                "No se pudo canjear el enlace sintetico.",
            )
            desafio = client.get(
                f"{activaciones_propietario.RUTA_ACTIVACION_PROPIETARIO}/desafio"
            )
            _asegurar(
                desafio.status_code == 200
                and desafio.json().get("tipo_cuenta") == "nueva",
                "La activacion no identificó una cuenta nueva.",
            )
            completar = client.post(
                f"{activaciones_propietario.RUTA_ACTIVACION_PROPIETARIO}/completar",
                json={
                    "nombre": "Propietario",
                    "apellido_paterno": "Sintetico",
                    "apellido_materno": apellido_materno,
                    "contrasena_login": contrasena_login,
                    "confirmar_contrasena_login": contrasena_login,
                    "contrasena_admin": contrasena_admin,
                    "confirmar_contrasena_admin": contrasena_admin,
                },
            )
            salida_http.append(completar.text)
            _asegurar(
                completar.status_code == 200
                and completar.json().get("estado") == "owner_activado",
                "No se pudo activar la cuenta sintetica de dueño.",
            )

            login = client.post(
                "/api/autenticacion/login",
                json={"correo": correo, "contrasena": contrasena_login},
            )
            salida_http.append(login.text)
            _asegurar(
                login.status_code == 200 and login.json().get("rol") == "OWNER",
                "La cuenta sintetica no pudo iniciar sesión por el flujo ordinario.",
            )
            acceso_admin = client.get("/api/cajones")
            _asegurar(
                acceso_admin.status_code == 200,
                "OWNER no pudo usar el área /admin tras iniciar sesión.",
            )

            solo_gestion = TestClient(modulo_main.app)
            try:
                cookie_gestion = client.cookies.get(
                    gestion_propietario.NOMBRE_COOKIE_GESTION_PROPIETARIO
                )
                if cookie_gestion is None:
                    raise AssertionError("La sesión temporal no emitió su cookie.")
                solo_gestion.cookies.set(
                    gestion_propietario.NOMBRE_COOKIE_GESTION_PROPIETARIO,
                    cookie_gestion,
                )
                acceso_con_solo_gestion = solo_gestion.get("/api/cajones")
                _asegurar(
                    acceso_con_solo_gestion.status_code == 401,
                    "La cookie temporal autorizó una ruta /admin ordinaria.",
                )
            finally:
                solo_gestion.close()

        salida_total = "\n".join(salida_http)
        _asegurar(token not in salida_total, "El token apareció en respuestas HTTP.")
    finally:
        _limpiar_mensajes(correos)
        modulo_main.app.dependency_overrides.pop(get_db, None)


def test_sp_owner_retorno_roleless_envia_y_confirma_correo_con_mailpit(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifica por correo sintetico el retorno de un OWNER roleless."""

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
    _solicitar_mailpit("/readyz")

    correo = f"sp-owner-return-{uuid4().hex}@example.com"
    login_original = f"Acceso original {uuid4().hex}"
    admin_anterior = f"Administracion anterior {uuid4().hex}"
    admin_nueva = f"Administracion renovada {uuid4().hex}"
    nombre_previo = ("Sofia", "Ines", "Sintetica")
    nombre_corregido = ("Sofia", "Ines", "Retorno")
    hash_admin_anterior = crear_hash_contrasena(admin_anterior)
    ahora = datetime.now(UTC)

    usuario = Usuario(
        nombre="Sofia",
        apellido_paterno="Ines",
        apellido_materno="Sintetica",
        correo=correo,
        contrasena_hash=crear_hash_contrasena(login_original),
        rol=None,
        correo_verificado=True,
        debe_cambiar_contrasena=False,
        esta_activo=True,
    )
    db.add(usuario)
    db.flush()
    cuenta = CuentaPropietario(
        usuario_id=usuario.id,
        contrasena_admin_hash=hash_admin_anterior,
        rol_anterior=None,
    )
    db.add(cuenta)
    db.flush()
    db.add(
        DesvinculacionPropietario(
            usuario_id=usuario.id,
            cuenta_propietario_id=cuenta.id,
            token_hash=hash_token_activacion(uuid4().hex + uuid4().hex),
            emitida_en=ahora - timedelta(minutes=20),
            expira_en=ahora - timedelta(minutes=10),
            consumida_en=ahora - timedelta(minutes=5),
        )
    )
    cuenta.contrasena_admin_hash = None
    db.commit()
    usuario_id = usuario.id
    hash_login = usuario.contrasena_hash
    cuenta_id = cuenta.id

    correos = [correo]
    salida_http: list[str] = []

    def entregar(correo_destino: str, token: str) -> None:
        transporte = gestion_propietario._entregar_enlace(settings)
        transporte(correo_destino, token)

    def entregar_db() -> Any:
        yield db

    monkeypatch.setitem(modulo_main.app.dependency_overrides, get_db, entregar_db)
    monkeypatch.setattr(activaciones_propietario, "get_settings", lambda: settings)

    try:
        iniciar_inscripcion_propietario(
            db,
            correo=correo,
            entregar_enlace=entregar,
            modo="nueva",
        )
        ids = _esperar_mensajes(correo, 1)
        _asegurar(len(ids) == 1, "Mailpit no recibió el correo de retorno.")
        plano, html = _cuerpos_mensaje(ids[0])
        enlaces = re.findall(r"https?://[^\s<>\"']+", f"{plano}\n{html}")
        enlaces = [enlace.rstrip(".,;)]}") for enlace in enlaces]
        enlaces_owner = [
            enlace
            for enlace in enlaces
            if urlsplit(enlace).path == "/activar-propietario"
        ]
        _asegurar(
            len(set(enlaces_owner)) == 1,
            "El correo de retorno no contiene un enlace unico.",
        )
        consulta = parse_qs(urlsplit(enlaces_owner[0]).query)
        _asegurar(
            set(consulta) == {"token"} and len(consulta["token"]) == 1,
            "El enlace de retorno no respeta el contrato de activacion OWNER.",
        )
        token = consulta["token"][0]
        _asegurar(
            login_original not in f"{plano}\n{html}"
            and admin_anterior not in f"{plano}\n{html}",
            "El correo de retorno expuso credenciales.",
        )

        with TestClient(modulo_main.app) as client:
            canje = client.post(
                f"{activaciones_propietario.RUTA_ACTIVACION_PROPIETARIO}/enlace",
                json={"token": token},
            )
            salida_http.append(canje.text)
            _asegurar(
                canje.status_code == 204,
                "No se pudo canjear el correo de retorno.",
            )
            estado = client.get(
                f"{activaciones_propietario.RUTA_ACTIVACION_PROPIETARIO}/desafio"
            )
            salida_http.append(estado.text)
            _asegurar(
                estado.status_code == 200
                and estado.json().get("tipo_cuenta") == "retorno"
                and (
                    estado.json().get("nombre"),
                    estado.json().get("apellido_paterno"),
                    estado.json().get("apellido_materno"),
                ) == nombre_previo,
                "El desafio no reconoció el OWNER roleless ni su nombre.",
            )
            completar = client.post(
                f"{activaciones_propietario.RUTA_ACTIVACION_PROPIETARIO}/completar",
                json={
                    "nombre": nombre_corregido[0],
                    "apellido_paterno": nombre_corregido[1],
                    "apellido_materno": nombre_corregido[2],
                    "contrasena_admin": admin_nueva,
                    "confirmar_contrasena_admin": admin_nueva,
                },
            )
            salida_http.append(completar.text)
            _asegurar(
                completar.status_code == 200,
                "No se pudo confirmar el retorno del OWNER.",
            )
            acceso = client.post(
                "/api/autenticacion/login",
                json={"correo": correo, "contrasena": login_original},
            )
            salida_http.append(acceso.text)
            _asegurar(
                acceso.status_code == 200
                and acceso.json().get("rol") == RolUsuario.OWNER.value,
                "La contraseña de acceso original dejó de funcionar.",
            )
            _asegurar(
                client.post(
                    "/api/autenticacion/login",
                    json={"correo": correo, "contrasena": admin_anterior},
                ).status_code
                == 401,
                "La contraseña administrativa anterior inició sesión.",
            )

        salida_total = "\n".join(salida_http)
        _asegurar(token not in salida_total, "El token apareció en respuestas HTTP.")
        db.refresh(usuario)
        db.refresh(cuenta)
        _asegurar(
            usuario.id == usuario_id
            and usuario.correo == correo
            and usuario.contrasena_hash == hash_login
            and cuenta.id == cuenta_id
            and cuenta.rol_anterior is None
            and cuenta.contrasena_admin_hash is not None
            and cuenta.contrasena_admin_hash != hash_admin_anterior
            and autenticar_admin(db, correo=correo, contrasena=login_original),
            "La cuenta de retorno no preservó su identidad y credenciales esperadas.",
        )
        hash_admin_final = cuenta.contrasena_admin_hash
        assert hash_admin_final is not None
        _asegurar(
            verificar_contrasena(admin_nueva, hash_admin_final)
            and not verificar_contrasena(admin_anterior, hash_admin_final),
            "La contraseña administrativa nueva no reemplazó la anterior.",
        )
        _asegurar(
            " ".join(
                parte
                for parte in (
                    usuario.nombre,
                    usuario.apellido_paterno,
                    usuario.apellido_materno,
                )
                if parte
            )
            == " ".join(nombre_corregido),
            "El nombre corregido no se guardó.",
        )
    finally:
        _limpiar_mensajes(correos)
        modulo_main.app.dependency_overrides.pop(get_db, None)


def test_sp_owner_desvinculacion_envia_confirmacion_de_un_solo_uso_con_mailpit(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Entrega el correo sintético y confirma desde un cliente sin cookie."""

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
    _solicitar_mailpit("/readyz")

    correo = f"sp-owner-unlink-{uuid4().hex}@example.test"
    contrasena_login = f"Owner login {uuid4().hex}"
    contrasena_admin = f"Owner admin {uuid4().hex}"
    usuario = Usuario(
        nombre="Prueba",
        apellido_paterno="Owner",
        correo=correo,
        contrasena_hash=crear_hash_contrasena(contrasena_login),
        rol=RolUsuario.OWNER.value,
        correo_verificado=True,
        debe_cambiar_contrasena=False,
        esta_activo=True,
    )
    db.add(usuario)
    db.flush()
    db.add(
        CuentaPropietario(
            usuario_id=usuario.id,
            contrasena_admin_hash=crear_hash_contrasena(contrasena_admin),
            rol_anterior=None,
        )
    )
    db.commit()

    correos = [correo]
    enlaces: list[str] = []
    respuestas: list[str] = []

    def entregar_db() -> Any:
        yield db

    monkeypatch.setitem(modulo_main.app.dependency_overrides, get_db, entregar_db)
    monkeypatch.setattr(gestion_propietario, "get_settings", lambda: settings)

    try:
        emision = emitir_sesion_gestion(db)
        if emision.ticket is None or emision.codigo_apareamiento is None:
            raise AssertionError("No se pudo preparar la sesión de gestión sintética.")
        origen = urlsplit(settings.app_public_url).scheme + "://" + urlsplit(
            settings.app_public_url
        ).netloc

        with TestClient(modulo_main.app) as client:
            reclamo = client.post(
                f"{gestion_propietario.RUTA_GESTION_PROPIETARIO}/claim",
                headers={"origin": origen},
                json={
                    "ticket": emision.ticket,
                    "codigo_apareamiento": emision.codigo_apareamiento,
                },
            )
            _asegurar(
                reclamo.status_code == 200,
                "No se autorizó la sesión temporal sintética.",
            )

            envio = client.post(
                f"{gestion_propietario.RUTA_GESTION_PROPIETARIO}/desvinculacion",
                headers={"origin": origen},
                json={"contrasena_admin": contrasena_admin},
            )
            respuestas.append(envio.text)
            _asegurar(
                envio.status_code == 202,
                "La solicitud sintética no envió el correo de desvinculación.",
            )

            ids = _esperar_mensajes(correo, 1)
            _asegurar(len(ids) == 1, "Mailpit no recibió el correo de desvinculación.")
            plano, html = _cuerpos_mensaje(ids[0])
            candidatos = re.findall(r"https?://[^\s<>\"']+", f"{plano}\n{html}")
            candidatos = [enlace.rstrip(".,;)]}") for enlace in candidatos]
            enlaces_confirmacion = [
                enlace
                for enlace in candidatos
                if urlsplit(enlace).path == "/confirmar-desvinculacion"
            ]
            _asegurar(
                len(set(enlaces_confirmacion)) == 1,
                "El mensaje no contiene un enlace público único.",
            )
            enlace = urlsplit(enlaces_confirmacion[0])
            _asegurar(
                enlace.query == ""
                and enlace.fragment.startswith("desvincular="),
                "El enlace expuso el token fuera del fragmento.",
            )
            token = enlace.fragment.removeprefix("desvincular=")
            enlaces.append(token)

            otro_navegador = TestClient(modulo_main.app)
            try:
                confirmacion = otro_navegador.post(
                    f"{gestion_propietario.RUTA_GESTION_PROPIETARIO}"
                    "/desvinculacion/confirmar",
                    headers={"origin": origen},
                    json={"token": token},
                )
                respuestas.append(confirmacion.text)
                _asegurar(
                    confirmacion.status_code == 200
                    and confirmacion.json().get("estado") == "dueno_desvinculado",
                    "El enlace no confirmó sin cookie ni perfil de navegador previo.",
                )
            finally:
                otro_navegador.close()

        db.expire_all()
        usuario_final = db.get(Usuario, usuario.id)
        cuenta_final = db.scalar(
            select(CuentaPropietario).where(
                CuentaPropietario.usuario_id == usuario.id
            )
        )
        _asegurar(
            usuario_final is not None
            and usuario_final.rol is None
            and usuario_final.esta_activo is True
            and usuario_final.contrasena_hash is not None,
            "La cuenta sintética no conservó su identidad sin rol.",
        )
        _asegurar(
            cuenta_final is not None
            and cuenta_final.contrasena_admin_hash is None,
            "La credencial administrativa no se invalidó.",
        )
        salida = "\n".join(respuestas)
        _asegurar(token not in salida, "El token apareció en una respuesta HTTP.")
    finally:
        _limpiar_mensajes(correos)
        modulo_main.app.dependency_overrides.pop(get_db, None)
