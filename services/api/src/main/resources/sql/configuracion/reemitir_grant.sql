UPDATE configuracion_estacionamiento
SET hash_grant_transferencia = ?, grant_vence_en = ?, revision = ?
WHERE id = 1 AND estado = 'TRANSFERENCIA_PENDIENTE'
