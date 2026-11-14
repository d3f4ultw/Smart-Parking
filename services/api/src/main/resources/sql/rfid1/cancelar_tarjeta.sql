UPDATE asociacion_tarjeta_rfid1
SET estado = 'CANCELADA', cancelada_en = ?
WHERE asociacion_id = ? AND estado = 'ACTIVA'
