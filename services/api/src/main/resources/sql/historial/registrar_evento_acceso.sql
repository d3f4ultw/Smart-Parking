INSERT INTO evento_acceso (
    ocurrido_en, lector, resultado, motivo, lectura_id, asociacion_id, movimiento_id)
VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (lector, lectura_id) DO UPDATE SET
    ocurrido_en = EXCLUDED.ocurrido_en,
    resultado = EXCLUDED.resultado,
    motivo = EXCLUDED.motivo,
    asociacion_id = EXCLUDED.asociacion_id,
    movimiento_id = EXCLUDED.movimiento_id
WHERE evento_acceso.resultado IS DISTINCT FROM EXCLUDED.resultado
    OR evento_acceso.motivo IS DISTINCT FROM EXCLUDED.motivo
    OR evento_acceso.asociacion_id IS DISTINCT FROM EXCLUDED.asociacion_id
    OR evento_acceso.movimiento_id IS DISTINCT FROM EXCLUDED.movimiento_id
RETURNING evento_id
