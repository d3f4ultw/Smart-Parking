from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

import app.servicios.stripe_membresias as servicio_stripe
from app.api.rutas.clientes_membresias import consultar_membresia_cuenta
from app.models import (
    Cliente,
    CuentaCliente,
    FacturaMembresia,
    IntentoCheckoutCliente,
    Membresia,
)
from app.servicios.clientes_membresias import (
    IntentoCheckoutEnCursoError,
    crear_o_reusar_intento_checkout,
    formatear_codigo_cliente,
    listar_clientes,
    obtener_membresia_cuenta,
)
from app.servicios.stripe_membresias import (
    IMPORTE_MEMBRESIA_CENTAVOS,
    MONEDA_MEMBRESIA,
    NOMBRE_PRODUCTO_MEMBRESIA,
    crear_checkout_membresia,
    procesar_evento_stripe,
)


def _crear_cuenta(db: Session, marcador: str) -> CuentaCliente:
    cuenta = CuentaCliente(
        nombre="Cuenta",
        apellido_paterno=marcador,
        apellido_materno=None,
        correo=f"{marcador.lower()}-{uuid4().hex}@example.invalid",
        contrasena_hash="hash-sintetico",
        correo_verificado=False,
        esta_activa=True,
    )
    db.add(cuenta)
    db.flush()
    return cuenta


def _crear_membresia(
    db: Session,
    cuenta: CuentaCliente,
    estado: str,
    *,
    cancelar: bool = False,
) -> None:
    ahora = datetime.now(UTC)
    cliente = Cliente(
        cuenta_cliente_id=cuenta.id,
        stripe_customer_id=f"cus_{uuid4().hex}",
        nombre_completo=f"{cuenta.nombre} {cuenta.apellido_paterno}",
        correo_privado=cuenta.correo,
    )
    db.add(cliente)
    db.flush()
    db.add(
        Membresia(
            cliente_id=cliente.id,
            stripe_subscription_id=f"sub_{uuid4().hex}",
            stripe_price_id="price_testmonthly",
            nombre_plan=NOMBRE_PRODUCTO_MEMBRESIA,
            monto_centavos=IMPORTE_MEMBRESIA_CENTAVOS,
            moneda=MONEDA_MEMBRESIA,
            intervalo="month",
            intervalo_cantidad=1,
            estado_stripe=estado,
            cancelacion_programada=cancelar,
            fecha_inicio=ahora - timedelta(days=30),
            periodo_actual_inicio=ahora - timedelta(days=1),
            periodo_actual_fin=ahora + timedelta(days=29),
        )
    )


def test_intento_checkout_reutiliza_clave_y_bloquea_otras_compra_en_curso(
    db: Session,
) -> None:
    cuenta = _crear_cuenta(db, "Intento")
    db.commit()
    clave = uuid4()

    primero = crear_o_reusar_intento_checkout(
        db,
        cuenta_cliente_id=cuenta.id,
        clave_solicitud=clave,
    )
    repetido = crear_o_reusar_intento_checkout(
        db,
        cuenta_cliente_id=cuenta.id,
        clave_solicitud=clave,
    )
    assert repetido.id == primero.id
    assert repetido.stripe_idempotency_key == primero.stripe_idempotency_key
    membresia_pendiente = obtener_membresia_cuenta(
        db,
        cuenta_cliente_id=cuenta.id,
    )
    assert membresia_pendiente.checkout_pendiente is True
    assert membresia_pendiente.puede_comprar is False
    respuesta = consultar_membresia_cuenta(
        response=Response(),
        db=db,
        cuenta=cuenta,
    )
    assert respuesta.estado == "sin_membresia"
    assert respuesta.membresia is None
    assert respuesta.checkout_pendiente is True
    assert respuesta.puede_comprar is False

    with pytest.raises(IntentoCheckoutEnCursoError):
        crear_o_reusar_intento_checkout(
            db,
            cuenta_cliente_id=cuenta.id,
            clave_solicitud=uuid4(),
        )

    db.execute(
        update(IntentoCheckoutCliente)
        .where(IntentoCheckoutCliente.id == primero.id)
        .values(expira_en=datetime.now(UTC) - timedelta(seconds=1))
    )
    db.commit()
    nuevo = crear_o_reusar_intento_checkout(
        db,
        cuenta_cliente_id=cuenta.id,
        clave_solicitud=uuid4(),
    )
    assert nuevo.id != primero.id
    intento_expirado = db.get(IntentoCheckoutCliente, primero.id)
    assert intento_expirado is not None
    assert intento_expirado.estado == "expirado"


