UPDATE movimiento_estacionamiento
SET fecha_salida = ?, hora_salida = ?, instante_salida = ?, lectura_salida_id = ?
WHERE movimiento_id = ? AND asociacion_id = ? AND instante_salida IS NULL
