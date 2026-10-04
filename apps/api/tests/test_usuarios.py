from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from io import StringIO
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.cli import crear_admin as cli
from app.cli import presentacion
from app.core.config import Settings
from app.models import ActivacionCuenta, RolUsuario, Sesion, Usuario
from app.seguridad.activaciones import hash_token_activacion
from app.seguridad.contrasenas import (
    ContrasenaInvalidaError,
    ContrasenasNoCoincidenError,
    crear_hash_contrasena,
    verificar_contrasena,
)
from app.servicios.usuarios import (
    CorreoDuplicadoError,
    CorreoInvalidoError,
    CorreoOperadorDuplicadoError,
    DatoOperadorInvalidoError,
    DatoPersonalInvalidoError,
    crear_admin,
    crear_admin_pendiente,
    crear_operador,
)


class SalidaTerminal(StringIO):
    def isatty(self) -> bool:
        return True


def correo_de_prueba() -> str:
    return f"sp003-test-{uuid4().hex}@example.com"


def settings_de_correo() -> Settings:
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
    )


def _crear_manual(
    db: Session, correo: str, contrasena: str = "Contrasena de prueba 123"
):
    return crear_admin(
        db,
        nombre="Ada",
        apellido_paterno="Lovelace",
        apellido_materno="Byron",
        correo=correo,
        contrasena=contrasena,
        confirmacion_contrasena=contrasena,
    )


def _ignorar_invitacion(_usuario: Usuario, _token: str) -> None:
    """Simula que el transporte acepto una invitacion de prueba."""


def _crear_operador(
    db: Session,
    correo: str,
    *,
    entregar_invitacion: Callable[[Usuario, str], None] = _ignorar_invitacion,
):
    return crear_operador(
        db,
        nombre="Grace",
        apellido_paterno="Hopper",
        apellido_materno="Murray",
        correo=correo,
        entregar_invitacion=entregar_invitacion,
        duracion_token_horas=24,
    )


def test_roles_canonicos_son_exactamente_admin_y_operador() -> None:
    assert tuple(RolUsuario.__members__) == ("ADMIN", "OPERADOR")
    assert tuple(rol.value for rol in RolUsuario) == ("ADMIN", "OPERADOR")


@pytest.mark.parametrize("rol", [RolUsuario.ADMIN, RolUsuario.OPERADOR])
def test_usuario_acepta_rol_canonico(rol: RolUsuario) -> None:
    usuario = Usuario(rol=rol)

    assert usuario.rol == rol.value


@pytest.mark.parametrize(
    "rol",
    ["admin", "operador", "SUPPORT", "ROOT", "UNKNOWN"],
)
def test_usuario_rechaza_rol_no_canonico(rol: str) -> None:
    with pytest.raises(ValueError, match="Rol de usuario no valido"):
        Usuario(rol=rol)


def test_crear_operador_guarda_estado_pendiente_y_solo_hash_de_invitacion(
    db: Session,
) -> None:
    correo = correo_de_prueba()
    tokens: list[str] = []

    def capturar_invitacion(_usuario: Usuario, token: str) -> None:
        tokens.append(token)

    resultado = _crear_operador(
        db,
        f"  {correo.upper()}  ",
        entregar_invitacion=capturar_invitacion,
    )
    token = tokens[0]
    usuario = db.get(Usuario, resultado.usuario.id)

    assert usuario is not None
    assert usuario.rol == RolUsuario.OPERADOR.value
    assert usuario.correo == correo
    assert usuario.esta_activo is True
    assert usuario.correo_verificado is False
    assert usuario.debe_cambiar_contrasena is False
    assert usuario.contrasena_hash is None
    activacion = db.scalar(
        select(ActivacionCuenta).where(ActivacionCuenta.usuario_id == usuario.id)
    )
    assert activacion is not None
    assert activacion.codigo_hash is None
    assert activacion.token_hash == hash_token_activacion(token)
    assert token not in activacion.token_hash
    assert activacion.expira_en - activacion.creado_en == timedelta(hours=24)
    assert (
        db.scalar(
            select(func.count())
            .select_from(Sesion)
            .where(Sesion.usuario_id == usuario.id)
        )
        == 0
    )


