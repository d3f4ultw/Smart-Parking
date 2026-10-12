from __future__ import annotations

import secrets
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from http.cookies import SimpleCookie
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import get_db
from app.correo.errores import ErrorEnvioCorreo
from app.models import (
    CuentaPropietario,
    DesvinculacionPropietario,
    InscripcionPropietario,
    RolUsuario,
    Sesion,
    Usuario,
)
from app.seguridad.activaciones import hash_token_activacion
from app.seguridad.contrasenas import crear_hash_contrasena, verificar_contrasena
from app.seguridad.limitador import MAXIMO_INTENTOS_POR_TOKEN
from app.seguridad.sesiones import hash_token_sesion
from app.servicios.autenticacion import autenticar_admin
from app.servicios.propietario import (
    COOLDOWN_REENVIO_SEGUNDOS,
    MAXIMO_REENVIO,
    VIGENCIA_ENLACE_MINUTOS,
    VIGENCIA_PROCESO_MINUTOS,
    ContrasenasPropietarioIgualesError,
    InscripcionPropietarioNoDisponible,
    InscripcionPropietarioYaEnCurso,
    LimiteReenviosPropietario,
    ReenvioPropietarioEnEspera,
    canjear_enlace_propietario,
    completar_inscripcion_propietario,
    iniciar_inscripcion_propietario,
    listar_estados_inscripciones_propietario,
    obtener_datos_desafio_propietario,
    obtener_tipo_cuenta_desafio,
)
from main import app

RUTA_OWNER = "/api/autenticacion/activacion-propietario"
NOMBRE_COOKIE_DESAFIO = "smart_parking_owner_activation_challenge"


class TransporteFalso:
    """Guarda correos de prueba solo en memoria o falla de forma controlada."""

    def __init__(self, *, fallar: bool = False) -> None:
        self.mensajes: list[EmailMessage] = []
        self.fallar = fallar

    def enviar(self, mensaje: EmailMessage) -> None:
        if self.fallar:
            raise ErrorEnvioCorreo
        self.mensajes.append(mensaje)


def contrasena_prueba(prefijo: str) -> str:
    return f"{prefijo} {uuid4().hex}"


def correo_prueba() -> str:
    return f"owner-{uuid4().hex}@example.com"


def iniciar(db: Session, correo: str, *, ahora: datetime | None = None) -> str:
    tokens: list[str] = []
    iniciar_inscripcion_propietario(
        db,
        correo=correo,
        ahora=ahora,
        entregar_enlace=lambda _correo, token: tokens.append(token),
    )
    assert len(tokens) == 1
    return tokens[0]


def desafio(db: Session, token: str, *, ahora: datetime | None = None) -> str:
    return canjear_enlace_propietario(
        db,
        token=token,
        duracion_desafio_minutos=15,
        ahora=ahora,
    ).token


def crear_usuario_elegible(
    db: Session,
    rol: RolUsuario,
    *,
    correo: str | None = None,
    activo: bool = True,
    verificado: bool = True,
    debe_cambiar: bool = False,
    con_hash: bool = True,
) -> tuple[Usuario, str | None]:
    contrasena = contrasena_prueba("Login existente") if con_hash else None
    usuario = Usuario(
        nombre="Ada",
        apellido_paterno="Lovelace",
        apellido_materno="Byron",
        correo=correo or correo_prueba(),
        contrasena_hash=(
            crear_hash_contrasena(contrasena) if contrasena is not None else None
        ),
        rol=rol.value,
        correo_verificado=verificado,
        debe_cambiar_contrasena=debe_cambiar,
        esta_activo=activo,
    )
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario, contrasena


def crear_propietario_desvinculado(
    db: Session,
    *,
    correo: str | None = None,
    nombre: str = "Ada",
    apellido_paterno: str = "Lovelace",
    apellido_materno: str = "Byron",
) -> tuple[Usuario, str, str, str]:
    """Crea en la base de prueba un OWNER roleless con historial confirmado."""

    ahora = datetime.now(UTC)
    login = contrasena_prueba("Acceso original")
    contrasena_admin_anterior = contrasena_prueba("Administracion anterior")
    hash_admin_anterior = crear_hash_contrasena(contrasena_admin_anterior)
    usuario = Usuario(
        nombre=nombre,
        apellido_paterno=apellido_paterno,
        apellido_materno=apellido_materno,
        correo=correo or correo_prueba(),
        contrasena_hash=crear_hash_contrasena(login),
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
            token_hash=hash_token_activacion(secrets.token_urlsafe(32)),
            emitida_en=ahora - timedelta(minutes=30),
            expira_en=ahora - timedelta(minutes=15),
            consumida_en=ahora - timedelta(minutes=10),
        )
    )
    cuenta.contrasena_admin_hash = None
    db.commit()
    db.refresh(usuario)
    db.refresh(cuenta)
    return usuario, login, contrasena_admin_anterior, hash_admin_anterior


@pytest.fixture
def client(database_url: URL) -> Generator[TestClient]:
    motor = create_engine(database_url, pool_pre_ping=True)
    fabrica = sessionmaker(bind=motor, autoflush=False, expire_on_commit=False)

    def override_get_db() -> Generator[Session]:
        sesion = fabrica()
        try:
            yield sesion
        finally:
            sesion.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as cliente:
            yield cliente
    finally:
        app.dependency_overrides.pop(get_db, None)
        motor.dispose()


