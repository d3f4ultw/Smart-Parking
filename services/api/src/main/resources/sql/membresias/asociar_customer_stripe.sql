UPDATE cliente_stripe
SET stripe_customer_id = ?, estado = 'ASOCIADO', actualizada_en = ?
WHERE cliente_id = ?
  AND (stripe_customer_id IS NULL OR stripe_customer_id = ?)
