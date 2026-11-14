SELECT empleado.id, empleado.nombres, empleado.primer_apellido,
       empleado.segundo_apellido, empleado.estado, NULL::text AS estado_membresia,
       EXISTS (SELECT 1 FROM asociacion_tarjeta_rfid1 tarjeta
               WHERE tarjeta.empleado_id = empleado.id AND tarjeta.estado = 'ACTIVA') AS tiene_activa
FROM empleado
WHERE concat_ws(' ', empleado.nombres, empleado.primer_apellido, empleado.segundo_apellido,
    'E-' || CASE WHEN length(empleado.id::text) < 4
        THEN lpad(empleado.id::text, 4, '0') ELSE empleado.id::text END) ILIKE ?
ORDER BY empleado.id ASC LIMIT ?
