UPDATE cliente_stripe
SET estado = 'INDETERMINADO'
WHERE cliente_id = ? AND stripe_customer_id IS NULL
  AND estado IN ('RESERVADO', 'INDETERMINADO')
