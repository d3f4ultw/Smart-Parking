SELECT estado FROM solicitud_salida_manual
WHERE movimiento_id = ? AND estado IN ('PENDIENTE', 'EMITIDA', 'INCIERTA') FOR UPDATE