@pytest.mark.parametrize("rol_existente", [RolUsuario.ADMIN, RolUsuario.OPERADOR])
def test_crear_operador_rechaza_correo_normalizado_de_ambos_roles(
    db: Session,
    rol_existente: RolUsuario,
) -> None:
    correo = correo_de_prueba()
    if rol_existente is RolUsuario.ADMIN:
        _crear_manual(db, correo)
    else:
        _crear_operador(db, correo)

    with pytest.raises(CorreoOperadorDuplicadoError):
        _crear_operador(db, f"  {correo.upper()}  ")

    assert db.scalar(select(func.count()).select_from(Usuario)) == 1


@pytest.mark.parametrize("campo", ["nombre", "apellido_paterno", "apellido_materno"])
def test_crear_operador_rechaza_dato_personal_vacio_o_largo(
    db: Session,
    campo: str,
) -> None:
    datos = {
        "nombre": "Grace",
        "apellido_paterno": "Hopper",
        "apellido_materno": "Murray",
        "correo": correo_de_prueba(),
    }
    datos[campo] = "   "

    with pytest.raises(DatoOperadorInvalidoError):
        crear_operador(
            db,
            nombre=datos["nombre"],
            apellido_paterno=datos["apellido_paterno"],
            apellido_materno=datos["apellido_materno"],
            correo=datos["correo"],
            entregar_invitacion=_ignorar_invitacion,
            duracion_token_horas=24,
        )

    datos[campo] = "N" * 101
    with pytest.raises(DatoOperadorInvalidoError):
        crear_operador(
            db,
            nombre=datos["nombre"],
            apellido_paterno=datos["apellido_paterno"],
            apellido_materno=datos["apellido_materno"],
            correo=datos["correo"],
            entregar_invitacion=_ignorar_invitacion,
            duracion_token_horas=24,
        )


def test_crear_operador_rechaza_correo_invalido_sin_persistir(db: Session) -> None:
    with pytest.raises(CorreoInvalidoError):
        crear_operador(
            db,
            nombre="Grace",
            apellido_paterno="Hopper",
            apellido_materno="Murray",
            correo="correo-invalido",
            entregar_invitacion=_ignorar_invitacion,
            duracion_token_horas=24,
        )

    assert db.scalar(select(func.count()).select_from(Usuario)) == 0


def test_carrera_de_correo_de_operador_se_traduce_y_hace_rollback(db: Session) -> None:
    correo = correo_de_prueba()
    _crear_manual(db, correo)
    otra_sesion = Session(
        bind=db.get_bind(),
        autoflush=False,
        expire_on_commit=False,
    )
    try:
        with patch.object(otra_sesion, "scalar", return_value=None):
            with pytest.raises(CorreoOperadorDuplicadoError):
                _crear_operador(otra_sesion, correo)
    finally:
        otra_sesion.close()

    assert db.scalar(select(func.count()).select_from(Usuario)) == 1


def test_error_de_integridad_ajeno_a_correo_hace_rollback_y_se_propaga(
    db: Session,
) -> None:
    error = IntegrityError("insert", {}, RuntimeError("restriccion controlada"))
    with patch.object(db, "flush", side_effect=error):
        with pytest.raises(IntegrityError) as capturado:
            _crear_operador(db, correo_de_prueba())

    assert capturado.value is error
    assert db.scalar(select(func.count()).select_from(Usuario)) == 0


def test_crear_admin_manual_persiste_estado_y_hash(db: Session) -> None:
    contrasena = "  Contrasena manual 123  "
    resultado = _crear_manual(db, correo_de_prueba(), contrasena)

    usuario = db.get(Usuario, resultado.usuario.id)
    assert usuario is not None
    assert usuario.rol == RolUsuario.ADMIN.value
    assert usuario.correo_verificado is False
    assert usuario.esta_activo is True
    assert usuario.debe_cambiar_contrasena is False
    assert usuario.contrasena_hash is not None
    assert usuario.contrasena_hash.startswith("$argon2id$")
    assert verificar_contrasena(contrasena, usuario.contrasena_hash)
    assert resultado.contrasena_temporal is None


