SELECT estacionamiento_id, revision
FROM configuracion_estacionamiento
WHERE id = 1 AND estado = 'CONFIGURADA'
FOR UPDATE