def test_enlace_verifica_email_y_registra_cuenta_nueva_con_credenciales_separadas(
    db: Session,
) -> None:
    correo = correo_prueba()
    token = iniciar(db, correo)
    assert db.scalar(select(func.count(Usuario.id))) == 0
    assert db.scalar(select(func.count(InscripcionPropietario.id))) == 1
    inscripcion = db.scalar(select(InscripcionPropietario))
    assert inscripcion is not None
    assert inscripcion.token_hash == hash_token_activacion(token)
    assert token not in inscripcion.token_hash
    assert inscripcion.expira_en - inscripcion.ultimo_envio_en == timedelta(
        minutes=VIGENCIA_ENLACE_MINUTOS
    )
    assert inscripcion.proceso_expira_en - inscripcion.ultimo_envio_en == timedelta(
        minutes=VIGENCIA_PROCESO_MINUTOS
    )
    assert obtener_tipo_cuenta_desafio(db, token_desafio=None) is None

    token_desafio = desafio(db, token)
    assert obtener_tipo_cuenta_desafio(db, token_desafio=token_desafio) == "nueva"
    login = contrasena_prueba("Acceso independiente")
    admin = contrasena_prueba("Administracion independiente")
    completar_inscripcion_propietario(
        db,
        token_desafio=token_desafio,
        contrasena_login=login,
        confirmar_contrasena_login=login,
        contrasena_admin=admin,
        confirmar_contrasena_admin=admin,
        nombre="Ada",
        apellido_paterno="Lovelace",
        apellido_materno="Byron",
    )

    usuario = db.scalar(select(Usuario).where(Usuario.correo == correo.casefold()))
    cuenta = db.scalar(select(CuentaPropietario))
    assert usuario is not None
    assert usuario.rol == RolUsuario.OWNER.value
    assert usuario.correo_verificado is True
    assert usuario.esta_activo is True
    assert usuario.debe_cambiar_contrasena is False
    assert " ".join(
        parte
        for parte in (
            usuario.nombre,
            usuario.apellido_paterno,
            usuario.apellido_materno,
        )
        if parte
    ) == "Ada Lovelace Byron"
    assert cuenta is not None and cuenta.usuario_id == usuario.id
    assert cuenta is not None
    assert cuenta.rol_anterior is None
    assert usuario.contrasena_hash is not None
    assert verificar_contrasena(login, usuario.contrasena_hash)
    assert not verificar_contrasena(admin, usuario.contrasena_hash)
    assert cuenta.contrasena_admin_hash is not None
    assert verificar_contrasena(admin, cuenta.contrasena_admin_hash)
    assert not verificar_contrasena(login, cuenta.contrasena_admin_hash)
    assert autenticar_admin(db, correo=correo, contrasena=login)
    assert not autenticar_admin(db, correo=correo, contrasena=admin)
    assert obtener_tipo_cuenta_desafio(db, token_desafio=token_desafio) is None
    with pytest.raises(InscripcionPropietarioNoDisponible):
        completar_inscripcion_propietario(
            db,
            token_desafio=token_desafio,
            contrasena_login=login,
            confirmar_contrasena_login=login,
            contrasena_admin=admin,
            confirmar_contrasena_admin=admin,
            nombre="Ada",
            apellido_paterno="Lovelace",
        )


@pytest.mark.parametrize("rol", [RolUsuario.ADMIN, RolUsuario.OPERADOR])
def test_no_promueve_cuentas_asignadas_a_admin_u_operador(
    db: Session,
    rol: RolUsuario,
) -> None:
    correo = correo_prueba()
    usuario, login = crear_usuario_elegible(db, rol, correo=correo)
    assert login is not None and usuario.contrasena_hash is not None
    hash_login = usuario.contrasena_hash
    transporte = TransporteFalso()

    with pytest.raises(InscripcionPropietarioNoDisponible):
        iniciar_inscripcion_propietario(
            db,
            correo=correo,
            entregar_enlace=lambda _correo, _token: transporte.enviar(EmailMessage()),
        )

    db.refresh(usuario)
    assert usuario.rol == rol.value
    assert usuario.contrasena_hash == hash_login
    assert db.scalar(select(func.count(CuentaPropietario.id))) == 0
    assert db.scalar(select(func.count(InscripcionPropietario.id))) == 0
    assert transporte.mensajes == []


