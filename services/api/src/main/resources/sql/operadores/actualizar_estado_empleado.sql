UPDATE empleado
SET estado = ?, revision = revision + 1, actualizado_en = CURRENT_TIMESTAMP
WHERE id = ? AND revision = ? AND revision < 9223372036854775807
