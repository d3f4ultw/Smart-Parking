CREATE TABLE cliente_stripe (
    cliente_id UUID PRIMARY KEY,
    estado VARCHAR(20) NOT NULL,
    stripe_customer_id VARCHAR(255),
    livemode BOOLEAN NOT NULL DEFAULT FALSE,
    creada_en TIMESTAMPTZ NOT NULL,
    actualizada_en TIMESTAMPTZ NOT NULL,
    CONSTRAINT cliente_stripe_cliente_fk
        FOREIGN KEY (cliente_id) REFERENCES cuenta(id) ON DELETE RESTRICT,
    CONSTRAINT cliente_stripe_estado_ck
        CHECK (estado IN ('RESERVADO', 'ASOCIADO', 'INDETERMINADO')),
    CONSTRAINT cliente_stripe_customer_id_ck
        CHECK (
            (estado = 'ASOCIADO' AND stripe_customer_id IS NOT NULL
                AND stripe_customer_id ~ '^cus_[A-Za-z0-9]+$')
            OR (estado IN ('RESERVADO', 'INDETERMINADO') AND stripe_customer_id IS NULL)
        ),
    CONSTRAINT cliente_stripe_customer_uq UNIQUE (stripe_customer_id),
    CONSTRAINT cliente_stripe_cliente_customer_uq UNIQUE (cliente_id, stripe_customer_id),
    CONSTRAINT cliente_stripe_sandbox_ck CHECK (livemode = FALSE)
);