def test_reinscribe_propietario_roleless_con_nombre_corregido_y_hash_nuevo(
    db: Session,
) -> None:
    correo = correo_prueba()
    usuario, login, admin_anterior, hash_admin_anterior = (
        crear_propietario_desvinculado(db, correo=correo)
    )
    usuario_id = usuario.id
    cuenta_id = db.scalar(
        select(CuentaPropietario.id).where(CuentaPropietario.usuario_id == usuario_id)
    )
    hash_login = usuario.contrasena_hash
    nombre_previo = "Ada Lovelace Byron"
    assert " ".join(
        parte
        for parte in (
            usuario.nombre,
            usuario.apellido_paterno,
            usuario.apellido_materno,
        )
        if parte
    ) == nombre_previo
    token_sesion = secrets.token_urlsafe(32)
    db.add(
        Sesion(
            usuario_id=usuario_id,
            token_hash=hash_token_sesion(token_sesion),
            expira_en=datetime.now(UTC) + timedelta(hours=1),
            creado_en=datetime.now(UTC),
        )
    )
    db.commit()

    token = iniciar(db, correo)
    inscripcion = db.scalar(select(InscripcionPropietario))
    assert inscripcion is not None and inscripcion.usuario_id == usuario_id
    assert inscripcion.rol_anterior is None
    token_desafio = desafio(db, token)
    datos_desafio = obtener_datos_desafio_propietario(
        db,
        token_desafio=token_desafio,
    )
    assert datos_desafio.tipo_cuenta == "retorno"
    assert datos_desafio.nombre == "Ada"
    assert datos_desafio.apellido_paterno == "Lovelace"
    assert datos_desafio.apellido_materno == "Byron"
    assert datos_desafio.expira_en is not None
    assert obtener_tipo_cuenta_desafio(db, token_desafio=token_desafio) == "retorno"
    with pytest.raises(ContrasenasPropietarioIgualesError):
        completar_inscripcion_propietario(
            db,
            token_desafio=token_desafio,
            contrasena_admin=login,
            confirmar_contrasena_admin=login,
            nombre="Nombre corregido",
            apellido_paterno="Lovelace",
            apellido_materno="Byron",
        )
    assert obtener_tipo_cuenta_desafio(db, token_desafio=token_desafio) == "retorno"
    db.refresh(usuario)
    assert usuario.rol is None
    assert usuario.contrasena_hash == hash_login
    assert (usuario.nombre, usuario.apellido_paterno, usuario.apellido_materno) == (
        "Ada",
        "Lovelace",
        "Byron",
    )
    admin_nueva = contrasena_prueba("Administracion nueva")
    nombre_corregido = "Ada M. Lovelace Byron"
    completar_inscripcion_propietario(
        db,
        token_desafio=token_desafio,
        contrasena_admin=admin_nueva,
        confirmar_contrasena_admin=admin_nueva,
        nombre="Ada M.",
        apellido_paterno="Lovelace",
        apellido_materno="Byron",
    )

    usuario_actual = db.get(Usuario, usuario_id)
    cuenta_actual = db.scalar(
        select(CuentaPropietario).where(CuentaPropietario.usuario_id == usuario_id)
    )
    assert usuario_actual is not None
    assert usuario_actual.id == usuario_id
    assert usuario_actual.correo == correo.casefold()
    assert usuario_actual.rol == RolUsuario.OWNER.value
    assert usuario_actual.contrasena_hash == hash_login
    assert " ".join(
        parte
        for parte in (
            usuario_actual.nombre,
            usuario_actual.apellido_paterno,
            usuario_actual.apellido_materno,
        )
        if parte
    ) == nombre_corregido
    assert cuenta_actual is not None
    assert cuenta_actual.id == cuenta_id
    assert cuenta_actual.rol_anterior is None
    assert cuenta_actual.contrasena_admin_hash is not None
    assert cuenta_actual.contrasena_admin_hash != hash_admin_anterior
    assert verificar_contrasena(admin_nueva, cuenta_actual.contrasena_admin_hash)
    assert not verificar_contrasena(admin_anterior, cuenta_actual.contrasena_admin_hash)
    assert not verificar_contrasena(login, cuenta_actual.contrasena_admin_hash)
    assert autenticar_admin(db, correo=correo, contrasena=login)
    assert not autenticar_admin(db, correo=correo, contrasena=admin_anterior)
    assert not autenticar_admin(db, correo=correo, contrasena=admin_nueva)
    assert db.scalar(select(func.count(Usuario.id))) == 1
    assert db.scalar(select(func.count(CuentaPropietario.id))) == 1
    assert db.scalar(select(func.count(DesvinculacionPropietario.id))) == 1
    assert db.scalar(select(func.count(Sesion.id))) == 1
    sesion = db.scalar(
        select(Sesion).where(Sesion.token_hash == hash_token_sesion(token_sesion))
    )
    assert sesion is not None and sesion.revocado_en is not None
    assert nombre_previo != nombre_corregido


def test_rechaza_cuenta_sin_rol_y_sin_historial_owner(
    db: Session,
) -> None:
    correo = correo_prueba()
    usuario = Usuario(
        correo=correo,
        contrasena_hash=crear_hash_contrasena(contrasena_prueba("Login roleless")),
        rol=None,
        correo_verificado=True,
        debe_cambiar_contrasena=False,
        esta_activo=True,
    )
    db.add(usuario)
    db.commit()
    correos_enviados: list[str] = []

    with pytest.raises(InscripcionPropietarioNoDisponible):
        iniciar_inscripcion_propietario(
            db,
            correo=correo,
            entregar_enlace=lambda destino, _token: correos_enviados.append(destino),
        )

    assert correos_enviados == []
    assert db.scalar(select(func.count(Usuario.id))) == 1
    assert db.scalar(select(func.count(InscripcionPropietario.id))) == 0


def test_reinscripcion_completa_nombre_de_cuenta_roleless_incompleta(
    db: Session,
) -> None:
    correo = correo_prueba()
    usuario, _login, _admin_anterior, _hash_admin_anterior = (
        crear_propietario_desvinculado(
            db,
            correo=correo,
            nombre="",
            apellido_paterno="",
            apellido_materno="",
        )
    )
    token = iniciar(db, correo)
    token_desafio = desafio(db, token)
    datos_desafio = obtener_datos_desafio_propietario(
        db,
        token_desafio=token_desafio,
    )
    assert datos_desafio.tipo_cuenta == "retorno"
    assert datos_desafio.nombre == ""
    assert datos_desafio.apellido_paterno == ""
    assert datos_desafio.apellido_materno == ""

    contrasena_admin = contrasena_prueba("Administracion renovada")
    completar_inscripcion_propietario(
        db,
        token_desafio=token_desafio,
        contrasena_admin=contrasena_admin,
        confirmar_contrasena_admin=contrasena_admin,
        nombre="Grace",
        apellido_paterno="Hopper",
    )

    db.refresh(usuario)
    assert usuario.rol == RolUsuario.OWNER.value
    assert " ".join(
        parte
        for parte in (
            usuario.nombre,
            usuario.apellido_paterno,
            usuario.apellido_materno,
        )
        if parte
    ) == "Grace Hopper"


