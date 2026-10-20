from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

import app.api.dependencias as dependencias
import app.api.rutas.clientes_membresias as rutas_clientes
import app.api.rutas.eventos as rutas_eventos
import app.api.rutas.stripe_webhook as rutas_webhook
import main
from app.core.config import Settings
from app.core.database import get_db
from app.models import (
    Cliente,
    CuentaCliente,
    EventoStripe,
    FacturaMembresia,
    IntentoCheckoutCliente,
    Membresia,
    RolUsuario,
    Sesion,
    SesionCliente,
    Usuario,
)
from app.seguridad.sesiones import hash_token_sesion
from app.servicios.autorizacion_clientes import (
    AccionClienteMembresia,
    usuario_tiene_accion_cliente,
)
from app.servicios.clientes_membresias import (
    formatear_codigo_cliente,
    listar_clientes,
    obtener_detalle_membresia,
)
from app.servicios.configuracion_estacionamiento import (
    cambiar_modalidad_estacionamiento,
)
from app.servicios.stripe_membresias import (
    IMPORTE_MEMBRESIA_CENTAVOS,
    MONEDA_MEMBRESIA,
    NOMBRE_PRODUCTO_MEMBRESIA,
    mapear_estado_membresia,
)

NOMBRE_COOKIE_SESION = "smart_parking_session"


def crear_settings(
    *,
    webhook_secret: str | None = "whsec_test_synthetic",
) -> Settings:
    valores: dict[str, object] = {
        "database_host": "localhost",
        "database_port": 5432,
        "database_name": "smart_parking_test",
        "database_user": "smart_parking_test",
        "database_password": SecretStr("database-secret-test-only"),
        "activation_token_ttl_hours": 24,
        "activation_challenge_ttl_minutes": 15,
        "correo_transporte": "smtp",
        "smtp_host": "mailpit",
        "smtp_port": "1025",
        "smtp_from_email": "no-reply@example.test",
        "smtp_security": "none",
        "stripe_api_key": SecretStr("sk_test_synthetic"),
        "stripe_webhook_secret": (
            SecretStr(webhook_secret) if webhook_secret is not None else None
        ),
        "stripe_membership_price_ids": "price_testmonthly",
        "app_public_url": "http://localhost:3000",
    }
    return Settings.model_validate(valores)