def test_crear_admin_temporal_retorna_secreto_ephemeral_y_solo_hash(
    db: Session,
) -> None:
    resultado = crear_admin(
        db,
        nombre="Grace",
        apellido_paterno="Hopper",
        apellido_materno="Murray",
        correo=correo_de_prueba(),
        usar_contrasena_temporal=True,
    )

    assert resultado.contrasena_temporal is not None
    assert len(resultado.contrasena_temporal) == 14
    usuario = db.get(Usuario, resultado.usuario.id)
    assert usuario is not None
    assert usuario.debe_cambiar_contrasena is True
    assert usuario.contrasena_hash is not None
    assert verificar_contrasena(resultado.contrasena_temporal, usuario.contrasena_hash)
    assert "contrasena" not in {col.name for col in Usuario.__table__.columns}
    assert usuario.contrasena_hash != resultado.contrasena_temporal


def test_hashes_de_misma_contrasena_usan_salt_distinto() -> None:
    primero = crear_hash_contrasena("Contrasena de prueba 123")
    segundo = crear_hash_contrasena("Contrasena de prueba 123")

    assert primero != segundo
    assert primero.startswith("$argon2id$")
    assert segundo.startswith("$argon2id$")


def test_correo_duplicado_rechaza_segunda_creacion(db: Session) -> None:
    correo = correo_de_prueba()
    _crear_manual(db, correo)

    with pytest.raises(CorreoDuplicadoError):
        _crear_manual(db, correo)

    assert (
        db.scalar(
            select(func.count()).select_from(Usuario).where(Usuario.correo == correo)
        )
        == 1
    )


def test_carrera_de_correo_duplicado_se_traduce_a_error_seguro(db: Session) -> None:
    correo = correo_de_prueba()
    _crear_manual(db, correo)
    otra_sesion = Session(
        bind=db.get_bind(),
        autoflush=False,
        expire_on_commit=False,
    )
    try:
        with patch.object(otra_sesion, "scalar", return_value=None):
            with pytest.raises(CorreoDuplicadoError):
                _crear_manual(otra_sesion, correo)
    finally:
        otra_sesion.close()

    assert (
        db.scalar(
            select(func.count()).select_from(Usuario).where(Usuario.correo == correo)
        )
        == 1
    )


def test_correo_normalizado_no_permite_duplicado_por_espacios_y_mayusculas(
    db: Session,
) -> None:
    correo = correo_de_prueba()
    _crear_manual(db, f"  {correo.upper()}  ")

    with pytest.raises(CorreoDuplicadoError):
        _crear_manual(db, correo)


def test_correo_invalido_rechaza_creacion(db: Session) -> None:
    cantidad_antes = db.scalar(select(func.count()).select_from(Usuario))
    db.rollback()
    with pytest.raises(CorreoInvalidoError):
        _crear_manual(db, "correo-no-valido")

    assert db.scalar(select(func.count()).select_from(Usuario)) == cantidad_antes


@pytest.mark.parametrize(
    "campo",
    ["nombre", "apellido_paterno", "apellido_materno"],
)
def test_dato_personal_vacio_rechaza_creacion(db: Session, campo: str) -> None:
    datos = {
        "nombre": "Ada",
        "apellido_paterno": "Lovelace",
        "apellido_materno": "Byron",
        "correo": correo_de_prueba(),
        "contrasena": "Contrasena de prueba 123",
        "confirmacion_contrasena": "Contrasena de prueba 123",
    }
    datos[campo] = "   "

    with pytest.raises(DatoPersonalInvalidoError):
        crear_admin(
            db,
            nombre=datos["nombre"],
            apellido_paterno=datos["apellido_paterno"],
            apellido_materno=datos["apellido_materno"],
            correo=datos["correo"],
            contrasena=datos["contrasena"],
            confirmacion_contrasena=datos["confirmacion_contrasena"],
        )