def test_owner_activo_bloquea_nueva_inscripcion_y_retorno(
    db: Session,
) -> None:
    owner = Usuario(
        correo=correo_prueba(),
        contrasena_hash=crear_hash_contrasena(contrasena_prueba("Login activo")),
        rol=RolUsuario.OWNER.value,
        correo_verificado=True,
        debe_cambiar_contrasena=False,
        esta_activo=True,
    )
    db.add(owner)
    db.flush()
    db.add(
        CuentaPropietario(
            usuario_id=owner.id,
            contrasena_admin_hash=crear_hash_contrasena(
                contrasena_prueba("Admin activo")
            ),
            rol_anterior=None,
        )
    )
    correo_retorno = correo_prueba()
    crear_propietario_desvinculado(db, correo=correo_retorno)
    db.commit()
    correos_enviados: list[str] = []

    for correo in (correo_prueba(), correo_retorno):
        with pytest.raises(InscripcionPropietarioNoDisponible):
            iniciar_inscripcion_propietario(
                db,
                correo=correo,
                entregar_enlace=lambda destino, _token: correos_enviados.append(
                    destino
                ),
            )

    assert correos_enviados == []
    assert db.scalar(select(func.count(InscripcionPropietario.id))) == 0


@pytest.mark.parametrize(
    "estado",
    ["deshabilitada", "sin_verificar", "invitacion_pendiente", "sin_hash"],
)
def test_rechaza_cuentas_no_elegibles_sin_cambiarlas_ni_enviar_correo(
    db: Session,
    estado: str,
) -> None:
    atributos = {
        "deshabilitada": {"activo": False},
        "sin_verificar": {"verificado": False},
        "invitacion_pendiente": {"debe_cambiar": True},
        "sin_hash": {"con_hash": False, "verificado": False},
    }[estado]
    correo = correo_prueba()
    usuario, _ = crear_usuario_elegible(
        db,
        RolUsuario.ADMIN,
        correo=correo,
        **atributos,
    )
    estado_anterior = (
        usuario.id,
        usuario.rol,
        usuario.esta_activo,
        usuario.correo_verificado,
        usuario.debe_cambiar_contrasena,
        usuario.contrasena_hash,
    )
    transporte = TransporteFalso()

    with pytest.raises(InscripcionPropietarioNoDisponible):
        iniciar_inscripcion_propietario(
            db,
            correo=correo,
            entregar_enlace=lambda _correo, _token: transporte.enviar(EmailMessage()),
        )

    db.refresh(usuario)
    assert (
        usuario.id,
        usuario.rol,
        usuario.esta_activo,
        usuario.correo_verificado,
        usuario.debe_cambiar_contrasena,
        usuario.contrasena_hash,
    ) == estado_anterior
    assert transporte.mensajes == []
    assert db.scalar(select(func.count(InscripcionPropietario.id))) == 0


def test_reenvios_respetan_cooldown_maximo_y_reemplazan_el_enlace_anterior(
    db: Session,
) -> None:
    inicio = datetime(2026, 10, 11, 8, 0, tzinfo=UTC)
    correo = correo_prueba()
    tokens: list[str] = []

    def entregar(_correo: str, token: str) -> None:
        tokens.append(token)

    iniciar_inscripcion_propietario(
        db,
        correo=correo,
        entregar_enlace=entregar,
        ahora=inicio,
    )
    with pytest.raises(ReenvioPropietarioEnEspera) as espera:
        iniciar_inscripcion_propietario(
            db,
            correo=correo,
            entregar_enlace=entregar,
            ahora=inicio + timedelta(seconds=COOLDOWN_REENVIO_SEGUNDOS - 1),
        )
    assert espera.value.segundos_restantes == 1

    for numero in range(1, MAXIMO_REENVIO + 1):
        iniciar_inscripcion_propietario(
            db,
            correo=correo,
            entregar_enlace=entregar,
            ahora=inicio + timedelta(seconds=COOLDOWN_REENVIO_SEGUNDOS * numero),
        )
    assert len(tokens) == MAXIMO_REENVIO + 1
    registro = db.scalar(select(InscripcionPropietario))
    assert registro is not None
    assert registro.reenviados == MAXIMO_REENVIO
    assert registro.token_hash == hash_token_activacion(tokens[-1])
    ultimo_envio = inicio + timedelta(
        seconds=COOLDOWN_REENVIO_SEGUNDOS * MAXIMO_REENVIO
    )
    assert registro.expira_en == ultimo_envio + timedelta(
        minutes=VIGENCIA_ENLACE_MINUTOS
    )
    assert registro.proceso_expira_en == inicio + timedelta(
        minutes=VIGENCIA_PROCESO_MINUTOS
    )
    with pytest.raises(LimiteReenviosPropietario):
        iniciar_inscripcion_propietario(
            db,
            correo=correo,
            entregar_enlace=entregar,
            ahora=inicio + timedelta(seconds=COOLDOWN_REENVIO_SEGUNDOS * 4),
        )
    with pytest.raises(InscripcionPropietarioNoDisponible):
        canjear_enlace_propietario(
            db,
            token=tokens[0],
            duracion_desafio_minutos=15,
            ahora=inicio + timedelta(seconds=COOLDOWN_REENVIO_SEGUNDOS),
        )
    assert desafio(
        db,
        tokens[-1],
        ahora=inicio + timedelta(seconds=COOLDOWN_REENVIO_SEGUNDOS * 3),
    )


