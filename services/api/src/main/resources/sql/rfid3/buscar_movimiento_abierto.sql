SELECT movimiento_id, instante_entrada FROM movimiento_estacionamiento
WHERE asociacion_id = ? AND instante_salida IS NULL