def test_datos_personales_no_se_truncan(db: Session) -> None:
    with pytest.raises(DatoPersonalInvalidoError):
        crear_admin(
            db,
            nombre="N" * 101,
            apellido_paterno="Lovelace",
            apellido_materno="Byron",
            correo=correo_de_prueba(),
            contrasena="Contrasena de prueba 123",
            confirmacion_contrasena="Contrasena de prueba 123",
        )


def test_contrasena_manual_9_caracteres_rechazada(db: Session) -> None:
    with pytest.raises(ContrasenaInvalidaError):
        _crear_manual(db, correo_de_prueba(), "Abcdefghi")


def test_contrasena_manual_10_y_128_caracteres_son_validas(db: Session) -> None:
    _crear_manual(db, correo_de_prueba(), "Abcdefghij")
    _crear_manual(db, correo_de_prueba(), "B" + "b" * 127)


def test_contrasena_manual_129_caracteres_rechazada(db: Session) -> None:
    with pytest.raises(ContrasenaInvalidaError):
        _crear_manual(db, correo_de_prueba(), "a" * 129)


def test_contrasena_con_espacios_no_se_recorta(db: Session) -> None:
    contrasena = "  Contrasena con espacios  "
    resultado = _crear_manual(db, correo_de_prueba(), contrasena)
    assert resultado.usuario.contrasena_hash is not None
    assert verificar_contrasena(contrasena, resultado.usuario.contrasena_hash)
    assert not verificar_contrasena(
        contrasena.strip(), resultado.usuario.contrasena_hash
    )


def test_contrasena_no_coincidente_no_escribe(db: Session) -> None:
    correo = correo_de_prueba()
    with pytest.raises(ContrasenasNoCoincidenError):
        crear_admin(
            db,
            nombre="Ada",
            apellido_paterno="Lovelace",
            apellido_materno="Byron",
            correo=correo,
            contrasena="Contrasena de prueba 123",
            confirmacion_contrasena="Otra contrasena de prueba",
        )

    assert db.scalar(select(Usuario.id).where(Usuario.correo == correo)) is None


def test_fallo_de_integridad_hace_rollback(db: Session) -> None:
    cantidad_antes = db.scalar(select(func.count()).select_from(Usuario))
    db.rollback()
    error = IntegrityError("insert", {}, RuntimeError("fallo controlado"))
    with patch.object(db, "flush", side_effect=error):
        with pytest.raises(IntegrityError):
            _crear_manual(db, correo_de_prueba())

    assert db.scalar(select(func.count()).select_from(Usuario)) == cantidad_antes


def test_creacion_no_genera_activacion_ni_sesion(db: Session) -> None:
    resultado = _crear_manual(db, correo_de_prueba())

    assert (
        db.scalar(
            select(func.count())
            .select_from(ActivacionCuenta)
            .where(ActivacionCuenta.usuario_id == resultado.usuario.id)
        )
        == 0
    )
    assert (
        db.scalar(
            select(func.count())
            .select_from(Sesion)
            .where(Sesion.usuario_id == resultado.usuario.id)
        )
        == 0
    )