def test_proceso_pendiente_no_se_reinicia_ni_reenvia_automaticamente(
    db: Session,
) -> None:
    ahora = datetime(2026, 10, 11, 8, 0, tzinfo=UTC)
    correo = correo_prueba()
    tokens: list[str] = []
    iniciar_inscripcion_propietario(
        db,
        correo=correo,
        entregar_enlace=lambda _correo, token: tokens.append(token),
        ahora=ahora,
    )
    registro = db.scalar(select(InscripcionPropietario))
    assert registro is not None
    estado_anterior = (
        registro.token_hash,
        registro.ultimo_envio_en,
        registro.expira_en,
        registro.proceso_expira_en,
        registro.reenviados,
    )

    with pytest.raises(InscripcionPropietarioYaEnCurso):
        iniciar_inscripcion_propietario(
            db,
            correo=correo,
            entregar_enlace=lambda _correo, token: tokens.append(token),
            modo="nueva",
            ahora=ahora + timedelta(minutes=1),
        )

    db.refresh(registro)
    assert len(tokens) == 1
    assert (
        registro.token_hash,
        registro.ultimo_envio_en,
        registro.expira_en,
        registro.proceso_expira_en,
        registro.reenviados,
    ) == estado_anterior


def test_proceso_expirado_se_puede_reiniciar_sin_enlace_viejo(
    db: Session,
) -> None:
    inicio = datetime(2026, 10, 11, 8, 0, tzinfo=UTC)
    correo = correo_prueba()
    tokens: list[str] = []

    def enviar(_correo: str, token: str) -> None:
        tokens.append(token)

    iniciar_inscripcion_propietario(
        db,
        correo=correo,
        entregar_enlace=enviar,
        ahora=inicio,
    )
    vencimiento = inicio + timedelta(minutes=VIGENCIA_PROCESO_MINUTOS)
    with pytest.raises(InscripcionPropietarioNoDisponible):
        canjear_enlace_propietario(
            db,
            token=tokens[0],
            duracion_desafio_minutos=15,
            ahora=vencimiento,
        )
    iniciar_inscripcion_propietario(
        db,
        correo=correo,
        entregar_enlace=enviar,
        ahora=vencimiento,
    )
    assert len(tokens) == 2
    registro = db.scalar(select(InscripcionPropietario))
    assert registro is not None and registro.reenviados == 0
    assert registro.token_hash == hash_token_activacion(tokens[1])
    assert registro.expira_en == vencimiento + timedelta(
        minutes=VIGENCIA_ENLACE_MINUTOS
    )
    assert registro.proceso_expira_en == vencimiento + timedelta(
        minutes=VIGENCIA_PROCESO_MINUTOS
    )
    with pytest.raises(ReenvioPropietarioEnEspera) as espera:
        iniciar_inscripcion_propietario(
            db,
            correo=correo,
            entregar_enlace=enviar,
            ahora=vencimiento + timedelta(seconds=1),
        )
    assert espera.value.segundos_restantes == COOLDOWN_REENVIO_SEGUNDOS - 1


def test_estado_de_inscripcion_distingue_pendiente_bloqueado_expirado_y_completado(
    db: Session,
) -> None:
    ahora = datetime.now(UTC)
    correos = {
        estado: correo_prueba()
        for estado in ("pendiente", "bloqueado", "expirado", "completado")
    }
    for nombre, correo in correos.items():
        minutos_desde_envio = {
            "pendiente": 1,
            "bloqueado": 20,
            "expirado": 61,
            "completado": 20,
        }[nombre]
        inicio = ahora - timedelta(minutes=minutos_desde_envio)
        iniciar_inscripcion_propietario(
            db,
            correo=correo,
            entregar_enlace=lambda _correo, _token: None,
            ahora=inicio,
        )
        if nombre == "bloqueado":
            for numero in range(1, MAXIMO_REENVIO + 1):
                iniciar_inscripcion_propietario(
                    db,
                    correo=correo,
                    entregar_enlace=lambda _correo, _token: None,
                    ahora=inicio
                    + timedelta(seconds=COOLDOWN_REENVIO_SEGUNDOS * numero),
                )
        if nombre == "completado":
            registro = db.scalar(
                select(InscripcionPropietario).where(
                    InscripcionPropietario.correo == correo
                )
            )
            assert registro is not None
            registro.consumido_en = ahora
            db.commit()

    estados = {
        estado.correo: estado
        for estado in listar_estados_inscripciones_propietario(db, ahora=ahora)
    }

    assert estados[correos["pendiente"]].estado == "pendiente"
    assert estados[correos["pendiente"]].reenvio_bloqueado is True
    assert estados[correos["pendiente"]].segundos_cooldown > 0
    assert estados[correos["bloqueado"]].estado == "bloqueado"
    assert estados[correos["bloqueado"]].reenviados_restantes == 0
    assert estados[correos["expirado"]].estado == "expirado"
    assert estados[correos["completado"]].estado == "completado"


