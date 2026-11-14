INSERT INTO asociacion_tarjeta_rfid1 (uid_canonico, cliente_id, empleado_id, asociada_en)
VALUES (?, ?, ?, ?)
ON CONFLICT DO NOTHING
RETURNING asociacion_id
