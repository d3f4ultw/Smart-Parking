UPDATE stripe_evento_procesado
SET estado = ?, evento_creado_en = ?, actualizado_en = ?, procesado_en = ?
WHERE event_id = ? AND estado IN ('RECIBIDO', 'REINTENTAR')