def test_directorio_filtra_categorias_y_conserva_estado_mostrado(db: Session) -> None:
    cuenta_sin_membresia = _crear_cuenta(db, "Pendiente")
    cuenta_activa = _crear_cuenta(db, "Activa")
    cuenta_vencida = _crear_cuenta(db, "Vencida")
    cuenta_inactiva = _crear_cuenta(db, "Inactiva")
    cuenta_cancelada = _crear_cuenta(db, "Cancelada")
    _crear_membresia(db, cuenta_activa, "active", cancelar=True)
    _crear_membresia(db, cuenta_vencida, "past_due")
    _crear_membresia(db, cuenta_inactiva, "unpaid")
    _crear_membresia(db, cuenta_cancelada, "canceled")
    db.commit()

    todos = listar_clientes(db, pagina=1)
    por_nombre = {
        cliente.nombre_completo.split()[-1]: cliente for cliente in todos.clientes
    }
    assert todos.total == 5
    assert por_nombre["Pendiente"].estado_membresia == "pendiente"
    assert por_nombre["Pendiente"].codigo_cliente is None
    assert por_nombre["Activa"].estado_membresia == "cancelacion_programada"
    assert por_nombre["Vencida"].estado_membresia == "pago_vencido"
    assert por_nombre["Inactiva"].estado_membresia == "inactiva"
    assert por_nombre["Cancelada"].estado_membresia == "cancelada"
    assert por_nombre["Activa"].codigo_cliente is not None
    assert por_nombre["Activa"].codigo_cliente.startswith("CLI-")
    assert not any(hasattr(cliente, "correo") for cliente in todos.clientes)

    activas = listar_clientes(db, pagina=1, estado="activa")
    sin_membresia = listar_clientes(db, pagina=1, estado="sin_membresia")
    canceladas = listar_clientes(db, pagina=1, estado="cancelada")
    assert [fila.estado_membresia for fila in activas.clientes] == [
        "cancelacion_programada"
    ]
    assert {fila.estado_membresia for fila in sin_membresia.clientes} == {
        "pendiente",
        "pago_vencido",
        "inactiva",
    }
    assert [fila.estado_membresia for fila in canceladas.clientes] == ["cancelada"]
    assert formatear_codigo_cliente(1) == "CLI-0001"

    estado_sin_membresia = obtener_membresia_cuenta(
        db,
        cuenta_cliente_id=cuenta_sin_membresia.id,
    )
    estado_activo = obtener_membresia_cuenta(db, cuenta_cliente_id=cuenta_activa.id)
    estado_vencido = obtener_membresia_cuenta(db, cuenta_cliente_id=cuenta_vencida.id)
    estado_inactivo = obtener_membresia_cuenta(db, cuenta_cliente_id=cuenta_inactiva.id)
    estado_cancelado = obtener_membresia_cuenta(
        db,
        cuenta_cliente_id=cuenta_cancelada.id,
    )
    assert estado_sin_membresia.estado == "sin_membresia"
    assert estado_sin_membresia.membresia is None
    assert estado_sin_membresia.puede_comprar is True
    assert estado_activo.puede_comprar is False
    assert estado_activo.estado == "cancelacion_programada"
    assert estado_activo.membresia is not None
    assert estado_activo.membresia.cancelacion_programada is True
    assert estado_activo.membresia.intervalo == "month"
    assert estado_activo.membresia.intervalo_cantidad == 1
    assert estado_activo.membresia.periodo_actual_inicio is not None
    assert estado_activo.membresia.periodo_actual_fin is not None
    respuesta_activa = consultar_membresia_cuenta(
        response=Response(),
        db=db,
        cuenta=cuenta_activa,
    )
    assert respuesta_activa.estado == "cancelacion_programada"
    assert respuesta_activa.membresia is not None
    assert respuesta_activa.membresia.plan == NOMBRE_PRODUCTO_MEMBRESIA
    assert respuesta_activa.membresia.monto_centavos == IMPORTE_MEMBRESIA_CENTAVOS
    assert respuesta_activa.membresia.moneda == MONEDA_MEMBRESIA
    assert respuesta_activa.membresia.intervalo == "month"
    assert respuesta_activa.membresia.intervalo_cantidad == 1
    assert respuesta_activa.membresia.periodo_actual_inicio is not None
    assert respuesta_activa.membresia.periodo_actual_fin is not None
    assert respuesta_activa.membresia.cancelacion_programada is True
    assert estado_vencido.puede_comprar is False
    assert estado_vencido.estado == "pago_vencido"
    assert estado_inactivo.puede_comprar is False
    assert estado_inactivo.estado == "inactiva"
    assert estado_cancelado.puede_comprar is True


