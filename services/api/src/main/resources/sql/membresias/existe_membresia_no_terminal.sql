SELECT count(*) FROM suscripcion_cliente
WHERE cliente_id = ? AND estado IN ('PENDIENTE', 'ACTIVA', 'PAGO_VENCIDO')
