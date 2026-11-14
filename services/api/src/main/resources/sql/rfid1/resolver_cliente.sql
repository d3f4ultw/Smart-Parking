SELECT codigo.cliente_id, codigo.numero, cuenta.estado,
       COALESCE(suscripcion.estado, CASE WHEN intento.intento_id IS NULL
           THEN 'SIN_MEMBRESIA' ELSE 'PENDIENTE' END) AS estado_membresia
FROM cliente_codigo_publico AS codigo
JOIN cuenta ON cuenta.id = codigo.cliente_id
LEFT JOIN LATERAL (
    SELECT estado
    FROM suscripcion_cliente
    WHERE cliente_id = codigo.cliente_id
    ORDER BY CASE WHEN estado IN ('PENDIENTE', 'ACTIVA', 'PAGO_VENCIDO') THEN 0 ELSE 1 END,
             evento_creado_en DESC, stripe_subscription_id DESC
    LIMIT 1
) suscripcion ON TRUE
LEFT JOIN LATERAL (
    SELECT intento_id
    FROM intento_checkout
    WHERE cliente_id = codigo.cliente_id
      AND estado IN ('RESERVADO', 'ABIERTO', 'RECONCILIANDO', 'INDETERMINADO')
    ORDER BY creado_en DESC, intento_id DESC
    LIMIT 1
) intento ON TRUE
WHERE codigo.numero = ? AND cuenta.rol = 'CLIENTE'
FOR UPDATE OF codigo, cuenta