def test_directorio_conserva_cliente_historico_sin_cuenta(db: Session) -> None:
    cliente = Cliente(
        stripe_customer_id=f"cus_historico_{uuid4().hex}",
        nombre_completo="Cliente Historico",
        correo_privado="historico@example.invalid",
    )
    db.add(cliente)
    db.flush()
    db.add(
        Membresia(
            cliente_id=cliente.id,
            stripe_subscription_id=f"sub_historico_{uuid4().hex}",
            stripe_price_id="price_testmonthly",
            nombre_plan=NOMBRE_PRODUCTO_MEMBRESIA,
            monto_centavos=IMPORTE_MEMBRESIA_CENTAVOS,
            moneda=MONEDA_MEMBRESIA,
            intervalo="month",
            intervalo_cantidad=1,
            estado_stripe="active",
        )
    )
    db.commit()

    resultado = listar_clientes(db, pagina=1)

    assert resultado.total == 1
    assert resultado.clientes[0].codigo_cliente == formatear_codigo_cliente(cliente.id)
    assert resultado.clientes[0].nombre_completo == "Cliente Historico"
    assert resultado.clientes[0].estado_membresia == "activa"


class _FakeStripeCheckout:
    def __init__(self) -> None:
        self.parametros: dict[str, object] | None = None
        self.opciones: dict[str, object] | None = None

        def recuperar_price(_price_id: str) -> dict[str, object]:
            return {
                "id": "price_testmonthly",
                "active": True,
                "unit_amount": IMPORTE_MEMBRESIA_CENTAVOS,
                "currency": MONEDA_MEMBRESIA,
                "recurring": {"interval": "month", "interval_count": 1},
                "product": {
                    "id": "prod_testmembership",
                    "name": NOMBRE_PRODUCTO_MEMBRESIA,
                },
            }

        def crear_sesion(
            params: dict[str, object],
            options: dict[str, object],
        ) -> dict[str, object]:
            self.parametros = params
            self.opciones = options
            return {
                "id": "cs_test_synthetic",
                "url": "https://checkout.stripe.com/c/pay/cs_test_synthetic",
                "livemode": False,
                "metadata": params["metadata"],
                "customer": params.get("customer"),
                "expires_at": params["expires_at"],
            }

        self.v1 = SimpleNamespace(
            prices=SimpleNamespace(retrieve=recuperar_price),
            checkout=SimpleNamespace(
                sessions=SimpleNamespace(create=crear_sesion),
            ),
        )


def test_checkout_usa_metadata_minimo_price_mensual_y_clave_durable() -> None:
    client = _FakeStripeCheckout()
    intento_id = uuid4()
    expira_en = datetime.now(UTC) + timedelta(hours=1)
    settings = SimpleNamespace(
        stripe_price_ids=("price_testmonthly", "price_ignorado"),
        app_public_url="https://parking.example",
    )

    resultado = crear_checkout_membresia(
        client,  # type: ignore[arg-type]
        settings,  # type: ignore[arg-type]
        plan_id="mensual",
        intento_id=intento_id,
        clave_idempotencia=f"stable_{intento_id.hex}",
        expira_en=expira_en,
        correo_cliente="cliente@example.invalid",
        stripe_customer_id=None,
    )

    assert client.parametros is not None
    assert client.parametros["line_items"] == [
        {"price": "price_testmonthly", "quantity": 1}
    ]
    assert client.parametros["metadata"] == {
        "intento_checkout_id": str(intento_id)
    }
    assert client.parametros["subscription_data"] == {
        "metadata": {"intento_checkout_id": str(intento_id)}
    }
    assert client.parametros["customer_email"] == "cliente@example.invalid"
    assert client.opciones == {"idempotency_key": f"stable_{intento_id.hex}"}
    assert resultado["checkout_session_id"] == "cs_test_synthetic"
    assert resultado["checkout_url"].startswith("https://checkout.stripe.com/")


