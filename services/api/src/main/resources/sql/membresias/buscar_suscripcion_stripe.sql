SELECT cliente_id, stripe_customer_id, price_id, evento_creado_en
FROM suscripcion_cliente WHERE stripe_subscription_id = ? FOR UPDATE
