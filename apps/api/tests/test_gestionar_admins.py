"""Pruebas del servicio y la CLI de gestion de ADMIN existentes."""

from __future__ import annotations

import re
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from io import StringIO
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from solicitud_cliente import solicitar_con_cookies
from sqlalchemy import create_engine, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from app.api.rutas.autenticacion import RUTA_ME
from app.cli import gestionar_admins as cli
from app.cli import presentacion
from app.core.config import Settings
from app.core.database import get_db
from app.correo.smtp import ErrorEnvioCorreo
from app.models import ActivacionCuenta, RolUsuario, Sesion, Usuario
from app.seguridad.activaciones import hash_token_activacion
from app.seguridad.correos import CorreoInvalidoError
from app.seguridad.sesiones import hash_token_sesion
from app.servicios.activaciones import crear_activacion, reenviar_activacion
from app.servicios.activaciones_operador import (
    ActivacionOperadorNoDisponible,
    canjear_enlace_operador,
)
from app.servicios.administradores import (
    AdministradorNoEncontradoError,
    buscar_administrador_por_correo,
    buscar_administrador_por_id,
    desactivar_administrador,
    listar_administradores,
    reactivar_administrador,
    reenviar_invitacion_administrador,
)
from app.servicios.autenticacion import (
    crear_sesion_admin,
    obtener_usuario_admin_por_token,
)
from app.servicios.usuarios import crear_admin, crear_admin_pendiente
from main import app

CONTRASENA_PRUEBA = "Contrasena gestion admins 123"


class SalidaTerminal(StringIO):
    def isatty(self) -> bool:
        return True


def correo_de_prueba() -> str:
    return f"gestionar-admins-{uuid4().hex}@example.com"


def settings_de_prueba(
    *,
    cooldown_segundos: int = 60,
) -> Settings:
    return Settings(
        database_host="localhost",
        database_port=5432,
        database_name="unused",
        database_user="unused",
        database_password=SecretStr("test-db-password"),
        activation_token_ttl_hours=24,
        activation_challenge_ttl_minutes=15,
        smtp_from_email="no-reply@example.com",
        app_public_url="https://parking.example",
        correo_transporte="smtp",
        activacion_reenvio_cooldown_segundos=cooldown_segundos,
    )


def crear_usuario_manual(db: Session, correo: str | None = None) -> Usuario:
    resultado = crear_admin(
        db,
        nombre="Ada",
        apellido_paterno="Lovelace",
        apellido_materno="Byron",
        correo=correo or correo_de_prueba(),
        contrasena=CONTRASENA_PRUEBA,
        confirmacion_contrasena=CONTRASENA_PRUEBA,
    )
    return resultado.usuario


def crear_usuario_temporal(db: Session) -> Usuario:
    resultado = crear_admin(
        db,
        nombre="Grace",
        apellido_paterno="Hopper",
        apellido_materno="Murray",
        correo=correo_de_prueba(),
        usar_contrasena_temporal=True,
    )
    return resultado.usuario


def crear_usuario_pendiente(db: Session, *, ahora: datetime) -> tuple[Usuario, str]:
    tokens: list[str] = []
    resultado = crear_admin_pendiente(
        db,
        nombre="Ada",
        apellido_paterno="Lovelace",
        apellido_materno="Byron",
        correo=correo_de_prueba(),
        entregar_invitacion=lambda _usuario, token: tokens.append(token),
        duracion_token_horas=24,
        ahora=ahora,
    )
    assert len(tokens) == 1
    return resultado.usuario, tokens[0]


def crear_activacion_controlada(
    db: Session,
    usuario: Usuario,
    *,
    ahora: datetime,
) -> ActivacionCuenta:
    resultado = crear_activacion(db, usuario.id, ahora=ahora)
    resultado.activacion.creado_en = ahora
    db.commit()
    db.rollback()
    return resultado.activacion


def activar_usuario(db: Session, usuario: Usuario) -> None:
    usuario.correo_verificado = True
    usuario.debe_cambiar_contrasena = False
    usuario.esta_activo = True
    db.commit()
    db.rollback()


def crear_sesion_vigente(
    db: Session,
    usuario: Usuario,
    *,
    ahora: datetime,
):
    resultado = crear_sesion_admin(
        db,
        correo=usuario.correo,
        contrasena=CONTRASENA_PRUEBA,
        correo_normalizado=usuario.correo,
        duracion_minutos=480,
        ahora=ahora,
    )
    assert resultado is not None
    db.rollback()
    return resultado


