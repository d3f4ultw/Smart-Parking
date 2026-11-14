SELECT
    (SELECT count(*) FROM vision_cajon c
     JOIN vision_zona z ON z.cajon_id = c.cajon_id AND z.activa
     WHERE c.estacionamiento_id = configuracion.estacionamiento_id) AS capacidad,
    (SELECT count(*) FROM movimiento_estacionamiento
     WHERE instante_salida IS NULL) AS dentro
FROM configuracion_estacionamiento configuracion
WHERE configuracion.id = 1 AND configuracion.estado = 'CONFIGURADA'
    AND configuracion.estacionamiento_id IS NOT NULL
