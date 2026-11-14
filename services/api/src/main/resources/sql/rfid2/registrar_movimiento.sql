INSERT INTO movimiento_estacionamiento (
    asociacion_id, tipo_persona, cliente_id, empleado_id, uid_historico, lectura_id,
    fecha_entrada, hora_entrada, instante_entrada)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT DO NOTHING
RETURNING movimiento_id