@pytest.fixture
def client(database_url: URL) -> Generator[TestClient]:
    engine = create_engine(database_url, pool_pre_ping=True)
    fabrica_sesiones = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )

    def override_get_db() -> Generator[Session]:
        db = fabrica_sesiones()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def ejecutar_cli(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    respuestas: list[str],
    *,
    transporte=None,
    settings: Settings | None = None,
    limpiezas: list[None] | None = None,
) -> int:
    entradas = iter(respuestas)
    monkeypatch.setattr("builtins.input", lambda _prompt: next(entradas))

    def registrar_limpieza() -> None:
        if limpiezas is not None:
            limpiezas.append(None)

    monkeypatch.setattr(cli, "limpiar_pantalla", registrar_limpieza)
    return cli.main(
        db=db,
        transporte=transporte,
        settings=settings or settings_de_prueba(),
    )


def test_colores_solo_se_emiten_en_tty_y_respetan_no_color(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminal = SalidaTerminal()
    monkeypatch.setattr(cli.sys, "stdout", terminal)
    monkeypatch.delenv("NO_COLOR", raising=False)

    assert (
        cli._estilizar("Activo", cli.ANSI_VERDE)
        == f"{cli.ANSI_VERDE}Activo{cli.ANSI_REINICIO}"
    )

    monkeypatch.setenv("NO_COLOR", "")
    assert cli._estilizar("Activo", cli.ANSI_VERDE) == "Activo"

    monkeypatch.delenv("NO_COLOR")
    monkeypatch.setattr(cli.sys, "stdout", StringIO())
    assert cli._estilizar("Activo", cli.ANSI_VERDE) == "Activo"


def test_menu_principal_solo_muestra_lista_y_salida(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminal = StringIO()
    monkeypatch.setattr(cli.sys, "stdout", terminal)

    cli._mostrar_menu()

    salida = terminal.getvalue()
    assert "SMART PARKING — GESTIÓN DE ADMINISTRADORES" in salida
    assert "1. Ver administradores" in salida
    assert "0. Salir" in salida
    assert "Buscar ADMIN" not in salida


def test_lista_colorea_estados_y_alinea_columnas_sin_colorear_datos(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ahora = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)
    activo_verificado = crear_usuario_manual(db)
    activar_usuario(db, activo_verificado)
    activo_pendiente = crear_usuario_manual(db)
    crear_activacion_controlada(db, activo_pendiente, ahora=ahora)
    inactivo_verificado = crear_usuario_manual(db)
    activar_usuario(db, inactivo_verificado)
    inactivo_verificado.esta_activo = False
    db.commit()
    inactivo_pendiente = crear_usuario_manual(db)
    crear_activacion_controlada(db, inactivo_pendiente, ahora=ahora)
    inactivo_pendiente.esta_activo = False
    db.commit()
    db.rollback()

    administradores = listar_administradores(db, ahora=ahora)
    terminal = SalidaTerminal()
    monkeypatch.setattr(cli.sys, "stdout", terminal)
    monkeypatch.delenv("NO_COLOR", raising=False)
    cli._mostrar_lista(administradores)

    salida = terminal.getvalue()
    salida_plana = re.sub(r"\x1b\[[0-9;]*m", "", salida)
    filas = [
        linea
        for linea in salida_plana.splitlines()
        if linea and linea[0].isdigit() and "|" in linea
    ]
    posiciones = [
        tuple(indice for indice, caracter in enumerate(fila) if caracter == "|")
        for fila in filas
    ]

    assert len(filas) == 4
    assert len(set(posiciones)) == 1
    assert f"{cli.ANSI_VERDE}Acceso habilitado" in salida
    assert f"{cli.ANSI_AMARILLO}Pendiente de activación" in salida
    assert f"{cli.ANSI_ROJO}Inactivo" in salida
    assert f"{cli.ANSI_VERDE}Verificado" in salida
    assert f"{cli.ANSI_AMARILLO}No verificado" in salida
    for administrador in administradores:
        nombre = cli._nombre_completo(administrador)
        assert nombre in salida
        assert administrador.correo in salida
        assert not any(
            f"{codigo}{nombre}" in salida or f"{codigo}{administrador.correo}" in salida
            for codigo in (
                cli.ANSI_CIAN,
                cli.ANSI_CIAN_BRILLANTE,
                cli.ANSI_VERDE,
                cli.ANSI_AMARILLO,
                cli.ANSI_ROJO,
                cli.ANSI_DIM,
            )
        )

    salida_no_tty = StringIO()
    monkeypatch.setattr(cli.sys, "stdout", salida_no_tty)
    cli._mostrar_lista(administradores)
    assert "\x1b[" not in salida_no_tty.getvalue()


def test_limpiar_pantalla_no_ejecuta_comando_en_salida_no_tty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    salida = StringIO()
    comando = MagicMock()
    monkeypatch.setattr(cli.sys, "stdout", salida)
    monkeypatch.setattr(presentacion.os, "system", comando)

    presentacion.limpiar_pantalla()

    comando.assert_not_called()
    assert salida.getvalue() == ""


def test_detalle_colorea_valores_semanticos_y_deja_datos_neutrales(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ahora = datetime(2026, 9, 29, 11, 0, tzinfo=UTC)
    usuario = crear_usuario_manual(db)
    crear_activacion_controlada(db, usuario, ahora=ahora)
    administrador = buscar_administrador_por_id(db, usuario.id, ahora=ahora)
    assert administrador is not None

    terminal = SalidaTerminal()
    monkeypatch.setattr(cli.sys, "stdout", terminal)
    monkeypatch.delenv("NO_COLOR", raising=False)
    cli._mostrar_detalle(administrador)

    salida = terminal.getvalue()
    assert f"{cli.ANSI_AMARILLO}Pendiente de activación" in salida
    assert f"{cli.ANSI_VERDE}No verificado" not in salida
    assert f"{cli.ANSI_AMARILLO}No verificado" in salida
    assert f"{cli.ANSI_AMARILLO}Pendiente" in salida
    assert usuario.correo in salida
    assert f"{cli.ANSI_VERDE}{usuario.correo}" not in salida
    assert f"{cli.ANSI_AMARILLO}{usuario.correo}" not in salida


def test_detalle_reutiliza_renderer_y_muestra_una_fila_con_perfil_base(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    usuario = crear_usuario_manual(db)
    administrador = buscar_administrador_por_id(db, usuario.id)
    assert administrador is not None
    renderer = MagicMock(wraps=cli._mostrar_tabla_administradores)
    monkeypatch.setattr(cli, "_mostrar_tabla_administradores", renderer)

    cli._mostrar_lista([administrador])
    cli._mostrar_detalle(administrador)

    assert renderer.call_args_list[0].args == ([administrador],)
    assert renderer.call_args_list[0].kwargs == {
        "titulo": "SMART PARKING — ADMIN registrados"
    }
    assert renderer.call_args_list[1].args == ([administrador],)
    assert renderer.call_args_list[1].kwargs == {
        "titulo": "SMART PARKING — ADMIN seleccionado"
    }

    filas = [
        cli._fila_administrador(administrador),
    ]
    anchos = cli._anchos_tabla_administradores(filas)
    assert all(
        anchos[clave] >= cli.ANCHOS_BASE_TABLA_ADMIN[clave]
        for clave in cli.COLUMNAS_TABLA_ADMIN
    )


def test_cli_id_invalido_y_no_numerico_regresan_a_la_lista(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    usuario = crear_usuario_manual(db)

    assert (
        ejecutar_cli(
            db,
            monkeypatch,
            ["1", "texto", "999999", "", "0", "0"],
        )
        == 0
    )

    salida = capsys.readouterr()
    assert "Ingresa un ID numerico positivo." in salida.err
    assert "No se encontro el ADMIN solicitado." in salida.err
    assert usuario.correo in salida.out


@pytest.mark.parametrize(
    ("esta_activo", "correo_verificado", "opciones", "etiquetas"),
    [
        (True, True, {"1", "0"}, {"1. Desactivar administrador"}),
        (
            True,
            False,
            {"1", "2", "0"},
            {"1. Reenviar invitación", "2. Desactivar administrador"},
        ),
        (False, True, {"1", "0"}, {"1. Reactivar administrador"}),
        (False, False, {"1", "0"}, {"1. Reactivar administrador"}),
    ],
)
def test_cli_matriz_de_acciones_contextuales(
    esta_activo: bool,
    correo_verificado: bool,
    opciones: set[str],
    etiquetas: set[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    administrador = MagicMock(
        esta_activo=esta_activo,
        correo_verificado=correo_verificado,
        debe_cambiar_contrasena=False,
    )
    terminal = StringIO()
    monkeypatch.setattr(cli.sys, "stdout", terminal)

    cli._mostrar_acciones(administrador)

    assert cli._opciones_detalle(administrador) == opciones
    salida = terminal.getvalue()
    assert etiquetas <= set(salida.splitlines())


def test_listado_usa_solo_admin_orden_ascendente_y_estado_derivado(
    db: Session,
) -> None:
    ahora = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)
    manual = crear_usuario_manual(db)
    temporal = crear_usuario_temporal(db)
    crear_activacion_controlada(db, temporal, ahora=ahora)
    verificado = crear_usuario_manual(db)
    activar_usuario(db, verificado)
    inactivo_pendiente = crear_usuario_manual(db)
    crear_activacion_controlada(db, inactivo_pendiente, ahora=ahora)
    inactivo_pendiente.esta_activo = False
    db.commit()
    operador = crear_usuario_manual(db)
    operador.rol = RolUsuario.OPERADOR.value
    db.commit()
    operador_id = operador.id
    operador_correo = operador.correo
    db.rollback()

    administradores = listar_administradores(db, ahora=ahora)

    assert [admin.id for admin in administradores] == sorted(
        admin.id for admin in administradores
    )
    assert all(admin.id != operador_id for admin in administradores)
    assert buscar_administrador_por_id(db, operador_id, ahora=ahora) is None
    assert buscar_administrador_por_correo(db, operador_correo, ahora=ahora) is None
    db.rollback()
    with pytest.raises(AdministradorNoEncontradoError):
        desactivar_administrador(db, operador_id, ahora=ahora)
    db.rollback()
    operador_persistido = db.get(Usuario, operador_id)
    assert operador_persistido is not None
    assert operador_persistido.esta_activo
    por_correo = {admin.correo: admin for admin in administradores}
    assert por_correo[manual.correo].estado_activacion == "Sin activación vigente"
    assert por_correo[manual.correo].modo_activacion == "Manual"
    assert por_correo[temporal.correo].estado_activacion == "Pendiente"
    assert por_correo[temporal.correo].modo_activacion == "Temporal"
    assert por_correo[verificado.correo].estado_activacion == "No requerida"
    assert por_correo[verificado.correo].modo_activacion is None
    assert (
        por_correo[inactivo_pendiente.correo].estado_activacion
        == "Pendiente; cuenta inactiva"
    )


def test_estado_no_muestra_activacion_expirada_y_busqueda_es_exacta(
    db: Session,
) -> None:
    ahora = datetime(2026, 9, 28, 11, 0, tzinfo=UTC)
    usuario = crear_usuario_manual(db)
    activacion = crear_activacion_controlada(db, usuario, ahora=ahora)
    activacion.expira_en = ahora - timedelta(seconds=1)
    db.commit()
    db.rollback()

    por_id = buscar_administrador_por_id(db, usuario.id, ahora=ahora)
    por_correo = buscar_administrador_por_correo(
        db,
        f"  {usuario.correo.upper()}  ",
        ahora=ahora,
    )
    with pytest.raises(CorreoInvalidoError):
        buscar_administrador_por_correo(db, "Ada Lovelace")

    assert por_id is not None
    assert por_id.estado_activacion == "Sin activación vigente"
    assert por_correo is not None
    assert por_correo.id == usuario.id


def test_desactivar_revoca_sesiones_vigentes_y_rechaza_nuevo_login(
    db: Session,
) -> None:
    ahora = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    usuario = crear_usuario_manual(db)
    activar_usuario(db, usuario)
    primera = crear_sesion_vigente(db, usuario, ahora=ahora)
    segunda = crear_sesion_vigente(db, usuario, ahora=ahora)
    sesion_expirada = Sesion(
        usuario_id=usuario.id,
        token_hash=hash_token_sesion("token-expirado-gestionar"),
        expira_en=ahora - timedelta(seconds=1),
        revocado_en=None,
        creado_en=ahora - timedelta(hours=1),
    )
    db.add(sesion_expirada)
    db.commit()
    db.rollback()

    desactivar_administrador(db, usuario.id, ahora=ahora)
    db.rollback()

    usuario_persistido = db.get(Usuario, usuario.id)
    sesiones = db.scalars(select(Sesion).where(Sesion.usuario_id == usuario.id)).all()
    assert usuario_persistido is not None
    assert usuario_persistido.esta_activo is False
    sesiones_por_id = {sesion.id: sesion for sesion in sesiones}
    assert sesiones_por_id[primera.sesion.id].revocado_en == ahora
    assert sesiones_por_id[segunda.sesion.id].revocado_en == ahora
    assert sesiones_por_id[sesion_expirada.id].revocado_en is None
    assert (
        crear_sesion_admin(
            db,
            correo=usuario.correo,
            contrasena=CONTRASENA_PRUEBA,
            correo_normalizado=usuario.correo,
            duracion_minutos=480,
            ahora=ahora,
        )
        is None
    )
    assert obtener_usuario_admin_por_token(db, token=primera.token, ahora=ahora) is None


def test_fallo_al_revocar_revierte_tambien_la_desactivacion(db: Session) -> None:
    ahora = datetime(2026, 9, 28, 13, 0, tzinfo=UTC)
    usuario = crear_usuario_manual(db)
    activar_usuario(db, usuario)
    crear_sesion_vigente(db, usuario, ahora=ahora)

    administrador_id = usuario.id
    db.rollback()
    with (
        patch(
            "app.servicios.administradores.revocar_sesiones_vigentes",
            side_effect=RuntimeError("fallo de prueba"),
        ),
        pytest.raises(RuntimeError),
    ):
        desactivar_administrador(db, administrador_id, ahora=ahora)

    db.rollback()
    usuario_persistido = db.get(Usuario, usuario.id)
    sesion = db.scalar(select(Sesion).where(Sesion.usuario_id == usuario.id))
    assert usuario_persistido is not None
    assert usuario_persistido.esta_activo is True
    assert sesion is not None
    assert sesion.revocado_en is None


def test_reactivar_no_modifica_verificacion_password_activaciones_ni_sesiones(
    db: Session,
) -> None:
    ahora = datetime(2026, 9, 28, 14, 0, tzinfo=UTC)
    usuario = crear_usuario_manual(db)
    activacion = crear_activacion_controlada(db, usuario, ahora=ahora)
    usuario.correo_verificado = True
    usuario.esta_activo = True
    db.commit()
    db.rollback()
    hash_original = usuario.contrasena_hash
    crear_sesion_vigente(db, usuario, ahora=ahora)

    administrador_id = usuario.id
    db.rollback()
    desactivar_administrador(db, administrador_id, ahora=ahora)
    db.rollback()
    reactivar_administrador(
        db,
        administrador_id,
        ahora=ahora + timedelta(seconds=1),
    )
    db.rollback()

    usuario_persistido = db.get(Usuario, usuario.id)
    activacion_persistida = db.get(ActivacionCuenta, activacion.id)
    sesion = db.scalar(select(Sesion).where(Sesion.usuario_id == usuario.id))
    assert usuario_persistido is not None
    assert activacion_persistida is not None
    assert sesion is not None
    assert usuario_persistido.esta_activo is True
    assert usuario_persistido.correo_verificado is True
    assert usuario_persistido.contrasena_hash == hash_original
    assert activacion_persistida.consumido_en == ahora
    assert sesion.revocado_en == ahora


def test_desactivar_admin_pendiente_consumo_el_enlace_y_reactivar_no_lo_restaura(
    db: Session,
) -> None:
    ahora = datetime.now(UTC)
    usuario, token = crear_usuario_pendiente(db, ahora=ahora)
    usuario_id = usuario.id
    activacion = db.scalar(
        select(ActivacionCuenta).where(ActivacionCuenta.usuario_id == usuario_id)
    )
    assert activacion is not None
    activacion.desafio_hash = hash_token_activacion("desafio pendiente")
    activacion.desafio_expira_en = ahora + timedelta(minutes=15)
    db.commit()
    db.rollback()

    desactivar_administrador(db, usuario_id, ahora=ahora + timedelta(seconds=1))
    db.rollback()
    activacion = db.get(ActivacionCuenta, activacion.id)
    assert activacion is not None
    assert activacion.consumido_en == ahora + timedelta(seconds=1)
    assert activacion.desafio_hash is None
    assert activacion.desafio_expira_en is None
    db.rollback()
    with pytest.raises(ActivacionOperadorNoDisponible):
        canjear_enlace_operador(
            db,
            token=token,
            duracion_desafio_minutos=15,
        )

    db.rollback()
    reactivar_administrador(db, usuario_id, ahora=ahora + timedelta(seconds=2))
    db.rollback()
    activacion = db.get(ActivacionCuenta, activacion.id)
    assert activacion is not None
    assert activacion.consumido_en == ahora + timedelta(seconds=1)
    db.rollback()
    with pytest.raises(ActivacionOperadorNoDisponible):
        canjear_enlace_operador(
            db,
            token=token,
            duracion_desafio_minutos=15,
        )


def test_reenvio_admin_legacy_aceptado_reemplaza_codigo_por_enlace_token_only(
    db: Session,
) -> None:
    ahora = datetime.now(UTC)
    usuario = crear_usuario_manual(db)
    resultado_legacy = crear_activacion(
        db,
        usuario.id,
        ahora=ahora - timedelta(seconds=120),
    )
    legacy = resultado_legacy.activacion
    legacy.creado_en = ahora - timedelta(seconds=120)
    db.commit()
    db.rollback()
    tokens_nuevos: list[str] = []

    reenviar_invitacion_administrador(
        db,
        usuario.id,
        cooldown_segundos=60,
        duracion_token_horas=24,
        entregar_invitacion=lambda _usuario, token: tokens_nuevos.append(token),
        ahora=ahora,
    )
    assert len(tokens_nuevos) == 1

    db.rollback()
    activaciones = db.scalars(
        select(ActivacionCuenta)
        .where(ActivacionCuenta.usuario_id == usuario.id)
        .order_by(ActivacionCuenta.id)
    ).all()
    assert len(activaciones) == 2
    anterior, actual = activaciones
    assert anterior.id == legacy.id
    assert anterior.consumido_en == ahora
    assert anterior.desafio_hash is None
    assert anterior.desafio_expira_en is None
    assert actual.codigo_hash is None
    assert actual.token_hash == hash_token_activacion(tokens_nuevos[0])
    assert actual.expira_en == ahora + timedelta(hours=24)
    db.rollback()
    with pytest.raises(ActivacionOperadorNoDisponible):
        canjear_enlace_operador(
            db,
            token=resultado_legacy.token,
            duracion_desafio_minutos=15,
        )
    db.rollback()
    resultado = canjear_enlace_operador(
        db,
        token=tokens_nuevos[0],
        duracion_desafio_minutos=15,
    )
    assert resultado.token


def test_fallo_entrega_admin_conserva_invitacion_legacy_vigente(db: Session) -> None:
    ahora = datetime.now(UTC)
    usuario = crear_usuario_manual(db)
    resultado_legacy = crear_activacion(
        db,
        usuario.id,
        ahora=ahora - timedelta(seconds=120),
    )
    legacy = resultado_legacy.activacion
    legacy.creado_en = ahora - timedelta(seconds=120)
    db.commit()
    db.rollback()

    def fallar_entrega(_usuario: Usuario, _token: str) -> None:
        raise ErrorEnvioCorreo

    with pytest.raises(ErrorEnvioCorreo):
        reenviar_invitacion_administrador(
            db,
            usuario.id,
            cooldown_segundos=60,
            duracion_token_horas=24,
            entregar_invitacion=fallar_entrega,
            ahora=ahora,
        )

    db.rollback()
    activaciones = db.scalars(
        select(ActivacionCuenta).where(ActivacionCuenta.usuario_id == usuario.id)
    ).all()
    assert len(activaciones) == 1
    assert activaciones[0].id == legacy.id
    assert activaciones[0].token_hash == legacy.token_hash
    assert activaciones[0].codigo_hash is not None
    assert activaciones[0].consumido_en is None


def test_mutacion_de_admin_no_existente_es_segura(db: Session) -> None:
    with pytest.raises(AdministradorNoEncontradoError):
        desactivar_administrador(db, 999_999)


def test_cli_navega_por_lista_confirmacion_vacia_es_no_y_opcion_dos_es_invalida(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    usuario = crear_usuario_manual(db)
    activar_usuario(db, usuario)

    assert ejecutar_cli(db, monkeypatch, ["1", "0", "0"]) == 0
    assert (
        ejecutar_cli(
            db,
            monkeypatch,
            ["1", str(usuario.id), "1", "", "0", "0", "0"],
        )
        == 0
    )
    assert ejecutar_cli(db, monkeypatch, ["2", "0"]) == 0

    salida = capsys.readouterr()
    assert "ADMIN registrados" in salida.out
    assert "ADMIN desactivado correctamente." not in salida.out
    assert "SMART PARKING — GESTIÓN DE ADMINISTRADORES" in salida.out
    assert "1. Ver administradores" in salida.out
    assert "Buscar ADMIN" not in salida.out
    assert "Opcion no valida." in salida.err
    db.rollback()
    usuario_persistido = db.get(Usuario, usuario.id)
    assert usuario_persistido is not None
    assert usuario_persistido.esta_activo is True


def test_cli_limpia_antes_de_cada_vista_de_lista_y_detalle(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    usuario = crear_usuario_manual(db)
    activar_usuario(db, usuario)
    limpiezas: list[None] = []
    listas: list[int] = []
    detalles: list[int] = []

    monkeypatch.setattr(
        cli, "_mostrar_lista", lambda admins: listas.append(len(admins))
    )
    monkeypatch.setattr(
        cli,
        "_mostrar_detalle",
        lambda administrador: detalles.append(administrador.id),
    )

    assert (
        ejecutar_cli(
            db,
            monkeypatch,
            ["1", str(usuario.id), "0", "0", "0"],
            limpiezas=limpiezas,
        )
        == 0
    )

    assert len(listas) == 2
    assert detalles == [usuario.id]
    assert len(limpiezas) == 5


def test_cli_detalle_regresa_a_lista_y_luego_al_menu(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    usuario = crear_usuario_manual(db)
    menus_principales: list[None] = []
    detalles: list[int] = []
    limpiezas: list[None] = []

    monkeypatch.setattr(cli, "_mostrar_menu", lambda: menus_principales.append(None))
    monkeypatch.setattr(
        cli,
        "_mostrar_detalle",
        lambda administrador: detalles.append(administrador.id),
    )

    assert (
        ejecutar_cli(
            db,
            monkeypatch,
            ["1", str(usuario.id), "0", "0", "0"],
            limpiezas=limpiezas,
        )
        == 0
    )

    assert menus_principales == [None, None]
    assert detalles == [usuario.id]
    assert len(limpiezas) == 5


def test_cli_desactiva_y_refresca_el_detalle(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    usuario = crear_usuario_manual(db)
    activar_usuario(db, usuario)
    mostrar_detalle = MagicMock(wraps=cli._mostrar_detalle)
    monkeypatch.setattr(cli, "_mostrar_detalle", mostrar_detalle)

    assert (
        ejecutar_cli(
            db,
            monkeypatch,
            ["1", str(usuario.id), "1", "s", "", "0", "0", "0"],
        )
        == 0
    )

    salida = capsys.readouterr().out
    assert "ADMIN desactivado correctamente." in salida
    assert "Inactivo" in salida
    assert "1. Reactivar administrador" in salida
    assert "SMART PARKING — ADMIN seleccionado" in salida
    assert mostrar_detalle.call_count == 2
    db.rollback()
    usuario_persistido = db.get(Usuario, usuario.id)
    assert usuario_persistido is not None
    assert usuario_persistido.esta_activo is False


def test_cli_reactiva_inactivo_y_luego_ofrece_reenvio(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    usuario = crear_usuario_manual(db)
    usuario.esta_activo = False
    db.commit()
    db.rollback()
    transporte = MagicMock()

    assert (
        ejecutar_cli(
            db,
            monkeypatch,
            [
                "1",
                str(usuario.id),
                "1",
                "s",
                "",
                "1",
                "",
                "0",
                "0",
                "0",
            ],
            transporte=transporte,
        )
        == 0
    )

    transporte.enviar.assert_called_once()
    mensaje = transporte.enviar.call_args.args[0]
    assert "/activar-cuenta?token=" in str(
        mensaje.get_body(preferencelist=("plain",)).get_content()
    )
    db.rollback()
    usuario_persistido = db.get(Usuario, usuario.id)
    assert usuario_persistido is not None
    assert usuario_persistido.esta_activo is True


def test_cli_reenvio_smtp_no_imprime_el_enlace(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    usuario = crear_usuario_manual(db)
    mostrar_detalle = MagicMock(wraps=cli._mostrar_detalle)
    transporte = MagicMock()
    monkeypatch.setattr(cli, "_mostrar_detalle", mostrar_detalle)

    assert (
        ejecutar_cli(
            db,
            monkeypatch,
            ["1", str(usuario.id), "1", "", "0", "0", "0"],
            transporte=transporte,
            settings=settings_de_prueba(),
        )
        == 0
    )

    salida = capsys.readouterr()
    transporte.enviar.assert_called_once()
    mensaje = transporte.enviar.call_args.args[0]
    cuerpo = str(mensaje.get_body(preferencelist=("plain",)).get_content())
    token = cuerpo.split("/activar-cuenta?token=", maxsplit=1)[1].splitlines()[0]
    assert cuerpo.count("/activar-cuenta?token=") == 1
    assert "Invitacion reenviada correctamente." in salida.out
    assert token not in salida.out + salida.err
    assert "/activar-cuenta?token=" not in salida.out + salida.err
    assert "Código:" not in salida.out + salida.err
    assert "Contraseña temporal:" not in salida.out + salida.err
    assert "contrasena_hash" not in salida.out + salida.err
    assert "token_hash" not in salida.out + salida.err
    assert mostrar_detalle.call_count == 2


def test_cli_cooldown_muestra_segundos_y_refresca_detalle(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    usuario = crear_usuario_manual(db)
    settings = settings_de_prueba(cooldown_segundos=10)
    primera = reenviar_activacion(
        db,
        usuario.correo,
        cooldown_segundos=settings.activacion_reenvio_cooldown_segundos,
        ahora=datetime.now(UTC),
    )
    assert primera is not None
    db.rollback()
    mostrar_detalle = MagicMock(wraps=cli._mostrar_detalle)
    monkeypatch.setattr(cli, "_mostrar_detalle", mostrar_detalle)

    assert (
        ejecutar_cli(
            db,
            monkeypatch,
            ["1", str(usuario.id), "1", "", "0", "0", "0"],
            settings=settings,
        )
        == 0
    )

    salida = capsys.readouterr()
    coincidencia = re.search(
        r"Debes esperar (\d+) segundos? antes de reenviar otra activación\.",
        salida.out,
    )
    assert coincidencia is not None
    segundos_restantes = int(coincidencia.group(1))
    assert 1 <= segundos_restantes <= settings.activacion_reenvio_cooldown_segundos
    assert "No fue posible reenviar la activacion en este momento." not in salida.out
    assert salida.out.count("SMART PARKING — ADMIN seleccionado") == 2
    assert "ID  | Nombre" in salida.out
    assert mostrar_detalle.call_count == 2


def test_cli_fallo_smtp_no_finge_entrega_y_conserva_activacion(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    usuario = crear_usuario_manual(db)
    transporte = MagicMock()
    transporte.enviar.side_effect = ErrorEnvioCorreo()
    mostrar_detalle = MagicMock(wraps=cli._mostrar_detalle)
    monkeypatch.setattr(cli, "_mostrar_detalle", mostrar_detalle)

    assert (
        ejecutar_cli(
            db,
            monkeypatch,
            ["1", str(usuario.id), "1", "", "0", "0", "0"],
            transporte=transporte,
        )
        == 0
    )

    salida = capsys.readouterr()
    assert "no se pudo entregar la invitacion" in salida.err.casefold()
    assert "Invitacion reenviada correctamente." not in salida.out
    assert mostrar_detalle.call_count == 2
    db.rollback()
    activacion = db.scalar(
        select(ActivacionCuenta).where(ActivacionCuenta.usuario_id == usuario.id)
    )
    assert activacion is not None


def test_cli_encadena_reenvio_regreso_lista_y_desactivacion(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    usuario = crear_usuario_manual(db)
    transporte = MagicMock()

    assert (
        ejecutar_cli(
            db,
            monkeypatch,
            [
                "1",
                str(usuario.id),
                "1",
                "",
                "0",
                str(usuario.id),
                "2",
                "s",
                "",
                "0",
                "0",
                "0",
            ],
            transporte=transporte,
        )
        == 0
    )

    transporte.enviar.assert_called_once()
    db.rollback()
    usuario_persistido = db.get(Usuario, usuario.id)
    assert usuario_persistido is not None
    assert usuario_persistido.esta_activo is False


def test_cli_cancelacion_no_emite_traceback(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def cancelar(_prompt: str) -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", cancelar)
    monkeypatch.setattr(cli, "limpiar_pantalla", lambda: None)

    assert cli.main(db=db, settings=settings_de_prueba()) == 1
    salida = capsys.readouterr()
    assert "Gestion cancelada." in salida.err
    assert "Traceback" not in salida.err


def test_me_y_login_rechazan_cuenta_despues_de_desactivacion(
    db: Session,
    client: TestClient,
) -> None:
    ahora = datetime(2026, 9, 28, 15, 0, tzinfo=UTC)
    usuario = crear_usuario_manual(db)
    activar_usuario(db, usuario)
    resultado = crear_sesion_vigente(db, usuario, ahora=ahora)
    administrador_id = usuario.id
    db.rollback()
    desactivar_administrador(db, administrador_id, ahora=ahora)

    respuesta_me = solicitar_con_cookies(
        client,
        "GET",
        RUTA_ME,
        cookies={"smart_parking_session": resultado.token},
    )
    respuesta_login = client.post(
        "/api/autenticacion/login",
        json={"correo": usuario.correo, "contrasena": CONTRASENA_PRUEBA},
    )

    assert respuesta_me.status_code == 401
    assert respuesta_login.status_code == 401
    assert respuesta_me.json() == {"detail": "No autenticado"}
    assert respuesta_login.json() == {"detail": "Credenciales invalidas"}
