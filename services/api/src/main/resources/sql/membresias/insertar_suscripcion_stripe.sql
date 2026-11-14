INSERT INTO suscripcion_cliente (
    stripe_subscription_id, cliente_id, stripe_customer_id, price_id,
    estado_stripe, estado, invoice_id, estado_factura_stripe,
    periodo_inicio, periodo_fin, cancel_at_period_end, evento_creado_en,
    actualizada_en, livemode)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, FALSE)
ON CONFLICT (stripe_subscription_id) DO NOTHING