def test_desafio_no_extiende_la_vigencia_total_del_enlace(
    db: Session,
) -> None:
    inicio = datetime(2026, 10, 11, 8, 0, tzinfo=UTC)
    correo = correo_prueba()
    token = iniciar(db, correo, ahora=inicio)
    apertura = inicio + timedelta(minutes=10)
    desafio_anterior = desafio(db, token, ahora=apertura)
    token_desafio = canjear_enlace_propietario(
        db,
        token=token,
        duracion_desafio_minutos=15,
        ahora=apertura + timedelta(minutes=2),
    ).token

    inscripcion = db.scalar(select(InscripcionPropietario))
    assert inscripcion is not None
    assert inscripcion.desafio_expira_en == inicio + timedelta(minutes=15)
    assert (
        obtener_tipo_cuenta_desafio(
            db,
            token_desafio=desafio_anterior,
            ahora=inicio + timedelta(minutes=14),
        )
        is None
    )
    assert (
        obtener_tipo_cuenta_desafio(
            db,
            token_desafio=token_desafio,
            ahora=inicio + timedelta(minutes=14, seconds=59),
        )
        == "nueva"
    )
    assert (
        obtener_tipo_cuenta_desafio(
            db,
            token_desafio=token_desafio,
            ahora=inicio + timedelta(minutes=15),
        )
        is None
    )

    contrasena_login = contrasena_prueba("Acceso independiente")
    contrasena_admin = contrasena_prueba("Administracion independiente")
    with pytest.raises(InscripcionPropietarioNoDisponible):
        completar_inscripcion_propietario(
            db,
            token_desafio=token_desafio,
            contrasena_login=contrasena_login,
            confirmar_contrasena_login=contrasena_login,
            contrasena_admin=contrasena_admin,
            confirmar_contrasena_admin=contrasena_admin,
            nombre="Nombre",
            apellido_paterno="Propietario",
            ahora=inicio + timedelta(minutes=15),
        )
    assert db.scalar(select(Usuario).where(Usuario.correo == correo.casefold())) is None


def test_enlace_caduca_a_los_quince_minutos_con_proceso_aun_activo(
    db: Session,
) -> None:
    inicio = datetime(2026, 10, 11, 8, 0, tzinfo=UTC)
    correo = correo_prueba()
    token_anterior = iniciar(db, correo, ahora=inicio)
    ahora = inicio + timedelta(minutes=16)

    estado = next(
        estado
        for estado in listar_estados_inscripciones_propietario(db, ahora=ahora)
        if estado.correo == correo
    )
    assert estado.estado == "pendiente"
    assert estado.enlace_vigente is False
    assert estado.segundos_proceso == 44 * 60

    tokens_nuevos: list[str] = []
    iniciar_inscripcion_propietario(
        db,
        correo=correo,
        entregar_enlace=lambda _correo, token: tokens_nuevos.append(token),
        ahora=ahora,
    )
    registro = db.scalar(select(InscripcionPropietario))
    assert registro is not None
    assert registro.expira_en == inicio + timedelta(minutes=31)
    assert registro.proceso_expira_en == inicio + timedelta(minutes=60)
    assert registro.token_hash == hash_token_activacion(tokens_nuevos[0])
    with pytest.raises(InscripcionPropietarioNoDisponible):
        canjear_enlace_propietario(
            db,
            token=token_anterior,
            duracion_desafio_minutos=15,
            ahora=ahora,
        )


def test_fallo_smtp_no_persiste_proceso_ni_consume_reenvio(db: Session) -> None:
    correo = correo_prueba()
    transporte = TransporteFalso(fallar=True)
    with pytest.raises(ErrorEnvioCorreo):
        iniciar_inscripcion_propietario(
            db,
            correo=correo,
            entregar_enlace=lambda _correo, token: transporte.enviar(EmailMessage()),
        )
    assert db.scalar(select(func.count(InscripcionPropietario.id))) == 0

    token = iniciar(db, correo)
    assert token
    registro = db.scalar(select(InscripcionPropietario))
    assert registro is not None and registro.reenviados == 0


def test_fallo_smtp_en_reenvio_conserva_enlace_vigente_y_contador(
    db: Session,
) -> None:
    inicio = datetime(2026, 10, 11, 8, 0, tzinfo=UTC)
    correo = correo_prueba()
    tokens: list[str] = []
    iniciar_inscripcion_propietario(
        db,
        correo=correo,
        entregar_enlace=lambda _correo, token: tokens.append(token),
        ahora=inicio,
    )
    registro = db.scalar(select(InscripcionPropietario))
    assert registro is not None
    hash_anterior = registro.token_hash
    ultimo_envio_anterior = registro.ultimo_envio_en

    def entregar_fallido(_correo: str, _token: str) -> None:
        raise ErrorEnvioCorreo

    with pytest.raises(ErrorEnvioCorreo):
        iniciar_inscripcion_propietario(
            db,
            correo=correo,
            entregar_enlace=entregar_fallido,
            ahora=inicio + timedelta(seconds=COOLDOWN_REENVIO_SEGUNDOS),
        )

    db.refresh(registro)
    assert registro.token_hash == hash_anterior
    assert registro.ultimo_envio_en == ultimo_envio_anterior
    assert registro.reenviados == 0
    assert desafio(
        db,
        tokens[0],
        ahora=inicio + timedelta(seconds=COOLDOWN_REENVIO_SEGUNDOS),
    )


def test_inicio_concurrente_del_mismo_correo_envia_un_solo_enlace(
    db: Session,
    database_url: URL,
) -> None:
    correo = correo_prueba()
    motor = create_engine(database_url, pool_pre_ping=True)
    barrera = Barrier(2)
    enlaces: list[str] = []

    def iniciar_concurrente() -> str:
        with Session(motor) as sesion:
            barrera.wait(timeout=15)
            try:
                iniciar_inscripcion_propietario(
                    sesion,
                    correo=correo,
                    entregar_enlace=lambda _correo, token: enlaces.append(token),
                )
                return "enviado"
            except ReenvioPropietarioEnEspera:
                return "en espera"

    try:
        with ThreadPoolExecutor(max_workers=2) as ejecutores:
            tareas = [ejecutores.submit(iniciar_concurrente) for _ in range(2)]
            resultados = tuple(tarea.result() for tarea in tareas)
    finally:
        motor.dispose()

    assert sorted(resultados) == ["en espera", "enviado"]
    assert len(enlaces) == 1
    registro = db.scalar(
        select(InscripcionPropietario).where(InscripcionPropietario.correo == correo)
    )
    assert registro is not None
    assert registro.token_hash == hash_token_activacion(enlaces[0])
    assert registro.reenviados == 0


