DELETE FROM captura_rfid1
WHERE estado IN ('COMPLETADA', 'CANCELADA', 'EXPIRADA', 'RECHAZADA')
  AND actualizada_en <= ?