def test_cli_solicita_solo_identidad_y_crea_admin_pendiente(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    correo = correo_de_prueba()
    respuestas = iter(["Ada", "Lovelace", "Byron", correo])
    prompts: list[str] = []

    def responder(prompt: str) -> str:
        prompts.append(prompt)
        return next(respuestas)

    monkeypatch.setattr("builtins.input", responder)
    transporte = MagicMock()

    assert cli.main(db=db, transporte=transporte, settings=settings_de_correo()) == 0

    assert prompts == [
        "Nombre: ",
        "Apellido paterno: ",
        "Apellido materno: ",
        "Correo: ",
    ]
    transporte.enviar.assert_called_once()
    mensaje = transporte.enviar.call_args.args[0]
    cuerpo_plano = str(mensaje.get_body(preferencelist=("plain",)).get_content())
    cuerpo_html = str(mensaje.get_body(preferencelist=("html",)).get_content())
    token = cuerpo_plano.split("/activar-cuenta?token=", maxsplit=1)[1].splitlines()[0]
    assert cuerpo_plano.count("/activar-cuenta?token=") == 1
    assert "/activar?" not in cuerpo_plano + cuerpo_html
    assert "Código:" not in cuerpo_plano + cuerpo_html
    assert "Contraseña temporal" not in cuerpo_plano + cuerpo_html
    assert correo not in cuerpo_plano + cuerpo_html
    usuario = db.scalar(select(Usuario).where(Usuario.correo == correo))
    assert usuario is not None
    activacion = db.scalar(
        select(ActivacionCuenta).where(ActivacionCuenta.usuario_id == usuario.id)
    )
    assert usuario.rol == RolUsuario.ADMIN.value
    assert usuario.esta_activo is True
    assert usuario.correo_verificado is False
    assert usuario.contrasena_hash is None
    assert usuario.debe_cambiar_contrasena is False
    assert activacion is not None
    assert activacion.codigo_hash is None
    assert activacion.token_hash == hash_token_activacion(token)
    salida = capsys.readouterr()
    assert token not in salida.out
    assert token not in salida.err
    assert correo not in salida.out
    assert "/activar-cuenta?token=" not in salida.out + salida.err
    assert "ADMIN creado. Correo de activacion enviado." in salida.out
    assert token not in repr(usuario)
    assert token not in repr(activacion)


def test_servicio_admin_pendiente_revierte_si_entrega_falla(db: Session) -> None:
    correo = correo_de_prueba()

    def fallar(_usuario: Usuario, _token: str) -> None:
        raise RuntimeError("entrega rechazada")

    with pytest.raises(RuntimeError, match="entrega rechazada"):
        crear_admin_pendiente(
            db,
            nombre="Ada",
            apellido_paterno="Lovelace",
            apellido_materno="Byron",
            correo=correo,
            entregar_invitacion=fallar,
            duracion_token_horas=24,
        )

    db.rollback()
    assert db.scalar(select(Usuario.id).where(Usuario.correo == correo)) is None
    assert db.scalar(select(func.count()).select_from(ActivacionCuenta)) == 0


def test_servicio_admin_pendiente_mapea_carrera_de_correo_duplicado(
    db: Session,
) -> None:
    correo = correo_de_prueba()
    _crear_manual(db, correo)
    otra_sesion = Session(
        bind=db.get_bind(),
        autoflush=False,
        expire_on_commit=False,
    )
    try:
        with patch.object(otra_sesion, "scalar", return_value=None):
            with pytest.raises(CorreoDuplicadoError):
                crear_admin_pendiente(
                    otra_sesion,
                    nombre="Grace",
                    apellido_paterno="Hopper",
                    apellido_materno="Murray",
                    correo=correo,
                    entregar_invitacion=_ignorar_invitacion,
                    duracion_token_horas=24,
                )
    finally:
        otra_sesion.close()

    assert (
        db.scalar(
            select(func.count()).select_from(Usuario).where(Usuario.correo == correo)
        )
        == 1
    )


def test_se_permite_crear_varios_admin_pendientes_sin_limite_global(
    db: Session,
) -> None:
    primer = crear_admin_pendiente(
        db,
        nombre="Ada",
        apellido_paterno="Lovelace",
        apellido_materno="Byron",
        correo=correo_de_prueba(),
        entregar_invitacion=_ignorar_invitacion,
        duracion_token_horas=24,
    )
    segundo = crear_admin_pendiente(
        db,
        nombre="Grace",
        apellido_paterno="Hopper",
        apellido_materno="Murray",
        correo=correo_de_prueba(),
        entregar_invitacion=_ignorar_invitacion,
        duracion_token_horas=24,
    )

    assert primer.usuario.id != segundo.usuario.id
    assert primer.usuario.rol == segundo.usuario.rol == RolUsuario.ADMIN.value


def test_cli_limpia_una_vez_y_muestra_titulo_antes_del_formulario(
    db,
    monkeypatch,
    capsys,
) -> None:
    eventos: list[str] = []
    correo = correo_de_prueba()
    respuestas = iter(["Ada", "Lovelace", "Byron", correo, "2"])

    monkeypatch.setattr(
        cli,
        "limpiar_pantalla",
        lambda: eventos.append("limpiar"),
    )

    def responder(prompt: str) -> str:
        eventos.append(prompt)
        return next(respuestas)

    monkeypatch.setattr("builtins.input", responder)
    transporte = MagicMock()

    assert (
        cli.main(
            db=db,
            transporte=transporte,
            settings=settings_de_correo(),
        )
        == 0
    )

    salida = capsys.readouterr().out
    assert eventos[0] == "limpiar"
    assert eventos[1] == "Nombre: "
    assert eventos.count("limpiar") == 1
    assert "SMART PARKING — CREAR ADMINISTRADOR" in salida


def test_cli_ctrl_cancela_sin_crear_usuario(monkeypatch, capsys) -> None:
    def interrumpir(_prompt):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", interrumpir)

    assert cli.main() == 1
    salida = capsys.readouterr()
    assert "Creacion cancelada." in salida.err
    assert "Traceback" not in salida.err


def test_cli_error_de_validacion_no_emite_traceback(db, monkeypatch, capsys) -> None:
    correo = correo_de_prueba()
    prompts = []
    limpiezas: list[None] = []
    respuestas = iter(
        [
            "Ada",
            "Lovelace",
            "Byron",
            "correo-invalido",
            correo,
            "1",
        ]
    )

    def responder(prompt):
        prompts.append(prompt)
        return next(respuestas)

    monkeypatch.setattr("builtins.input", responder)
    monkeypatch.setattr(
        cli,
        "limpiar_pantalla",
        lambda: limpiezas.append(None),
    )
    transporte = MagicMock()

    assert (
        cli.main(
            db=db,
            transporte=transporte,
            settings=settings_de_correo(),
        )
        == 0
    )
    salida = capsys.readouterr()
    assert "El correo no es valido." in salida.err
    assert prompts.count("Nombre: ") == 1
    assert prompts.count("Apellido paterno: ") == 1
    assert prompts.count("Apellido materno: ") == 1
    assert prompts.count("Correo: ") == 2
    assert len(limpiezas) == 1
    assert "Traceback" not in salida.err


def test_cli_reintenta_solo_correo_si_la_parte_local_es_invalida(
    db,
    monkeypatch,
    capsys,
) -> None:
    correo = correo_de_prueba()
    prompts = []
    respuestas = iter(
        [
            "Fernando",
            "Montejo",
            "Herrera",
            "@example.com",
            correo,
            "2",
        ]
    )

    def responder(prompt):
        prompts.append(prompt)
        return next(respuestas)

    monkeypatch.setattr("builtins.input", responder)
    transporte = MagicMock()

    assert (
        cli.main(
            db=db,
            transporte=transporte,
            settings=settings_de_correo(),
        )
        == 0
    )

    salida = capsys.readouterr()
    assert "El correo no es valido." in salida.err
    assert prompts.count("Nombre: ") == 1
    assert prompts.count("Apellido paterno: ") == 1
    assert prompts.count("Apellido materno: ") == 1
    assert prompts.count("Correo: ") == 2
    transporte.enviar.assert_called_once()


def test_cli_correo_duplicado_repite_solo_correo_sin_limpiar(
    db,
    monkeypatch,
    capsys,
) -> None:
    correo_existente = correo_de_prueba()
    _crear_manual(db, correo_existente)
    correo_nuevo = correo_de_prueba()
    prompts: list[str] = []
    limpiezas: list[None] = []
    respuestas = iter(
        [
            "Fernando",
            "Montejo",
            "Herrera",
            correo_existente,
            correo_nuevo,
            "2",
        ]
    )

    def responder(prompt: str) -> str:
        prompts.append(prompt)
        return next(respuestas)

    monkeypatch.setattr("builtins.input", responder)
    monkeypatch.setattr(
        cli,
        "limpiar_pantalla",
        lambda: limpiezas.append(None),
    )
    transporte = MagicMock()

    assert (
        cli.main(
            db=db,
            transporte=transporte,
            settings=settings_de_correo(),
        )
        == 0
    )

    salida = capsys.readouterr()
    assert "el correo ya esta registrado" in salida.err
    assert prompts.count("Nombre: ") == 1
    assert prompts.count("Apellido paterno: ") == 1
    assert prompts.count("Apellido materno: ") == 1
    assert prompts.count("Correo: ") == 2
    assert len(limpiezas) == 1


def test_cli_colorea_titulo_errores_y_exitos_sin_colorear_datos(
    db,
    monkeypatch,
    capsys,
) -> None:
    terminal = SalidaTerminal()
    correo = correo_de_prueba()
    respuestas = iter(
        ["Fernando", "Montejo", "Herrera", "correo-invalido", correo, "2"]
    )
    monkeypatch.setattr(cli.sys, "stdout", terminal)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(cli, "limpiar_pantalla", lambda: None)
    monkeypatch.setattr("builtins.input", lambda _prompt: next(respuestas))
    transporte = MagicMock()

    assert (
        cli.main(
            db=db,
            transporte=transporte,
            settings=settings_de_correo(),
        )
        == 0
    )

    salida = terminal.getvalue()
    error = capsys.readouterr().err
    assert (
        f"{cli.ANSI_CIAN_BRILLANTE}"
        "SMART PARKING — CREAR ADMINISTRADOR"
        f"{presentacion.ANSI_REINICIO}"
    ) in salida
    assert (
        f"{cli.ANSI_VERDE}ADMIN creado. Correo de activacion enviado."
        f"{presentacion.ANSI_REINICIO}" in salida
    )
    assert f"{cli.ANSI_ROJO}Error:" in error
    assert f"{cli.ANSI_VERDE}Correo: {correo}" not in salida


def test_cli_no_color_deja_salida_tty_legible_y_sin_ansi(
    db,
    monkeypatch,
    capsys,
) -> None:
    terminal = SalidaTerminal()
    correo = correo_de_prueba()
    respuestas = iter(["Ada", "Lovelace", "Byron", correo, "2"])
    monkeypatch.setattr(cli.sys, "stdout", terminal)
    monkeypatch.setenv("NO_COLOR", "")
    monkeypatch.setattr(cli, "limpiar_pantalla", lambda: None)
    monkeypatch.setattr("builtins.input", lambda _prompt: next(respuestas))
    transporte = MagicMock()

    assert (
        cli.main(
            db=db,
            transporte=transporte,
            settings=settings_de_correo(),
        )
        == 0
    )

    salida = terminal.getvalue()
    error = capsys.readouterr().err
    assert "SMART PARKING — CREAR ADMINISTRADOR" in salida
    assert "ADMIN creado. Correo de activacion enviado." in salida
    assert "\033[" not in salida
    assert "\033[" not in error


def test_cli_correo_valido_se_acepta_a_la_primera(
    db,
    monkeypatch,
) -> None:
    correo = correo_de_prueba()
    prompts = []
    respuestas = iter(["Ada", "Lovelace", "Byron", correo, "2"])

    def responder(prompt):
        prompts.append(prompt)
        return next(respuestas)

    monkeypatch.setattr("builtins.input", responder)
    transporte = MagicMock()

    assert (
        cli.main(
            db=db,
            transporte=transporte,
            settings=settings_de_correo(),
        )
        == 0
    )

    assert prompts.count("Nombre: ") == 1
    assert prompts.count("Apellido paterno: ") == 1
    assert prompts.count("Apellido materno: ") == 1
    assert prompts.count("Correo: ") == 1


def test_cli_correo_con_espacios_y_mayusculas_usa_normalizacion_canonica(
    db,
    monkeypatch,
) -> None:
    correo = correo_de_prueba()
    entrada = f"  {correo.upper()}  "
    respuestas = iter(["Ada", "Lovelace", "Byron", entrada, "2"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(respuestas))
    transporte = MagicMock()

    assert (
        cli.main(
            db=db,
            transporte=transporte,
            settings=settings_de_correo(),
        )
        == 0
    )

    mensaje = transporte.enviar.call_args.args[0]
    assert mensaje["To"] == correo
    assert "/activar-cuenta?token=" in str(
        mensaje.get_body(preferencelist=("plain",)).get_content()
    )