def test_reenvios_concurrentes_respetan_cooldown_y_reemplazan_un_solo_enlace(
    db: Session,
    database_url: URL,
) -> None:
    correo = correo_prueba()
    inicio = datetime.now(UTC) - timedelta(minutes=6)
    enlace_inicial: list[str] = []
    iniciar_inscripcion_propietario(
        db,
        correo=correo,
        entregar_enlace=lambda _correo, token: enlace_inicial.append(token),
        ahora=inicio,
    )
    motor = create_engine(database_url, pool_pre_ping=True)
    barrera = Barrier(2)
    nuevos_enlaces: list[str] = []
    instante_reenvio = inicio + timedelta(seconds=COOLDOWN_REENVIO_SEGUNDOS)

    def reenviar_concurrente() -> str:
        with Session(motor) as sesion:
            barrera.wait(timeout=15)
            try:
                iniciar_inscripcion_propietario(
                    sesion,
                    correo=correo,
                    entregar_enlace=lambda _correo, token: nuevos_enlaces.append(token),
                    ahora=instante_reenvio,
                )
                return "enviado"
            except ReenvioPropietarioEnEspera:
                return "en espera"

    try:
        with ThreadPoolExecutor(max_workers=2) as ejecutores:
            tareas = [ejecutores.submit(reenviar_concurrente) for _ in range(2)]
            resultados = tuple(tarea.result() for tarea in tareas)
    finally:
        motor.dispose()

    assert sorted(resultados) == ["en espera", "enviado"]
    assert len(nuevos_enlaces) == 1
    registro = db.scalar(
        select(InscripcionPropietario).where(InscripcionPropietario.correo == correo)
    )
    assert registro is not None
    assert registro.reenviados == 1
    assert registro.token_hash == hash_token_activacion(nuevos_enlaces[0])
    with pytest.raises(InscripcionPropietarioNoDisponible):
        canjear_enlace_propietario(
            db,
            token=enlace_inicial[0],
            duracion_desafio_minutos=15,
            ahora=instante_reenvio,
        )


def test_rechaza_contrasenas_iguales_y_no_consume_desafio(db: Session) -> None:
    token = iniciar(db, correo_prueba())
    token_desafio = desafio(db, token)
    contrasena = contrasena_prueba("Owner password")
    with pytest.raises(ContrasenasPropietarioIgualesError):
        completar_inscripcion_propietario(
            db,
            token_desafio=token_desafio,
            contrasena_login=contrasena,
            confirmar_contrasena_login=contrasena,
            contrasena_admin=contrasena,
            confirmar_contrasena_admin=contrasena,
            nombre="Ada",
            apellido_paterno="Lovelace",
        )
    assert obtener_tipo_cuenta_desafio(db, token_desafio=token_desafio) == "nueva"


def test_dos_activaciones_concurrentes_dejan_un_owner_y_no_cuentas_parciales(
    db: Session,
    database_url: URL,
) -> None:
    correos = [correo_prueba(), correo_prueba()]
    desafios: list[str] = []
    for correo in correos:
        desafios.append(desafio(db, iniciar(db, correo)))

    motor = create_engine(database_url, pool_pre_ping=True)
    barrera = Barrier(2)

    def activar(indice: int) -> str:
        with Session(motor) as sesion:
            try:
                barrera.wait(timeout=15)
                contrasena_login = contrasena_prueba("Login Owner")
                contrasena_admin = contrasena_prueba("Admin Owner")
                completar_inscripcion_propietario(
                    sesion,
                    token_desafio=desafios[indice],
                    contrasena_login=contrasena_login,
                    confirmar_contrasena_login=contrasena_login,
                    contrasena_admin=contrasena_admin,
                    confirmar_contrasena_admin=contrasena_admin,
                    nombre="Nombre",
                    apellido_paterno="Propietario",
                )
                return "activado"
            except InscripcionPropietarioNoDisponible:
                return "rechazado"

    with ThreadPoolExecutor(max_workers=2) as ejecutores:
        resultados = tuple(ejecutores.map(activar, range(2)))
    motor.dispose()

    assert sorted(resultados) == ["activado", "rechazado"]
    assert (
        db.scalar(
            select(func.count(Usuario.id)).where(
                Usuario.rol == RolUsuario.OWNER.value,
                Usuario.esta_activo.is_(True),
            )
        )
        == 1
    )
    assert db.scalar(select(func.count(CuentaPropietario.id))) == 1
    assert db.scalar(select(func.count(Usuario.id))) == 1


