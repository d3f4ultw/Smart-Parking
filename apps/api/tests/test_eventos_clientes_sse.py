from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    EstadoEventosTiempoReal,
    EventoTiempoReal,
    RolUsuario,
    Sesion,
    Usuario,
)
from app.seguridad.sesiones import hash_token_sesion
from app.servicios.eventos_directorio_clientes import (
    registrar_evento_cliente_registrado,
    registrar_evento_membresia_actualizada,
)
from app.servicios.eventos_operadores import (
    admitir_conexion_sse,
    consultar_lote_eventos_usuario,
    tipos_autorizados_para_rol,
)


def _crear_usuario_con_sesion(db: Session, rol: str) -> tuple[int, str]:
    usuario = Usuario(
        nombre="Cuenta",
        apellido_paterno="Sintetica",
        correo=f"sse-{rol.lower()}-{uuid4().hex}@example.invalid",
        contrasena_hash="hash-de-prueba-no-autenticable",
        rol=rol,
        correo_verificado=True,
        debe_cambiar_contrasena=False,
        esta_activo=True,
    )
    db.add(usuario)
    db.flush()
    token = f"token-{rol.lower()}-{uuid4().hex}"
    db.add(
        Sesion(
            usuario_id=usuario.id,
            token_hash=hash_token_sesion(token),
            expira_en=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    usuario_id = usuario.id
    db.commit()
    db.rollback()
    return usuario_id, token


def test_eventos_de_clientes_solo_se_autorizan_para_owner() -> None:
    assert tipos_autorizados_para_rol("OWNER") >= {
        "cliente.registrado",
        "membresia.actualizada",
    }
    assert "cliente.registrado" not in tipos_autorizados_para_rol("OPERADOR")
    assert "membresia.actualizada" not in tipos_autorizados_para_rol("OPERADOR")
    assert tipos_autorizados_para_rol("OPERADOR") == {"cajon.actualizado"}


def test_journal_emite_cambios_de_cliente_sin_datos_personales(
    db: Session,
) -> None:
    owner_id, token_owner = _crear_usuario_con_sesion(db, RolUsuario.OWNER.value)
    operador_id, token_operador = _crear_usuario_con_sesion(
        db,
        RolUsuario.OPERADOR.value,
    )

    registrar_evento_cliente_registrado(db, cliente_id=41)
    registrar_evento_membresia_actualizada(db, cliente_id=41)
    # Simula una fila del journal anterior al contrato de ID generico.
    db.add(
        EventoTiempoReal(
            id=3,
            recurso_tipo="cliente",
            recurso_id=41,
            tipo="cliente.registrado",
            datos={"campo_sintetico": "no_exportar"},
        )
    )
    estado = db.get(EstadoEventosTiempoReal, 1)
    assert estado is not None
    estado.ultimo_id = 3
    db.commit()
    db.rollback()

    lease_owner = admitir_conexion_sse(
        db,
        usuario_id=owner_id,
        token_sesion=token_owner,
    )
    lease_operador = admitir_conexion_sse(
        db,
        usuario_id=operador_id,
        token_sesion=token_operador,
    )
    lote_owner = consultar_lote_eventos_usuario(
        db,
        usuario_id=owner_id,
        rol_usuario=RolUsuario.OWNER.value,
        token_sesion=token_owner,
        lease_id=lease_owner,
        cursor=0,
        revalidar_sesion=True,
        renovar_conexion=False,
    )
    lote_operador = consultar_lote_eventos_usuario(
        db,
        usuario_id=operador_id,
        rol_usuario=RolUsuario.OPERADOR.value,
        token_sesion=token_operador,
        lease_id=lease_operador,
        cursor=0,
        revalidar_sesion=True,
        renovar_conexion=False,
    )

    assert [evento.tipo for evento in lote_owner.eventos] == [
        "cliente.registrado",
        "membresia.actualizada",
        "cliente.registrado",
    ]
    assert all(evento.recurso_tipo == "cliente" for evento in lote_owner.eventos)
    assert all(evento.recurso_id == 1 for evento in lote_owner.eventos)
    assert all(evento.datos is None for evento in lote_owner.eventos)
    assert lote_operador.eventos == ()
    evento_historico = db.get(EventoTiempoReal, 3)
    assert evento_historico is not None
    assert evento_historico.recurso_id == 41

    db.rollback()
    assert db.scalar(select(Usuario.id).where(Usuario.id == owner_id)) == owner_id
