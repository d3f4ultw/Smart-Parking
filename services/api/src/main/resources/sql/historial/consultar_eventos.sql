SELECT evento.evento_id, evento.ocurrido_en, evento.lector, evento.resultado, evento.motivo,
       CASE WHEN asociacion.cliente_id IS NOT NULL THEN 'CLIENTE'
            WHEN asociacion.empleado_id IS NOT NULL THEN 'EMPLEADO' END AS tipo_persona,
       CASE WHEN asociacion.cliente_id IS NOT NULL THEN
                concat_ws(' ', cuenta.nombres, cuenta.primer_apellido, cuenta.segundo_apellido)
            WHEN asociacion.empleado_id IS NOT NULL THEN
                concat_ws(' ', empleado.nombres, empleado.primer_apellido, empleado.segundo_apellido)
       END AS nombre_persona
FROM evento_acceso evento
LEFT JOIN asociacion_tarjeta_rfid1 asociacion ON asociacion.asociacion_id = evento.asociacion_id
LEFT JOIN cuenta ON cuenta.id = asociacion.cliente_id
LEFT JOIN empleado ON empleado.id = asociacion.empleado_id
WHERE (? = 'TODOS' OR evento.lector = ?)
    AND (? = 'TODOS' OR evento.resultado = ?)
    AND (CAST(? AS timestamptz) IS NULL OR evento.ocurrido_en >= CAST(? AS timestamptz))
    AND (CAST(? AS timestamptz) IS NULL OR evento.ocurrido_en < CAST(? AS timestamptz))
ORDER BY evento.ocurrido_en DESC, evento.evento_id DESC
LIMIT ? OFFSET ?
