WITH candidatos_cliente AS (
    SELECT codigo.numero AS numero, cuenta.nombres, cuenta.primer_apellido,
           cuenta.segundo_apellido, cuenta.estado,
           COALESCE(suscripcion.estado, CASE WHEN intento.intento_id IS NULL
               THEN 'SIN_MEMBRESIA' ELSE 'PENDIENTE' END) AS estado_membresia,
           EXISTS (SELECT 1 FROM asociacion_tarjeta_rfid1 tarjeta
                   WHERE tarjeta.cliente_id = cuenta.id AND tarjeta.estado = 'ACTIVA')
               AS tiene_activa,
           'CLIENTE'::text AS tipo_entidad
    FROM cliente_codigo_publico AS codigo
    JOIN cuenta ON cuenta.id = codigo.cliente_id AND cuenta.rol = 'CLIENTE'
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
    WHERE concat_ws(' ', cuenta.nombres, cuenta.primer_apellido, cuenta.segundo_apellido,
        'CLI-' || CASE WHEN length(codigo.numero::text) < 4
            THEN lpad(codigo.numero::text, 4, '0') ELSE codigo.numero::text END) ILIKE ?
    ORDER BY codigo.numero ASC LIMIT ?
), candidatos_empleado AS (
    SELECT empleado.id AS numero, empleado.nombres, empleado.primer_apellido,
           empleado.segundo_apellido, empleado.estado, NULL::text AS estado_membresia,
           EXISTS (SELECT 1 FROM asociacion_tarjeta_rfid1 tarjeta
                   WHERE tarjeta.empleado_id = empleado.id AND tarjeta.estado = 'ACTIVA')
               AS tiene_activa,
           'EMPLEADO'::text AS tipo_entidad
    FROM empleado
    WHERE concat_ws(' ', empleado.nombres, empleado.primer_apellido,
        empleado.segundo_apellido, 'E-' || CASE WHEN length(empleado.id::text) < 4
            THEN lpad(empleado.id::text, 4, '0') ELSE empleado.id::text END) ILIKE ?
    ORDER BY empleado.id ASC LIMIT ?
), candidatos AS (
    SELECT * FROM candidatos_cliente
    UNION ALL
    SELECT * FROM candidatos_empleado
), candidatos_intercalados AS (
    SELECT candidatos.*,
           row_number() OVER (PARTITION BY tipo_entidad ORDER BY numero ASC) AS orden_tipo
    FROM candidatos
)
SELECT numero, nombres, primer_apellido, segundo_apellido, estado, estado_membresia,
       tiene_activa, tipo_entidad
FROM candidatos_intercalados
ORDER BY orden_tipo ASC, tipo_entidad ASC, numero ASC
LIMIT ?
