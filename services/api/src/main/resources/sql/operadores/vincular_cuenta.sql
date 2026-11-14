UPDATE cuenta
SET empleado_id = ?, revision_acceso = revision_acceso + 1,
    actualizada_en = CURRENT_TIMESTAMP
WHERE id = ? AND rol = 'OPERADOR' AND empleado_id IS NULL AND revision_acceso = ?
