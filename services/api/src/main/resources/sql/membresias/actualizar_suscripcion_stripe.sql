UPDATE suscripcion_cliente
SET estado_stripe = ?, estado = ?, invoice_id = ?, estado_factura_stripe = ?,
    periodo_inicio = ?, periodo_fin = ?, cancel_at_period_end = ?,
    evento_creado_en = ?, actualizada_en = ?
WHERE stripe_subscription_id = ? AND cliente_id = ? AND stripe_customer_id = ?
  AND price_id = ? AND evento_creado_en <= ?