CREATE TABLE intento_checkout (
    intento_id UUID PRIMARY KEY,
    cliente_id UUID NOT NULL,
    clave_hash CHAR(64) NOT NULL,
    huella_solicitud CHAR(64) NOT NULL,
    estado VARCHAR(20) NOT NULL,
    session_id VARCHAR(255),
    price_id VARCHAR(128) NOT NULL,
    expira_en TIMESTAMPTZ,
    livemode BOOLEAN NOT NULL DEFAULT FALSE,
    creado_en TIMESTAMPTZ NOT NULL,
    actualizado_en TIMESTAMPTZ NOT NULL,
    CONSTRAINT intento_checkout_cliente_fk
        FOREIGN KEY (cliente_id) REFERENCES cuenta(id) ON DELETE RESTRICT,
    CONSTRAINT intento_checkout_idempotencia_uq UNIQUE (cliente_id, clave_hash),
    CONSTRAINT intento_checkout_session_uq UNIQUE (session_id),
    CONSTRAINT intento_checkout_clave_hash_ck CHECK (clave_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT intento_checkout_huella_ck CHECK (huella_solicitud ~ '^[0-9a-f]{64}$'),
    CONSTRAINT intento_checkout_price_ck CHECK (price_id = 'price_1USQ5HAqtHmR2qmyAWwUp5vy'),
    CONSTRAINT intento_checkout_estado_ck CHECK (
        estado IN ('RESERVADO', 'ABIERTO', 'RECONCILIANDO', 'COMPLETADO', 'EXPIRADO', 'FALLIDO', 'INDETERMINADO')
    ),
    CONSTRAINT intento_checkout_session_id_ck CHECK (
        session_id IS NULL OR session_id ~ '^cs_test_[A-Za-z0-9]+$'
    ),
    CONSTRAINT intento_checkout_fechas_ck CHECK (
        expira_en IS NULL OR expira_en >= creado_en
    ),
    CONSTRAINT intento_checkout_estado_campos_ck CHECK (
        (estado = 'RESERVADO' AND session_id IS NULL AND expira_en IS NULL)
        OR (estado = 'ABIERTO' AND session_id IS NOT NULL AND expira_en IS NOT NULL)
        OR (estado = 'COMPLETADO' AND session_id IS NOT NULL)
        OR (estado = 'EXPIRADO' AND session_id IS NOT NULL AND expira_en IS NOT NULL)
        OR (estado IN ('RECONCILIANDO', 'INDETERMINADO')
            AND (session_id IS NOT NULL OR expira_en IS NULL))
        OR estado = 'FALLIDO'
    ),
    CONSTRAINT intento_checkout_sandbox_ck CHECK (livemode = FALSE)
);

CREATE UNIQUE INDEX intento_checkout_cliente_abierto_uq
    ON intento_checkout (cliente_id)
    WHERE estado IN ('RESERVADO', 'ABIERTO', 'RECONCILIANDO', 'INDETERMINADO');

CREATE INDEX intento_checkout_cliente_reciente_idx
    ON intento_checkout (cliente_id, creado_en DESC, intento_id DESC);

CREATE TABLE suscripcion_cliente (
    stripe_subscription_id VARCHAR(255) PRIMARY KEY,
    cliente_id UUID NOT NULL,
    stripe_customer_id VARCHAR(255) NOT NULL,
    price_id VARCHAR(128) NOT NULL,
    estado_stripe VARCHAR(32) NOT NULL,
    estado VARCHAR(24) NOT NULL,
    invoice_id VARCHAR(255),
    estado_factura_stripe VARCHAR(32),
    periodo_inicio TIMESTAMPTZ,
    periodo_fin TIMESTAMPTZ,
    cancel_at_period_end BOOLEAN NOT NULL,
    evento_creado_en TIMESTAMPTZ NOT NULL,
    actualizada_en TIMESTAMPTZ NOT NULL,
    livemode BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT suscripcion_cliente_customer_fk
        FOREIGN KEY (cliente_id, stripe_customer_id)
        REFERENCES cliente_stripe (cliente_id, stripe_customer_id) ON DELETE RESTRICT,
    CONSTRAINT suscripcion_cliente_price_ck CHECK (price_id = 'price_1USQ5HAqtHmR2qmyAWwUp5vy'),
    CONSTRAINT suscripcion_cliente_estado_stripe_ck
        CHECK (estado_stripe IN (
            'incomplete', 'incomplete_expired', 'trialing', 'active',
            'past_due', 'unpaid', 'canceled', 'paused'
        )),
    CONSTRAINT suscripcion_cliente_estado_ck
        CHECK (estado IN ('PENDIENTE', 'ACTIVA', 'PAGO_VENCIDO', 'CANCELADA', 'INACTIVA')),
    CONSTRAINT suscripcion_cliente_periodo_ck CHECK (
        (periodo_inicio IS NULL AND periodo_fin IS NULL)
        OR (periodo_inicio IS NOT NULL AND periodo_fin IS NOT NULL AND periodo_inicio <= periodo_fin)
    ),
    CONSTRAINT suscripcion_cliente_sandbox_ck CHECK (livemode = FALSE)
);

CREATE UNIQUE INDEX suscripcion_cliente_no_terminal_uq
    ON suscripcion_cliente (cliente_id)
    WHERE estado IN ('PENDIENTE', 'ACTIVA', 'PAGO_VENCIDO');

CREATE INDEX suscripcion_cliente_historial_idx
    ON suscripcion_cliente (cliente_id, evento_creado_en DESC, stripe_subscription_id DESC);

CREATE TABLE stripe_evento_procesado (
    event_id VARCHAR(255) PRIMARY KEY,
    event_type VARCHAR(80) NOT NULL,
    object_id VARCHAR(255) NOT NULL,
    estado VARCHAR(16) NOT NULL DEFAULT 'RECIBIDO',
    recibido_en TIMESTAMPTZ NOT NULL,
    evento_creado_en TIMESTAMPTZ,
    actualizado_en TIMESTAMPTZ NOT NULL,
    procesado_en TIMESTAMPTZ,
    livemode BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT stripe_evento_id_ck CHECK (event_id ~ '^evt_[A-Za-z0-9]+$'),
    CONSTRAINT stripe_evento_tipo_ck CHECK (event_type IN (
        'customer.subscription.created',
        'checkout.session.completed',
        'checkout.session.expired',
        'invoice.paid',
        'invoice.payment_failed',
        'customer.subscription.updated',
        'customer.subscription.deleted'
    )),
    CONSTRAINT stripe_evento_estado_ck CHECK (estado IN ('RECIBIDO', 'REINTENTAR', 'APLICADO', 'IGNORADO')),
    CONSTRAINT stripe_evento_procesamiento_ck CHECK (
        (estado IN ('RECIBIDO', 'REINTENTAR') AND procesado_en IS NULL)
        OR (estado IN ('APLICADO', 'IGNORADO') AND procesado_en IS NOT NULL)
    ),
    CONSTRAINT stripe_evento_sandbox_ck CHECK (livemode = FALSE)
);