@pytest.fixture
def client(
    database_url: URL,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[TestClient]:
    motor = create_engine(database_url, pool_pre_ping=True)
    fabrica = sessionmaker(bind=motor, autoflush=False, expire_on_commit=False)
    settings = crear_settings()

    def entregar_db() -> Generator[Session]:
        sesion = fabrica()
        try:
            yield sesion
        finally:
            sesion.close()

    main.app.dependency_overrides[get_db] = entregar_db
    monkeypatch.setattr(dependencias, "get_settings", lambda: settings)
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    monkeypatch.setattr(rutas_eventos, "SessionLocal", fabrica)
    try:
        with TestClient(main.app) as test_client:
            yield test_client
    finally:
        main.app.dependency_overrides.pop(get_db, None)
        motor.dispose()


def crear_usuario(db: Session, rol: str) -> tuple[int, str]:
    usuario = Usuario(
        nombre="Prueba",
        apellido_paterno="Membresias",
        apellido_materno="Sinteticas",
        correo=f"membresia-{uuid4().hex}@example.invalid",
        contrasena_hash="hash-sintetico-membresias",
        rol=rol,
        correo_verificado=True,
        debe_cambiar_contrasena=False,
        esta_activo=True,
    )
    db.add(usuario)
    db.flush()
    token = secrets.token_urlsafe(32)
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


def crear_sesion_cliente(db: Session) -> str:
    cuenta = CuentaCliente(
        nombre="Prueba",
        apellido_paterno="Membresias",
        apellido_materno="Cliente",
        correo=f"cliente-{uuid4().hex}@example.invalid",
        contrasena_hash="hash-sintetico-membresias",
    )
    db.add(cuenta)
    db.flush()
    token = secrets.token_urlsafe(32)
    db.add(
        SesionCliente(
            cuenta_cliente_id=cuenta.id,
            token_hash=hash_token_sesion(token),
            expira_en=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    db.commit()
    return token


def crear_price() -> dict[str, object]:
    return {
        "id": "price_testmonthly",
        "active": True,
        "unit_amount": IMPORTE_MEMBRESIA_CENTAVOS,
        "currency": MONEDA_MEMBRESIA,
        "recurring": {"interval": "month", "interval_count": 1},
        "product": {"id": "prod_test_membership", "name": NOMBRE_PRODUCTO_MEMBRESIA},
    }


class FakeStripeService:
    def __init__(self, respuestas: dict[str, dict[str, object]] | None = None) -> None:
        self.respuestas = respuestas or {}
        self.params_checkout: dict[str, object] | None = None
        self.opciones_checkout: dict[str, object] | None = None

        def recuperar_price(_price_id: str, *_args: object) -> dict[str, object]:
            return crear_price()

        def recuperar_producto(_product_id: str, *_args: object) -> dict[str, object]:
            return {"id": "prod_test_membership", "name": NOMBRE_PRODUCTO_MEMBRESIA}

        def recuperar_invoice(invoice_id: str, *_args: object) -> dict[str, object]:
            return self.respuestas.get(
                invoice_id,
                {
                    "id": invoice_id,
                    "status": "paid",
                    "amount_paid": IMPORTE_MEMBRESIA_CENTAVOS,
                    "amount_remaining": 0,
                    "currency": "mxn",
                    "customer": "cus_test_1",
                    "subscription": "sub_test_1",
                    "billing_reason": "subscription_create",
                },
            )

        def recuperar_subscription(
            subscription_id: str,
            *_args: object,
        ) -> dict[str, object]:
            estado = self.respuestas.get("subscription_status", {}).get(
                "status",
                "active",
            )
            cancelar = self.respuestas.get("subscription_status", {}).get(
                "cancel_at_period_end",
                False,
            )
            return {
                "id": subscription_id,
                "customer": "cus_test_1",
                "status": estado,
                "cancel_at_period_end": cancelar,
                "start_date": 1_760_000_000,
                "current_period_start": 1_760_000_000,
                "current_period_end": 1_762_592_000,
                "items": {
                    "data": [
                        {
                            "current_period_start": 1_760_000_000,
                            "current_period_end": 1_762_592_000,
                            "price": crear_price(),
                        }
                    ]
                },
            }

        def recuperar_customer(_customer_id: str, *_args: object) -> dict[str, object]:
            return {
                "id": "cus_test_1",
                "name": "Cliente Prueba Sintetica",
                "email": "privado@example.invalid",
            }

        def crear_checkout(
            params: dict[str, object],
            options: dict[str, object],
        ) -> dict[str, object]:
            self.params_checkout = params
            self.opciones_checkout = options
            return {
                "id": "cs_test_synthetic",
                "url": "https://checkout.stripe.com/c/pay/cs_test_synthetic",
                "livemode": False,
                "metadata": params["metadata"],
                "expires_at": params["expires_at"],
            }

        self.v1 = SimpleNamespace(
            prices=SimpleNamespace(retrieve=recuperar_price),
            products=SimpleNamespace(retrieve=recuperar_producto),
            invoices=SimpleNamespace(retrieve=recuperar_invoice),
            subscriptions=SimpleNamespace(retrieve=recuperar_subscription),
            customers=SimpleNamespace(retrieve=recuperar_customer),
            checkout=SimpleNamespace(
                sessions=SimpleNamespace(create=crear_checkout),
            ),
        )


def crear_evento(
    tipo: str,
    *,
    evento_id: str = "evt_test_membership_1",
    objeto_id: str = "in_test_1",
    livemode: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=evento_id,
        type=tipo,
        livemode=livemode,
        created=1_760_000_000,
        data=SimpleNamespace(object=SimpleNamespace(id=objeto_id, status="paid")),
    )


def instalar_evento_webhook(
    monkeypatch: pytest.MonkeyPatch,
    *,
    evento: SimpleNamespace,
    settings: Settings,
    stripe_client: FakeStripeService,
    fabrica: sessionmaker[Session],
) -> None:
    monkeypatch.setattr(rutas_webhook, "get_settings", lambda: settings)
    monkeypatch.setattr(
        rutas_webhook,
        "crear_cliente_stripe",
        lambda _settings: stripe_client,
    )
    monkeypatch.setattr(rutas_webhook, "SessionLocal", fabrica)
    monkeypatch.setattr(
        rutas_webhook.stripe.Webhook,
        "construct_event",
        staticmethod(lambda _payload, _signature, _secret: evento),
    )


def test_codigo_cliente_y_mapeo_de_estados_son_estables() -> None:
    assert formatear_codigo_cliente(1) == "CLI-0001"
    assert formatear_codigo_cliente(10_000) == "CLI-10000"
    assert mapear_estado_membresia("active", False) == "activa"
    assert mapear_estado_membresia("active", True) == "cancelacion_programada"
    assert mapear_estado_membresia("past_due", False) == "pago_vencido"
    assert mapear_estado_membresia("canceled", False) == "cancelada"
    assert mapear_estado_membresia("paused", False) == "inactiva"


def test_configuracion_solo_acepta_claves_de_prueba_y_tres_prices() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(
            {
                "database_host": "localhost",
                "database_port": 5432,
                "database_name": "test",
                "database_user": "test",
                "database_password": "test",
                "activation_token_ttl_hours": 24,
                "activation_challenge_ttl_minutes": 15,
                "stripe_api_key": "clave-live-ficticia",
            }
        )
    with pytest.raises(ValidationError):
        Settings.model_validate(
            {
                "database_host": "localhost",
                "database_port": 5432,
                "database_name": "test",
                "database_user": "test",
                "database_password": "test",
                "activation_token_ttl_hours": 24,
                "activation_challenge_ttl_minutes": 15,
                "stripe_membership_price_ids": ",".join(
                    ["price_one", "price_two", "price_three", "price_four"]
                ),
            }
        )


def test_acceso_administrativo_es_por_accion_y_por_rol(db: Session) -> None:
    owner = Usuario(
        nombre="Owner",
        apellido_paterno="Prueba",
        correo=f"owner-{uuid4().hex}@example.invalid",
        contrasena_hash="hash",
        rol=RolUsuario.OWNER.value,
        correo_verificado=True,
        esta_activo=True,
    )
    operador = Usuario(
        nombre="Operador",
        apellido_paterno="Prueba",
        correo=f"operator-{uuid4().hex}@example.invalid",
        contrasena_hash="hash",
        rol=RolUsuario.OPERADOR.value,
        correo_verificado=True,
        esta_activo=True,
    )
    db.add_all([owner, operador])
    db.flush()
    assert usuario_tiene_accion_cliente(
        db,
        usuario_id=owner.id,
        accion=AccionClienteMembresia.LEER,
    )
    assert usuario_tiene_accion_cliente(
        db,
        usuario_id=owner.id,
        accion=AccionClienteMembresia.DETALLE,
    )
    assert not usuario_tiene_accion_cliente(
        db,
        usuario_id=operador.id,
        accion=AccionClienteMembresia.LEER,
    )
    assert not usuario_tiene_accion_cliente(
        db,
        usuario_id=operador.id,
        accion=AccionClienteMembresia.DETALLE,
    )


def test_owner_ve_clientes_sin_correo_ni_ids_stripe(
    db: Session,
    client: TestClient,
) -> None:
    owner_id, token_owner = crear_usuario(db, RolUsuario.OWNER.value)
    operator_id, token_operator = crear_usuario(db, RolUsuario.OPERADOR.value)
    cliente = Cliente(
        stripe_customer_id="cus_private_test",
        nombre_completo="Nombre Completo de Prueba",
        correo_privado="private@example.invalid",
    )
    db.add(cliente)
    db.flush()
    membresia = Membresia(
        cliente_id=cliente.id,
        stripe_subscription_id="sub_private_test",
        stripe_price_id="price_private_test",
        nombre_plan=NOMBRE_PRODUCTO_MEMBRESIA,
        monto_centavos=IMPORTE_MEMBRESIA_CENTAVOS,
        moneda="mxn",
        intervalo="month",
        intervalo_cantidad=1,
        estado_stripe="active",
        fecha_inicio=datetime.now(UTC),
        periodo_actual_fin=datetime.now(UTC) + timedelta(days=30),
    )
    db.add(membresia)
    db.commit()
    codigo_cliente = formatear_codigo_cliente(cliente.id)

    client.cookies.set(NOMBRE_COOKIE_SESION, token_owner)
    lista = client.get("/api/admin/clientes")
    assert lista.status_code == 200
    assert lista.headers["cache-control"] == "no-store"
    respuesta_lista = lista.json()
    assert respuesta_lista["clientes"][0]["codigo_cliente"] == codigo_cliente
    assert (
        respuesta_lista["clientes"][0]["nombre_completo"]
        == "Nombre Completo de Prueba"
    )
    assert respuesta_lista["clientes"][0]["estado_membresia"] == "activa"
    assert "correo_privado" not in lista.text
    assert "private@example.invalid" not in lista.text
    assert "cus_private_test" not in lista.text
    assert "sub_private_test" not in lista.text
    assert "price_private_test" not in lista.text

    detalle = client.get(f"/api/admin/clientes/{codigo_cliente}")
    assert detalle.status_code == 200
    assert detalle.json()["plan"] == NOMBRE_PRODUCTO_MEMBRESIA
    assert detalle.json()["monto_centavos"] == 39_900
    assert "correo_privado" not in detalle.text
    assert "stripe_" not in detalle.text

    client.cookies.set(NOMBRE_COOKIE_SESION, token_operator)
    assert client.get("/api/admin/clientes").status_code == 403
    assert client.get(f"/api/admin/clientes/{codigo_cliente}").status_code == 403
    client.cookies.delete(NOMBRE_COOKIE_SESION)
    assert client.get("/api/admin/clientes").status_code == 401


def test_lista_y_detalle_muestran_una_membresia_vigente_por_cliente(
    db: Session,
) -> None:
    ahora = datetime.now(UTC)
    cliente = Cliente(
        stripe_customer_id="cus_membership_selection",
        nombre_completo="Cliente con renovacion vigente",
    )
    db.add(cliente)
    db.flush()
    db.add_all(
        [
            Membresia(
                cliente_id=cliente.id,
                stripe_subscription_id="sub_current_membership",
                stripe_price_id="price_testmonthly",
                nombre_plan=NOMBRE_PRODUCTO_MEMBRESIA,
                monto_centavos=IMPORTE_MEMBRESIA_CENTAVOS,
                moneda=MONEDA_MEMBRESIA,
                intervalo="month",
                intervalo_cantidad=1,
                estado_stripe="active",
                fecha_inicio=ahora - timedelta(days=30),
                periodo_actual_fin=ahora + timedelta(days=30),
                creada_en=ahora - timedelta(days=30),
            ),
            Membresia(
                cliente_id=cliente.id,
                stripe_subscription_id="sub_canceled_history",
                stripe_price_id="price_testmonthly",
                nombre_plan=NOMBRE_PRODUCTO_MEMBRESIA,
                monto_centavos=IMPORTE_MEMBRESIA_CENTAVOS,
                moneda=MONEDA_MEMBRESIA,
                intervalo="month",
                intervalo_cantidad=1,
                estado_stripe="canceled",
                fecha_inicio=ahora - timedelta(days=5),
                cancelada_en=ahora,
                creada_en=ahora,
            ),
        ]
    )
    db.commit()

    codigo_cliente = formatear_codigo_cliente(cliente.id)
    pagina = listar_clientes(db, pagina=1)
    detalle = obtener_detalle_membresia(db, codigo_cliente=codigo_cliente)

    assert pagina.total == 1
    assert len(pagina.clientes) == 1
    assert pagina.clientes[0].codigo_cliente == codigo_cliente
    assert pagina.clientes[0].estado_membresia == "activa"
    assert detalle.codigo_cliente == codigo_cliente
    assert detalle.estado == "activa"


def test_checkout_usa_solo_price_configurado_y_clave_idempotente(
    db: Session,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cambiar_modalidad_estacionamiento(db, "PUBLICO", revision_esperada=0)
    token_sesion = crear_sesion_cliente(db)
    settings = crear_settings(webhook_secret=None)
    stripe_client = FakeStripeService()
    monkeypatch.setattr(rutas_clientes, "get_settings", lambda: settings)
    monkeypatch.setattr(
        rutas_clientes,
        "crear_cliente_stripe",
        lambda _settings: stripe_client,
    )
    client.cookies.set("smart_parking_customer_session", token_sesion)
    clave = uuid4()
    no_price = client.post(
        "/api/membresias/checkout",
        headers={
            "Idempotency-Key": str(clave),
            "Origin": "http://localhost:3000",
        },
        json={"plan_id": "mensual", "price_id": "price_inventado"},
    )
    assert no_price.status_code == 422

    respuesta = client.post(
        "/api/membresias/checkout",
        headers={
            "Idempotency-Key": str(clave),
            "Origin": "http://localhost:3000",
        },
        json={"plan_id": "mensual"},
    )
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "checkout_url": "https://checkout.stripe.com/c/pay/cs_test_synthetic"
    }
    assert stripe_client.params_checkout is not None
    assert stripe_client.params_checkout["mode"] == "subscription"
    assert stripe_client.params_checkout["line_items"] == [
        {"price": "price_testmonthly", "quantity": 1}
    ]
    intento = db.scalar(select(IntentoCheckoutCliente))
    assert intento is not None
    assert intento.clave_solicitud == clave
    assert intento.stripe_idempotency_key.startswith("sp_checkout_cliente_")
    assert stripe_client.opciones_checkout == {
        "idempotency_key": intento.stripe_idempotency_key
    }
    assert intento.checkout_session_id == "cs_test_synthetic"
    assert "price_testmonthly" not in respuesta.text


def test_webhook_pago_historico_sin_intento_no_vincula_cuenta(
    db: Session,
    database_url: URL,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    motor = create_engine(database_url, pool_pre_ping=True)
    fabrica = sessionmaker(bind=motor, autoflush=False, expire_on_commit=False)
    settings = crear_settings()
    stripe_client = FakeStripeService()
    evento = crear_evento("invoice.paid")
    instalar_evento_webhook(
        monkeypatch,
        evento=evento,
        settings=settings,
        stripe_client=stripe_client,
        fabrica=fabrica,
    )
    try:
        primera = client.post(
            "/api/stripe/webhook",
            headers={"Stripe-Signature": "firma-valida-sintetica"},
            content=b"{\"synthetic\":true}",
        )
        repetida = client.post(
            "/api/stripe/webhook",
            headers={"Stripe-Signature": "firma-valida-sintetica"},
            content=b"{\"synthetic\":true}",
        )
        assert primera.status_code == 200
        assert repetida.status_code == 200
        with fabrica() as db:
            assert db.scalar(select(func.count()).select_from(Cliente)) == 0
            assert db.scalar(select(func.count()).select_from(Membresia)) == 0
            facturas = list(db.scalars(select(FacturaMembresia)))
            assert len(facturas) == 1
            assert facturas[0].membresia_id is None
            assert db.scalar(select(func.count()).select_from(EventoStripe)) == 1
    finally:
        motor.dispose()


def test_webhook_fallo_actualiza_estado_y_conserva_historial(
    db: Session,
    database_url: URL,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cliente = Cliente(
        stripe_customer_id="cus_test_1",
        nombre_completo="Cliente Recurrente",
        correo_privado="privado@example.invalid",
    )
    db.add(cliente)
    db.flush()
    membresia = Membresia(
        cliente_id=cliente.id,
        stripe_subscription_id="sub_test_1",
        stripe_price_id="price_testmonthly",
        nombre_plan=NOMBRE_PRODUCTO_MEMBRESIA,
        monto_centavos=39_900,
        moneda="mxn",
        intervalo="month",
        intervalo_cantidad=1,
        estado_stripe="active",
        periodo_actual_fin=datetime.now(UTC) + timedelta(days=30),
    )
    db.add(membresia)
    db.commit()

    motor = create_engine(database_url, pool_pre_ping=True)
    fabrica = sessionmaker(bind=motor, autoflush=False, expire_on_commit=False)
    stripe_client = FakeStripeService(
        {
            "in_failed_1": {
                "id": "in_failed_1",
                "status": "open",
                "amount_paid": 0,
                "amount_remaining": 39_900,
                "currency": "mxn",
                "customer": "cus_test_1",
                "subscription": "sub_test_1",
                "billing_reason": "subscription_cycle",
            },
            "subscription_status": {"status": "past_due"},
        }
    )
    evento = crear_evento(
        "invoice.payment_failed",
        evento_id="evt_test_payment_failed",
        objeto_id="in_failed_1",
    )
    instalar_evento_webhook(
        monkeypatch,
        evento=evento,
        settings=crear_settings(),
        stripe_client=stripe_client,
        fabrica=fabrica,
    )
    try:
        respuesta = client.post(
            "/api/stripe/webhook",
            headers={"Stripe-Signature": "firma-valida-sintetica"},
            content=b"{\"synthetic\":true}",
        )
        assert respuesta.status_code == 200
        with fabrica() as consulta:
            actualizada = consulta.scalar(
                select(Membresia).where(
                    Membresia.stripe_subscription_id == "sub_test_1"
                )
            )
            factura = consulta.scalar(
                select(FacturaMembresia).where(
                    FacturaMembresia.stripe_invoice_id == "in_failed_1"
                )
            )
            assert actualizada is not None and actualizada.estado_stripe == "past_due"
            assert factura is not None and factura.estado == "open"
            assert factura.ultimo_fallo_en is not None
    finally:
        motor.dispose()


def test_webhook_renovacion_y_cancelaciones_conservan_historial(
    db: Session,
    database_url: URL,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cliente = Cliente(
        stripe_customer_id="cus_test_1",
        nombre_completo="Cliente Recurrente",
        correo_privado="privado@example.invalid",
    )
    db.add(cliente)
    db.flush()
    membresia = Membresia(
        cliente_id=cliente.id,
        stripe_subscription_id="sub_test_1",
        stripe_price_id="price_testmonthly",
        nombre_plan=NOMBRE_PRODUCTO_MEMBRESIA,
        monto_centavos=39_900,
        moneda="mxn",
        intervalo="month",
        intervalo_cantidad=1,
        estado_stripe="active",
        periodo_actual_fin=datetime.now(UTC) + timedelta(days=30),
    )
    db.add(membresia)
    db.flush()
    db.add(
        FacturaMembresia(
            membresia_id=membresia.id,
            stripe_invoice_id="in_initial_paid",
            stripe_customer_id="cus_test_1",
            stripe_subscription_id="sub_test_1",
            estado="paid",
            motivo_cobro="subscription_create",
            monto_pagado=39_900,
            monto_pendiente=0,
            moneda="mxn",
        )
    )
    db.commit()

    motor = create_engine(database_url, pool_pre_ping=True)
    fabrica = sessionmaker(bind=motor, autoflush=False, expire_on_commit=False)
    stripe_client = FakeStripeService(
        {"subscription_status": {"status": "active"}}
    )
    settings = crear_settings()
    eventos = [
        crear_evento(
            "invoice.paid",
            evento_id="evt_renewal_paid",
            objeto_id="in_renewal_paid",
        ),
        crear_evento(
            "customer.subscription.updated",
            evento_id="evt_cancel_scheduled",
            objeto_id="sub_test_1",
        ),
        crear_evento(
            "customer.subscription.deleted",
            evento_id="evt_cancel_completed",
            objeto_id="sub_test_1",
        ),
    ]
    try:
        stripe_client.respuestas["subscription_status"] = {
            "status": "active",
            "cancel_at_period_end": False,
        }
        instalar_evento_webhook(
            monkeypatch,
            evento=eventos[0],
            settings=settings,
            stripe_client=stripe_client,
            fabrica=fabrica,
        )
        renovacion = client.post(
            "/api/stripe/webhook",
            headers={"Stripe-Signature": "firma-valida-sintetica"},
            content=b"{\"synthetic\":true}",
        )
        assert renovacion.status_code == 200

        stripe_client.respuestas["subscription_status"] = {
            "status": "active",
            "cancel_at_period_end": True,
        }
        instalar_evento_webhook(
            monkeypatch,
            evento=eventos[1],
            settings=settings,
            stripe_client=stripe_client,
            fabrica=fabrica,
        )
        cancelacion_programada = client.post(
            "/api/stripe/webhook",
            headers={"Stripe-Signature": "firma-valida-sintetica"},
            content=b"{\"synthetic\":true}",
        )
        assert cancelacion_programada.status_code == 200
        with fabrica() as consulta:
            programada = consulta.scalar(
                select(Membresia).where(
                    Membresia.stripe_subscription_id == "sub_test_1"
                )
            )
            assert programada is not None
            assert programada.estado_stripe == "active"
            assert programada.cancelacion_programada is True

        stripe_client.respuestas["subscription_status"] = {
            "status": "canceled",
            "cancel_at_period_end": False,
        }
        instalar_evento_webhook(
            monkeypatch,
            evento=eventos[2],
            settings=settings,
            stripe_client=stripe_client,
            fabrica=fabrica,
        )
        cancelacion_completada = client.post(
            "/api/stripe/webhook",
            headers={"Stripe-Signature": "firma-valida-sintetica"},
            content=b"{\"synthetic\":true}",
        )
        assert cancelacion_completada.status_code == 200

        with fabrica() as consulta:
            actualizada = consulta.scalar(
                select(Membresia).where(
                    Membresia.stripe_subscription_id == "sub_test_1"
                )
            )
            assert actualizada is not None
            assert actualizada.estado_stripe == "canceled"
            assert actualizada.cancelacion_programada is False
            assert (
                consulta.scalar(select(func.count()).select_from(FacturaMembresia))
                == 2
            )
            assert (
                consulta.scalar(select(func.count()).select_from(EventoStripe)) == 3
            )
    finally:
        motor.dispose()


def test_webhook_rechaza_firma_invalida_y_evento_live_sin_escrituras(
    database_url: URL,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = crear_settings()
    monkeypatch.setattr(rutas_webhook, "get_settings", lambda: settings)
    timestamp = str(int(time.time()))
    payload = b"{\"id\":\"evt_invalid_signature\"}"
    firma = hmac.new(
        b"test_synthetic",
        f"{timestamp}.".encode() + payload,
        hashlib.sha256,
    ).hexdigest()
    respuesta_firma = client.post(
        "/api/stripe/webhook",
        headers={"Stripe-Signature": f"t={timestamp},v1={firma}"},
        content=payload,
    )
    assert respuesta_firma.status_code == 400

    motor = create_engine(database_url, pool_pre_ping=True)
    fabrica = sessionmaker(bind=motor, autoflush=False, expire_on_commit=False)
    evento_live = crear_evento(
        "invoice.paid",
        evento_id="evt_live_rejected",
        livemode=True,
    )
    instalar_evento_webhook(
        monkeypatch,
        evento=evento_live,
        settings=settings,
        stripe_client=FakeStripeService(),
        fabrica=fabrica,
    )
    try:
        respuesta_live = client.post(
            "/api/stripe/webhook",
            headers={"Stripe-Signature": "firma-valida-sintetica"},
            content=b"{\"synthetic\":true}",
        )
        assert respuesta_live.status_code == 400
        with fabrica() as consulta:
            assert consulta.scalar(select(func.count()).select_from(Cliente)) == 0
            assert consulta.scalar(select(func.count()).select_from(EventoStripe)) == 0
    finally:
        motor.dispose()
