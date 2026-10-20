"""Checkout y sincronizacion transaccional de Stripe Billing en Sandbox."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import UUID

import stripe
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import (
    Cliente,
    ConfiguracionEstacionamiento,
    CuentaCliente,
    EventoStripe,
    FacturaMembresia,
    IntentoCheckoutCliente,
    Membresia,
)
from app.servicios.eventos_directorio_clientes import (
    registrar_evento_membresia_actualizada,
)

NOMBRE_PRODUCTO_MEMBRESIA = "Smart Parking - Membresía Mensual"
IMPORTE_MEMBRESIA_CENTAVOS = 39_900
MONEDA_MEMBRESIA = "mxn"
EVENTOS_STRIPE_MEMBRESIA = frozenset(
    {
        "invoice.paid",
        "invoice.payment_failed",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    }
)
ESTADOS_STRIPE_MEMBRESIA = frozenset(
    {
        "incomplete",
        "incomplete_expired",
        "trialing",
        "active",
        "past_due",
        "canceled",
        "unpaid",
        "paused",
    }
)


class StripeMembresiasError(RuntimeError):
    """Error de dominio seguro para traducir fallos sin mostrar datos de Stripe."""


class StripeNoConfiguradoError(StripeMembresiasError):
    """Indica que faltan secretos o Price IDs de Sandbox en el proceso."""


class MembresiasNoDisponiblesError(StripeMembresiasError):
    """Indica que la modalidad vigente no permite vender membresias."""


def crear_cliente_stripe(settings: Settings) -> stripe.StripeClient:
    """Construye un cliente aislado con una clave sk_test y limites acotados."""

    if settings.stripe_api_key is None:
        raise StripeNoConfiguradoError
    return stripe.StripeClient(
        settings.stripe_api_key.get_secret_value(),
        max_network_retries=1,
        http_client=stripe.RequestsClient(timeout=8),
    )


def exigir_membresias_disponibles(db: Session) -> None:
    """Permite compra solo en PUBLICO o MIXTO sin alterar el catalogo tecnico."""

    configuracion = db.get(ConfiguracionEstacionamiento, 1)
    if configuracion is None or configuracion.modalidad not in {"PUBLICO", "MIXTO"}:
        raise MembresiasNoDisponiblesError


def _valor(objeto: Any, clave: str, defecto: Any = None) -> Any:
    if isinstance(objeto, dict):
        return objeto.get(clave, defecto)
    return getattr(objeto, clave, defecto)


def _id_stripe(valor: Any) -> str | None:
    if isinstance(valor, str):
        return valor
    identificador = _valor(valor, "id")
    return identificador if isinstance(identificador, str) else None


def _fecha_stripe(valor: Any) -> datetime | None:
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        return datetime.fromtimestamp(valor, tz=UTC)
    return None


def _obtener_producto(
    client: stripe.StripeClient,
    producto: Any,
) -> Any:
    if isinstance(producto, dict) or hasattr(producto, "id"):
        return producto
    producto_id = _id_stripe(producto)
    if producto_id is None:
        raise StripeMembresiasError
    return client.v1.products.retrieve(producto_id)


def _validar_price_mensual(
    client: stripe.StripeClient,
    price_id: str,
) -> tuple[Any, Any]:
    """Confirma que el Price configurado siga siendo el plan autorizado."""

    price = client.v1.prices.retrieve(price_id)
    recurring = _valor(price, "recurring")
    product = _obtener_producto(client, _valor(price, "product"))
    if (
        _valor(price, "active") is not True
        or _valor(price, "unit_amount") != IMPORTE_MEMBRESIA_CENTAVOS
        or _valor(price, "currency") != MONEDA_MEMBRESIA
        or _valor(recurring, "interval") != "month"
        or _valor(recurring, "interval_count") != 1
        or _valor(product, "name") != NOMBRE_PRODUCTO_MEMBRESIA
    ):
        raise StripeMembresiasError
    return price, product


def listar_planes_membresia(
    client: stripe.StripeClient,
    settings: Settings,
) -> list[dict[str, Any]]:
    """Devuelve datos visibles sin incluir el Price ID servidor."""

    if not settings.stripe_price_ids:
        raise StripeNoConfiguradoError
    price, product = _validar_price_mensual(client, settings.stripe_price_ids[0])
    return [
        {
            "plan_id": "mensual",
            "nombre": _valor(product, "name"),
            "monto_centavos": _valor(price, "unit_amount"),
            "moneda": _valor(price, "currency"),
            "intervalo": _valor(_valor(price, "recurring"), "interval"),
            "intervalo_cantidad": _valor(
                _valor(price, "recurring"),
                "interval_count",
            ),
        }
    ]


def _base_publica(settings: Settings) -> str:
    partes = urlsplit(settings.app_public_url)
    if (
        partes.scheme not in {"http", "https"}
        or not partes.netloc
        or partes.username is not None
        or partes.password is not None
        or partes.query
        or partes.fragment
    ):
        raise StripeNoConfiguradoError
    return settings.app_public_url.rstrip("/")


def crear_checkout_membresia(
    client: stripe.StripeClient,
    settings: Settings,
    *,
    plan_id: str,
    intento_id: UUID,
    clave_idempotencia: str,
    expira_en: datetime,
    correo_cliente: str,
    stripe_customer_id: str | None,
) -> dict[str, Any]:
    """Crea Checkout ligado al intento local con metadata de servidor."""

    if plan_id != "mensual" or not settings.stripe_price_ids:
        raise StripeNoConfiguradoError
    price_id = settings.stripe_price_ids[0]
    _validar_price_mensual(client, price_id)
    base = _base_publica(settings)
    metadata = {"intento_checkout_id": str(intento_id)}
    parametros: dict[str, Any] = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": (
            f"{base}/membresias/resultado?session_id={{CHECKOUT_SESSION_ID}}"
        ),
        "cancel_url": f"{base}/membresias/resultado?estado=cancelado",
        "expires_at": int(expira_en.timestamp()),
        "metadata": metadata,
        "subscription_data": {"metadata": metadata},
    }
    if stripe_customer_id is not None:
        parametros["customer"] = stripe_customer_id
    else:
        parametros["customer_email"] = correo_cliente
    sesion = client.v1.checkout.sessions.create(
        cast(Any, parametros),
        {"idempotency_key": clave_idempotencia},
    )
    url = _valor(sesion, "url")
    parsed = urlsplit(url if isinstance(url, str) else "")
    checkout_session_id = _id_stripe(_valor(sesion, "id"))
    if (
        parsed.scheme != "https"
        or parsed.hostname != "checkout.stripe.com"
        or checkout_session_id is None
        or not checkout_session_id.startswith("cs_test_")
        or _valor(sesion, "livemode", False) is not False
        or _valor(_valor(sesion, "metadata"), "intento_checkout_id")
        not in {None, str(intento_id)}
    ):
        raise StripeMembresiasError
    expiracion_stripe = _fecha_stripe(_valor(sesion, "expires_at")) or expira_en
    return {
        "checkout_url": url,
        "checkout_session_id": checkout_session_id,
        "stripe_customer_id": _id_stripe(_valor(sesion, "customer"))
        or stripe_customer_id,
        "expira_en": expiracion_stripe,
    }


def _obtener_invoice_subscription_id(invoice: Any) -> str | None:
    subscription_id = _id_stripe(_valor(invoice, "subscription"))
    if subscription_id is not None:
        return subscription_id
    parent = _valor(invoice, "parent")
    detalles = _valor(parent, "subscription_details")
    return _id_stripe(_valor(detalles, "subscription"))


def _obtener_customer_id(objeto: Any) -> str | None:
    return _id_stripe(_valor(objeto, "customer"))


def _obtener_estado_membresia(subscription: Any) -> str:
    estado = _valor(subscription, "status")
    if estado not in ESTADOS_STRIPE_MEMBRESIA:
        raise StripeMembresiasError
    return estado


def _obtener_item_subscription(subscription: Any) -> Any:
    items = _valor(_valor(subscription, "items"), "data", [])
    if not isinstance(items, (list, tuple)) or not items:
        raise StripeMembresiasError
    return items[0]


def _sincronizar_subscription(
    db: Session,
    client: stripe.StripeClient,
    settings: Settings,
    *,
    cliente: Cliente,
    subscription_id: str,
    subscription: Any | None = None,
) -> Membresia:
    if subscription is None:
        subscription = client.v1.subscriptions.retrieve(
            subscription_id,
            {"expand": ["items.data.price.product"]},
        )
    if _obtener_customer_id(subscription) != cliente.stripe_customer_id:
        raise StripeMembresiasError
    item = _obtener_item_subscription(subscription)
    price = _valor(item, "price")
    price_id = _id_stripe(price)
    if price_id is None or price_id not in settings.stripe_price_ids:
        raise StripeMembresiasError
    _validar_price_mensual(client, price_id)
    producto = _obtener_producto(client, _valor(price, "product"))
    recurring = _valor(price, "recurring")
    intervalo = _valor(recurring, "interval")
    intervalo_cantidad = _valor(recurring, "interval_count")
    monto = _valor(price, "unit_amount")
    moneda = _valor(price, "currency")
    if (
        not isinstance(intervalo, str)
        or not isinstance(intervalo_cantidad, int)
        or not isinstance(monto, int)
        or not isinstance(moneda, str)
    ):
        raise StripeMembresiasError

    estado = _obtener_estado_membresia(subscription)
    cancelacion_programada = bool(
        _valor(subscription, "cancel_at_period_end", False)
        or _valor(subscription, "cancel_at")
    )
    periodo_inicio = _fecha_stripe(_valor(item, "current_period_start"))
    if periodo_inicio is None:
        periodo_inicio = _fecha_stripe(_valor(subscription, "current_period_start"))
    periodo_fin = _fecha_stripe(_valor(item, "current_period_end"))
    if periodo_fin is None:
        periodo_fin = _fecha_stripe(_valor(subscription, "current_period_end"))
    fecha_inicio = _fecha_stripe(_valor(subscription, "start_date")) or periodo_inicio
    cancelada_en = _fecha_stripe(_valor(subscription, "canceled_at"))

    membresia = db.scalar(
        select(Membresia)
        .where(Membresia.stripe_subscription_id == subscription_id)
        .with_for_update()
    )
    estado_anterior = (
        (
            membresia.stripe_price_id,
            membresia.nombre_plan,
            membresia.monto_centavos,
            membresia.moneda,
            membresia.intervalo,
            membresia.intervalo_cantidad,
            membresia.estado_stripe,
            membresia.cancelacion_programada,
            membresia.fecha_inicio,
            membresia.periodo_actual_inicio,
            membresia.periodo_actual_fin,
            membresia.cancelada_en,
        )
        if membresia is not None
        else None
    )
    if membresia is None:
        membresia = Membresia(
            cliente_id=cliente.id,
            stripe_subscription_id=subscription_id,
            stripe_price_id=price_id,
            nombre_plan=_valor(producto, "name") or NOMBRE_PRODUCTO_MEMBRESIA,
            monto_centavos=monto,
            moneda=moneda,
            intervalo=intervalo,
            intervalo_cantidad=intervalo_cantidad,
            estado_stripe=estado,
            cancelacion_programada=cancelacion_programada,
            fecha_inicio=fecha_inicio,
            periodo_actual_inicio=periodo_inicio,
            periodo_actual_fin=periodo_fin,
            cancelada_en=cancelada_en,
        )
        db.add(membresia)
    else:
        if membresia.cliente_id != cliente.id:
            raise StripeMembresiasError
        membresia.stripe_price_id = price_id
        membresia.nombre_plan = _valor(producto, "name") or NOMBRE_PRODUCTO_MEMBRESIA
        membresia.monto_centavos = monto
        membresia.moneda = moneda
        membresia.intervalo = intervalo
        membresia.intervalo_cantidad = intervalo_cantidad
        membresia.estado_stripe = estado
        membresia.cancelacion_programada = cancelacion_programada
        membresia.fecha_inicio = fecha_inicio or membresia.fecha_inicio
        membresia.periodo_actual_inicio = periodo_inicio
        membresia.periodo_actual_fin = periodo_fin
        membresia.cancelada_en = cancelada_en
    db.flush()
    estado_actual = (
        membresia.stripe_price_id,
        membresia.nombre_plan,
        membresia.monto_centavos,
        membresia.moneda,
        membresia.intervalo,
        membresia.intervalo_cantidad,
        membresia.estado_stripe,
        membresia.cancelacion_programada,
        membresia.fecha_inicio,
        membresia.periodo_actual_inicio,
        membresia.periodo_actual_fin,
        membresia.cancelada_en,
    )
    if estado_actual != estado_anterior:
        registrar_evento_membresia_actualizada(db, cliente_id=cliente.id)
    return membresia


def _obtener_o_vincular_cliente(
    db: Session,
    intento: IntentoCheckoutCliente,
    cuenta: CuentaCliente,
    customer_id: str,
) -> Cliente:
    cliente_cuenta = db.scalar(
        select(Cliente)
        .where(Cliente.cuenta_cliente_id == cuenta.id)
        .with_for_update()
    )
    cliente_stripe = db.scalar(
        select(Cliente)
        .where(Cliente.stripe_customer_id == customer_id)
        .with_for_update()
    )
    if (
        cliente_cuenta is not None
        and cliente_stripe is not None
        and cliente_cuenta.id != cliente_stripe.id
    ):
        raise StripeMembresiasError
    cliente = cliente_cuenta or cliente_stripe
    if cliente is not None and cliente.cuenta_cliente_id not in {None, cuenta.id}:
        raise StripeMembresiasError
    if cliente_cuenta is not None and cliente_cuenta.stripe_customer_id not in {
        None,
        customer_id,
    }:
        raise StripeMembresiasError
    if cliente is None:
        cliente = Cliente(
            cuenta_cliente_id=cuenta.id,
            stripe_customer_id=customer_id,
            nombre_completo=" ".join(
                parte
                for parte in (
                    cuenta.nombre,
                    cuenta.apellido_paterno,
                    cuenta.apellido_materno,
                )
                if parte
            ),
            correo_privado=cuenta.correo,
        )
        db.add(cliente)
        db.flush()
    else:
        cliente.cuenta_cliente_id = cuenta.id
        if cliente.stripe_customer_id is None:
            cliente.stripe_customer_id = customer_id
        cliente.nombre_completo = " ".join(
            parte
            for parte in (
                cuenta.nombre,
                cuenta.apellido_paterno,
                cuenta.apellido_materno,
            )
            if parte
        )
        cliente.correo_privado = cuenta.correo
    intento.stripe_customer_id = customer_id
    return cliente


def _validar_intento_checkout(
    db: Session,
    client: stripe.StripeClient,
    *,
    subscription: Any,
    customer_id: str,
    subscription_id: str,
    factura: Any,
) -> tuple[IntentoCheckoutCliente, CuentaCliente] | None:
    """Vincula solo una compra comprobada por metadata y Checkout completo."""

    metadata_id = _valor(
        _valor(subscription, "metadata"),
        "intento_checkout_id",
    )
    if metadata_id is None:
        return None
    try:
        intento_id = UUID(str(metadata_id))
    except (TypeError, ValueError):
        raise StripeMembresiasError from None

    intento = db.scalar(
        select(IntentoCheckoutCliente)
        .where(IntentoCheckoutCliente.id == intento_id)
        .with_for_update()
    )
    if (
        intento is None
        or intento.estado not in {"creado", "abierto", "confirmado"}
        or intento.checkout_session_id is None
        or intento.stripe_idempotency_key == ""
        or (intento.stripe_customer_id not in {None, customer_id})
        or (intento.stripe_subscription_id not in {None, subscription_id})
    ):
        raise StripeMembresiasError
    es_invoice_inicial = _valor(factura, "billing_reason") == "subscription_create"
    if intento.estado != "confirmado" and not es_invoice_inicial:
        raise StripeMembresiasError

    sesion = client.v1.checkout.sessions.retrieve(intento.checkout_session_id)
    metadata_sesion = _valor(sesion, "metadata")
    if (
        _valor(sesion, "id") != intento.checkout_session_id
        or _valor(sesion, "mode") != "subscription"
        or _valor(sesion, "livemode") is not False
        or _valor(sesion, "status") != "complete"
        or _valor(sesion, "payment_status") != "paid"
        or _valor(metadata_sesion, "intento_checkout_id") != str(intento.id)
        or _obtener_customer_id(sesion) != customer_id
        or _id_stripe(_valor(sesion, "subscription")) != subscription_id
        or _obtener_customer_id(subscription) != customer_id
    ):
        raise StripeMembresiasError
    cuenta = db.scalar(
        select(CuentaCliente)
        .where(CuentaCliente.id == intento.cuenta_cliente_id)
        .with_for_update()
    )
    if cuenta is None or not cuenta.esta_activa:
        raise StripeMembresiasError
    return intento, cuenta


def _upsert_factura(
    db: Session,
    invoice: Any,
    *,
    customer_id: str,
    subscription_id: str | None,
    membresia: Membresia | None,
    evento_tipo: str,
    ya_pagada: bool,
) -> None:
    invoice_id = _id_stripe(_valor(invoice, "id"))
    if invoice_id is None:
        raise StripeMembresiasError
    estado_invoice = _valor(invoice, "status")
    if estado_invoice not in {"draft", "open", "paid", "uncollectible", "void"}:
        estado_invoice = "open"
    if ya_pagada:
        estado_invoice = "paid"
    factura = db.scalar(
        select(FacturaMembresia)
        .where(FacturaMembresia.stripe_invoice_id == invoice_id)
        .with_for_update()
    )
    ahora = datetime.now(UTC)
    if factura is None:
        factura = FacturaMembresia(
            stripe_invoice_id=invoice_id,
            stripe_customer_id=customer_id,
            stripe_subscription_id=subscription_id,
            estado=estado_invoice,
            motivo_cobro=_valor(invoice, "billing_reason"),
            monto_pagado=max(0, int(_valor(invoice, "amount_paid", 0) or 0)),
            monto_pendiente=max(0, int(_valor(invoice, "amount_remaining", 0) or 0)),
            moneda=str(_valor(invoice, "currency", "mxn"))[:3].lower(),
            pagada_en=ahora if ya_pagada else None,
            ultimo_fallo_en=ahora if evento_tipo == "invoice.payment_failed" else None,
            membresia_id=membresia.id if membresia is not None else None,
        )
        db.add(factura)
        return

    factura.stripe_customer_id = customer_id
    factura.stripe_subscription_id = subscription_id or factura.stripe_subscription_id
    if membresia is not None:
        factura.membresia_id = membresia.id
    if factura.estado != "paid" or ya_pagada:
        factura.estado = estado_invoice
        factura.monto_pagado = max(
            factura.monto_pagado,
            int(_valor(invoice, "amount_paid", 0) or 0),
        )
        factura.monto_pendiente = max(
            0,
            int(_valor(invoice, "amount_remaining", 0) or 0),
        )
        factura.motivo_cobro = _valor(invoice, "billing_reason") or factura.motivo_cobro
    if ya_pagada and factura.pagada_en is None:
        factura.pagada_en = ahora
    if evento_tipo == "invoice.payment_failed":
        factura.ultimo_fallo_en = ahora


def _procesar_invoice(
    db: Session,
    client: stripe.StripeClient,
    settings: Settings,
    *,
    evento_tipo: str,
    objeto_evento: Any,
) -> None:
    invoice_id = _id_stripe(_valor(objeto_evento, "id"))
    if invoice_id is None:
        raise StripeMembresiasError
    invoice = client.v1.invoices.retrieve(invoice_id)
    if _id_stripe(_valor(invoice, "id")) != invoice_id:
        raise StripeMembresiasError
    customer_id = _obtener_customer_id(invoice) or _obtener_customer_id(objeto_evento)
    if customer_id is None:
        raise StripeMembresiasError
    customer_evento = _obtener_customer_id(objeto_evento)
    if customer_evento is not None and customer_evento != customer_id:
        raise StripeMembresiasError
    subscription_id = _obtener_invoice_subscription_id(invoice)
    subscription_evento = _obtener_invoice_subscription_id(objeto_evento)
    if (
        subscription_id is not None
        and subscription_evento is not None
        and subscription_id != subscription_evento
    ):
        raise StripeMembresiasError
    if subscription_id is None:
        subscription_id = subscription_evento
    pagada = evento_tipo == "invoice.paid" and _valor(invoice, "status") == "paid"
    membresia: Membresia | None = None
    suscripcion_existente: Membresia | None = None
    if subscription_id is not None:
        suscripcion_existente = db.scalar(
            select(Membresia)
            .where(Membresia.stripe_subscription_id == subscription_id)
            .with_for_update()
        )

    if pagada and int(_valor(invoice, "amount_paid", 0) or 0) > 0 and subscription_id:
        subscription = client.v1.subscriptions.retrieve(
            subscription_id,
            {"expand": ["items.data.price.product"]},
        )
        if _obtener_customer_id(subscription) != customer_id:
            raise StripeMembresiasError
        if suscripcion_existente is not None:
            cliente = db.get(Cliente, suscripcion_existente.cliente_id)
            if cliente is None or cliente.stripe_customer_id != customer_id:
                raise StripeMembresiasError
            membresia = _sincronizar_subscription(
                db,
                client,
                settings,
                cliente=cliente,
                subscription_id=subscription_id,
                subscription=subscription,
            )
        else:
            intento_y_cuenta = _validar_intento_checkout(
                db,
                client,
                subscription=subscription,
                customer_id=customer_id,
                subscription_id=subscription_id,
                factura=invoice,
            )
            if intento_y_cuenta is not None:
                intento, cuenta = intento_y_cuenta
                cliente = _obtener_o_vincular_cliente(
                    db,
                    intento,
                    cuenta,
                    customer_id,
                )
                membresia = _sincronizar_subscription(
                    db,
                    client,
                    settings,
                    cliente=cliente,
                    subscription_id=subscription_id,
                    subscription=subscription,
                )
                intento.stripe_customer_id = customer_id
                intento.stripe_subscription_id = subscription_id
                intento.estado = "confirmado"
    elif subscription_id is not None and suscripcion_existente is not None:
        membresia = db.scalar(
            select(Membresia)
            .where(Membresia.stripe_subscription_id == subscription_id)
            .with_for_update()
        )
        if membresia is not None:
            cliente = db.get(Cliente, membresia.cliente_id)
            if cliente is None:
                raise StripeMembresiasError
            membresia = _sincronizar_subscription(
                db,
                client,
                settings,
                cliente=cliente,
                subscription_id=subscription_id,
            )
    _upsert_factura(
        db,
        invoice,
        customer_id=customer_id,
        subscription_id=subscription_id,
        membresia=membresia,
        evento_tipo=evento_tipo,
        ya_pagada=pagada,
    )


def _procesar_cambio_subscription(
    db: Session,
    client: stripe.StripeClient,
    settings: Settings,
    *,
    objeto_evento: Any,
) -> None:
    subscription_id = _id_stripe(_valor(objeto_evento, "id"))
    if subscription_id is None:
        raise StripeMembresiasError
    membresia = db.scalar(
        select(Membresia)
        .where(Membresia.stripe_subscription_id == subscription_id)
        .with_for_update()
    )
    if membresia is None:
        return
    cliente = db.get(Cliente, membresia.cliente_id)
    if cliente is None:
        raise StripeMembresiasError
    _sincronizar_subscription(
        db,
        client,
        settings,
        cliente=cliente,
        subscription_id=subscription_id,
    )


def procesar_evento_stripe(
    db: Session,
    client: stripe.StripeClient,
    settings: Settings,
    *,
    evento: Any,
) -> bool:
    """Procesa cada evento de forma sincrona y confirma todo en una transaccion."""

    event_id = _valor(evento, "id")
    event_type = _valor(evento, "type")
    if not isinstance(event_id, str) or not isinstance(event_type, str):
        raise StripeMembresiasError
    data = _valor(evento, "data")
    objeto = _valor(data, "object")
    objeto_id = _id_stripe(_valor(objeto, "id"))
    fila = EventoStripe(
        stripe_event_id=event_id,
        tipo=event_type,
        livemode=False,
        objeto_id=objeto_id,
        creado_en_stripe=_fecha_stripe(_valor(evento, "created")),
        procesado_en=None,
        intentos=1,
    )
    try:
        db.add(fila)
        db.flush()
    except IntegrityError:
        db.rollback()
        return False

    if event_type in {"invoice.paid", "invoice.payment_failed"}:
        _procesar_invoice(
            db,
            client,
            settings,
            evento_tipo=event_type,
            objeto_evento=objeto,
        )
    elif event_type in {
        "customer.subscription.updated",
        "customer.subscription.deleted",
    }:
        _procesar_cambio_subscription(
            db,
            client,
            settings,
            objeto_evento=objeto,
        )
    fila.procesado_en = datetime.now(UTC)
    db.commit()
    return True


def mapear_estado_membresia(estado_stripe: str, cancelacion_programada: bool) -> str:
    """Conserva el cobro vencido separado de las cancelaciones ya efectivas."""

    if estado_stripe == "active" and cancelacion_programada:
        return "cancelacion_programada"
    if estado_stripe == "active":
        return "activa"
    if estado_stripe == "past_due":
        return "pago_vencido"
    if estado_stripe == "canceled":
        return "cancelada"
    if estado_stripe in {"unpaid", "paused"}:
        return "inactiva"
    return "pendiente"


__all__ = [
    "EVENTOS_STRIPE_MEMBRESIA",
    "IMPORTE_MEMBRESIA_CENTAVOS",
    "MONEDA_MEMBRESIA",
    "NOMBRE_PRODUCTO_MEMBRESIA",
    "MembresiasNoDisponiblesError",
    "StripeMembresiasError",
    "StripeNoConfiguradoError",
    "crear_checkout_membresia",
    "crear_cliente_stripe",
    "exigir_membresias_disponibles",
    "listar_planes_membresia",
    "mapear_estado_membresia",
    "procesar_evento_stripe",
]
