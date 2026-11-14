SELECT
    COALESCE(s.estado, CASE WHEN p.intento_id IS NULL THEN 'SIN_MEMBRESIA' ELSE 'PENDIENTE' END) AS estado,
    s.periodo_inicio,
    s.periodo_fin,
    CASE WHEN s.estado = 'ACTIVA' AND s.cancel_at_period_end = FALSE
         THEN s.periodo_fin ELSE NULL END AS siguiente_cobro_en,
    COALESCE(s.cancel_at_period_end, FALSE) AS cancelacion_al_final,
    CASE WHEN s.estado IN ('PENDIENTE', 'ACTIVA', 'PAGO_VENCIDO') OR p.intento_id IS NOT NULL
         THEN FALSE
         WHEN (SELECT count(*) FROM intento_checkout i
               WHERE i.cliente_id = c.id AND i.creado_en >= CURRENT_TIMESTAMP - INTERVAL '15 minutes') >= 5
         THEN FALSE ELSE TRUE END AS puede_comprar,
    p.intento_id AS intento_checkout_pendiente_id,
    p.estado AS estado_checkout_pendiente,
    p.expira_en AS checkout_expira_en
FROM cuenta c
LEFT JOIN LATERAL (
    SELECT estado, periodo_inicio, periodo_fin, cancel_at_period_end
    FROM suscripcion_cliente
    WHERE cliente_id = c.id
    ORDER BY CASE WHEN estado IN ('PENDIENTE', 'ACTIVA', 'PAGO_VENCIDO') THEN 0 ELSE 1 END,
             evento_creado_en DESC, stripe_subscription_id DESC
    LIMIT 1
) s ON TRUE
LEFT JOIN LATERAL (
    SELECT intento_id, estado, expira_en
    FROM intento_checkout
    WHERE cliente_id = c.id
      AND estado IN ('RESERVADO', 'ABIERTO', 'RECONCILIANDO', 'INDETERMINADO')
    ORDER BY creado_en DESC, intento_id DESC
    LIMIT 1
) p ON TRUE
WHERE c.id = ? AND c.rol = 'CLIENTE' AND c.estado = 'ACTIVA'
