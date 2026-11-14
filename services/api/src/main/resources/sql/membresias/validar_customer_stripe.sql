SELECT stripe_customer_id FROM cliente_stripe
WHERE cliente_id = ? AND stripe_customer_id = ? AND estado = 'ASOCIADO' AND livemode = FALSE
FOR UPDATE
