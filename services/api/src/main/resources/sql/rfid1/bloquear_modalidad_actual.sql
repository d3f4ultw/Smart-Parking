SELECT tipo_estacionamiento
FROM configuracion_estacionamiento
WHERE id = 1 AND estado = 'CONFIGURADA'
FOR SHARE