class _FakeStripeWebhook:
    def __init__(self, *, intento_id: str | None) -> None:
        metadata = {"intento_checkout_id": intento_id} if intento_id else {}
        self.invoice = {
            "id": "in_test_initial",
            "status": "paid",
            "amount_paid": IMPORTE_MEMBRESIA_CENTAVOS,
            "amount_remaining": 0,
            "currency": "mxn",
            "customer": "cus_test_initial",
            "subscription": "sub_test_initial",
            "billing_reason": "subscription_create",
        }
        price = {
            "id": "price_testmonthly",
            "active": True,
            "unit_amount": IMPORTE_MEMBRESIA_CENTAVOS,
            "currency": "mxn",
            "recurring": {"interval": "month", "interval_count": 1},
            "product": {
                "id": "prod_testmembership",
                "name": NOMBRE_PRODUCTO_MEMBRESIA,
            },
        }
        self.subscription = {
            "id": "sub_test_initial",
            "customer": "cus_test_initial",
            "status": "active",
            "cancel_at_period_end": False,
            "start_date": 1_760_000_000,
            "current_period_start": 1_760_000_000,
            "current_period_end": 1_762_592_000,
            "metadata": metadata,
            "items": {
                "data": [
                    {
                        "current_period_start": 1_760_000_000,
                        "current_period_end": 1_762_592_000,
                        "price": price,
                    }
                ]
            },
        }
        self.checkout_session = {
            "id": "cs_test_initial",
            "mode": "subscription",
            "livemode": False,
            "status": "complete",
            "payment_status": "paid",
            "metadata": metadata,
            "customer": "cus_test_initial",
            "subscription": "sub_test_initial",
        }

        def recuperar_invoice(_invoice_id: str) -> dict[str, object]:
            return self.invoice

        def recuperar_subscription(*_args: object) -> dict[str, object]:
            return self.subscription

        def recuperar_price(_price_id: str) -> dict[str, object]:
            return price

        def recuperar_checkout(_session_id: str) -> dict[str, object]:
            return self.checkout_session

        self.v1 = SimpleNamespace(
            invoices=SimpleNamespace(retrieve=recuperar_invoice),
            subscriptions=SimpleNamespace(retrieve=recuperar_subscription),
            prices=SimpleNamespace(retrieve=recuperar_price),
            checkout=SimpleNamespace(
                sessions=SimpleNamespace(retrieve=recuperar_checkout),
            ),
        )


def test_webhook_solo_vincula_si_intento_checkout_y_sesion_coinciden(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cuenta = _crear_cuenta(db, "WebHook")
    intento_id = uuid4()
    intento = IntentoCheckoutCliente(
        id=intento_id,
        cuenta_cliente_id=cuenta.id,
        clave_solicitud=uuid4(),
        stripe_idempotency_key=f"stable_{intento_id.hex}",
        checkout_session_id="cs_test_initial",
        stripe_customer_id="cus_test_initial",
        estado="abierto",
        expira_en=datetime.now(UTC) + timedelta(minutes=20),
    )
    db.add(intento)
    db.commit()
    llamadas: list[int] = []

    def registrar_evento(_db: Session, *, cliente_id: int) -> None:
        assert _db.scalar(select(Membresia.id)) is not None
        llamadas.append(cliente_id)

    monkeypatch.setattr(
        servicio_stripe,
        "registrar_evento_membresia_actualizada",
        registrar_evento,
    )
    evento = {
        "id": "evt_test_initial_paid",
        "type": "invoice.paid",
        "livemode": False,
        "created": 1_760_000_000,
        "data": {"object": {"id": "in_test_initial", "status": "paid"}},
    }
    settings = SimpleNamespace(stripe_price_ids=("price_testmonthly",))

    procesar_evento_stripe(
        db,
        _FakeStripeWebhook(intento_id=str(intento_id)),  # type: ignore[arg-type]
        settings,  # type: ignore[arg-type]
        evento=evento,
    )

    cliente = db.scalar(select(Cliente).where(Cliente.cuenta_cliente_id == cuenta.id))
    intento_guardado = db.get(IntentoCheckoutCliente, intento_id)
    assert cliente is not None
    assert cliente.stripe_customer_id == "cus_test_initial"
    assert db.scalar(select(Membresia).where(Membresia.cliente_id == cliente.id))
    assert intento_guardado is not None and intento_guardado.estado == "confirmado"
    assert intento_guardado.stripe_subscription_id == "sub_test_initial"
    assert llamadas == [cliente.id]
    assert db.scalar(select(FacturaMembresia.stripe_invoice_id)) == "in_test_initial"


def test_webhook_historico_sin_intento_guarda_factura_sin_vincular_cliente(
    db: Session,
) -> None:
    evento = {
        "id": "evt_test_historical_paid",
        "type": "invoice.paid",
        "livemode": False,
        "created": 1_760_000_000,
        "data": {"object": {"id": "in_test_initial", "status": "paid"}},
    }
    settings = SimpleNamespace(stripe_price_ids=("price_testmonthly",))

    procesar_evento_stripe(
        db,
        _FakeStripeWebhook(intento_id=None),  # type: ignore[arg-type]
        settings,  # type: ignore[arg-type]
        evento=evento,
    )

    assert db.scalar(select(Cliente.id)) is None
    assert db.scalar(select(Membresia.id)) is None
    factura = db.scalar(select(FacturaMembresia))
    assert factura is not None
    assert factura.membresia_id is None
    assert factura.estado == "paid"