def test_api_cookie_segura_login_y_capacidades_admin_owner(
    db: Session,
    client: TestClient,
) -> None:
    correo = correo_prueba()
    token = iniciar(db, correo)
    canje = None
    for _ in range(MAXIMO_INTENTOS_POR_TOKEN + 1):
        # La misma liga se puede abrir varias veces antes de su vencimiento.
        canje = client.post(f"{RUTA_OWNER}/enlace", json={"token": token})
        assert canje.status_code == 204
    assert canje is not None
    assert canje.headers["cache-control"] == "no-store"
    assert canje.headers["referrer-policy"] == "no-referrer"
    cookie = SimpleCookie()
    cookie.load(canje.headers["set-cookie"])
    desafio_cookie = cookie[NOMBRE_COOKIE_DESAFIO]
    assert desafio_cookie["httponly"] is True
    assert desafio_cookie["samesite"].lower() == "lax"
    assert desafio_cookie["path"] == RUTA_OWNER
    assert "smart_parking_session" not in cookie

    estado = client.get(f"{RUTA_OWNER}/desafio")
    assert estado.status_code == 200
    assert estado.json()["valido"] is True
    assert estado.json()["tipo_cuenta"] == "nueva"
    assert estado.json()["nombre"] is None
    assert estado.json()["apellido_paterno"] is None
    assert estado.json()["apellido_materno"] is None
    assert estado.json()["expira_en"] is not None
    assert estado.headers["cache-control"] == "no-store"

    login = contrasena_prueba("Login Owner")
    admin = contrasena_prueba("Admin Owner")
    respuesta_sin_nombre = client.post(
        f"{RUTA_OWNER}/completar",
        json={"contrasena_login": login, "contrasena_admin": admin},
    )
    assert respuesta_sin_nombre.status_code == 422
    assert login not in respuesta_sin_nombre.text
    assert admin not in respuesta_sin_nombre.text
    secreto_corto = "secreto-login-owner-corto"
    respuesta_con_secreto_invalido = client.post(
        f"{RUTA_OWNER}/completar",
        json={
            "nombre": "Nombre",
            "apellido_paterno": "Propietario",
            "contrasena_login": secreto_corto,
            "confirmar_contrasena_login": secreto_corto,
            "contrasena_admin": admin,
            "confirmar_contrasena_admin": admin,
        },
    )
    assert respuesta_con_secreto_invalido.status_code == 422
    assert secreto_corto not in respuesta_con_secreto_invalido.text
    token_corto = "token-owner-corto-no-revelar"
    respuesta_con_token_invalido = client.post(
        f"{RUTA_OWNER}/enlace",
        json={"token": token_corto},
    )
    assert respuesta_con_token_invalido.status_code == 422
    assert token_corto not in respuesta_con_token_invalido.text
    respuesta_con_confirmacion_invalida = client.post(
        f"{RUTA_OWNER}/completar",
        json={
            "nombre": "Nombre",
            "apellido_paterno": "Propietario",
            "contrasena_login": login,
            "confirmar_contrasena_login": login,
            "contrasena_admin": admin,
            "confirmar_contrasena_admin": f"Distinta {uuid4().hex}",
        },
    )
    assert respuesta_con_confirmacion_invalida.status_code == 422
    assert login not in respuesta_con_confirmacion_invalida.text
    assert admin not in respuesta_con_confirmacion_invalida.text
    assert client.get(f"{RUTA_OWNER}/desafio").json()["valido"] is True
    respuesta = client.post(
        f"{RUTA_OWNER}/completar",
        json={
            "nombre": "Nombre",
            "apellido_paterno": "Propietario",
            "apellido_materno": "",
            "contrasena_login": login,
            "confirmar_contrasena_login": login,
            "contrasena_admin": admin,
            "confirmar_contrasena_admin": admin,
        },
    )
    assert respuesta.status_code == 200
    assert respuesta.json() == {"estado": "owner_activado"}
    assert respuesta.headers["cache-control"] == "no-store"
    assert respuesta.headers["referrer-policy"] == "no-referrer"
    assert "max-age=0" in respuesta.headers["set-cookie"].lower()

    inicio_sesion = client.post(
        "/api/autenticacion/login",
        json={"correo": correo, "contrasena": login},
    )
    assert inicio_sesion.status_code == 200
    assert inicio_sesion.json()["rol"] == RolUsuario.OWNER.value
    assert client.get("/api/autenticacion/me").json()["usuario"]["rol"] == "OWNER"
    assert (
        client.post(
            "/api/autenticacion/login",
            json={"correo": correo, "contrasena": admin},
        ).status_code
        == 401
    )


def test_enlace_expirado_y_desafio_anterior_reemplazado_denegados(db: Session) -> None:
    inicio = datetime.now(UTC)
    correo = correo_prueba()
    token = iniciar(db, correo, ahora=inicio)
    with pytest.raises(InscripcionPropietarioNoDisponible):
        canjear_enlace_propietario(
            db,
            token=token,
            duracion_desafio_minutos=15,
            ahora=inicio + timedelta(minutes=VIGENCIA_ENLACE_MINUTOS),
        )
    token = iniciar(
        db,
        correo,
        ahora=inicio + timedelta(minutes=VIGENCIA_ENLACE_MINUTOS),
    )
    desafio_anterior = desafio(
        db,
        token,
        ahora=inicio + timedelta(minutes=VIGENCIA_ENLACE_MINUTOS),
    )
    nueva_apertura = inicio + timedelta(minutes=VIGENCIA_ENLACE_MINUTOS, seconds=1)
    token_desafio = canjear_enlace_propietario(
        db,
        token=token,
        duracion_desafio_minutos=15,
        ahora=nueva_apertura,
    ).token
    assert (
        obtener_tipo_cuenta_desafio(
            db,
            token_desafio=desafio_anterior,
            ahora=nueva_apertura,
        )
        is None
    )
    assert (
        obtener_tipo_cuenta_desafio(
            db,
            token_desafio=token_desafio,
            ahora=nueva_apertura,
        )
        == "nueva"
    )
    assert (
        obtener_tipo_cuenta_desafio(
            db,
            token_desafio=token_desafio,
            ahora=inicio + timedelta(minutes=2 * VIGENCIA_ENLACE_MINUTOS),
        )
        is None
    )
