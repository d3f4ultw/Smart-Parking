SELECT tarjeta.asociacion_id, NULL::text AS uid_canonico, tarjeta.estado,
       tarjeta.asociada_en, tarjeta.cancelada_en,
       (tarjeta.cliente_id IS NOT NULL) AS es_cliente,
       codigo.numero AS numero_cliente, empleado.id AS numero_empleado,
       COALESCE(cuenta.nombres, empleado.nombres) AS nombres,
       COALESCE(cuenta.primer_apellido, empleado.primer_apellido) AS primer_apellido,
       COALESCE(cuenta.segundo_apellido, empleado.segundo_apellido) AS segundo_apellido
FROM asociacion_tarjeta_rfid1 AS tarjeta
LEFT JOIN cliente_codigo_publico AS codigo ON codigo.cliente_id = tarjeta.cliente_id
LEFT JOIN cuenta ON cuenta.id = tarjeta.cliente_id
LEFT JOIN empleado ON empleado.id = tarjeta.empleado_id
WHERE tarjeta.asociacion_id = ?
