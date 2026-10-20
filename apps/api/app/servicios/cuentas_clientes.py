"""Persistencia de identidades publicas independientes de cuentas de personal."""

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import Cliente, CuentaCliente
from app.seguridad.contrasenas import crear_hash_contrasena, validar_contrasena
from app.seguridad.correos import normalizar_correo
from app.servicios.eventos_directorio_clientes import (
    registrar_evento_cliente_registrado,
)

INDICE_CORREO_CLIENTE = "uq_cuentas_clientes_correo_lower"


def registrar_cuenta_cliente(
    db: Session,
    *,
    nombre: str,
    apellido_paterno: str,
    apellido_materno: str | None,
    correo: str,
    contrasena: str,
) -> bool:
    """Inserta una cuenta y devuelve False solo ante correo duplicado."""

    validar_contrasena(contrasena)
    cuenta = CuentaCliente(
        nombre=nombre,
        apellido_paterno=apellido_paterno,
        apellido_materno=apellido_materno,
        correo=normalizar_correo(correo),
        contrasena_hash=crear_hash_contrasena(contrasena),
    )
    try:
        db.add(cuenta)
        db.flush()
        nombre_completo = " ".join(
            parte
            for parte in (nombre, apellido_paterno, apellido_materno)
            if parte
        )
        cliente = Cliente(
            cuenta_cliente_id=cuenta.id,
            nombre_completo=nombre_completo,
            correo_privado=None,
        )
        db.add(cliente)
        db.flush()
        registrar_evento_cliente_registrado(db, cliente_id=cliente.id)
        db.commit()
    except IntegrityError as error:
        db.rollback()
        diagnostico = getattr(error.orig, "diag", None)
        if getattr(diagnostico, "constraint_name", None) == INDICE_CORREO_CLIENTE:
            return False
        raise
    except SQLAlchemyError:
        db.rollback()
        raise
    return True


__all__ = ["INDICE_CORREO_CLIENTE", "registrar_cuenta_cliente"]
