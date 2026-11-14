UPDATE solicitud_salida_manual SET estado = 'ANULADA'
WHERE movimiento_id = ? AND estado = 'PENDIENTE'
