UPDATE cuenta
SET correo = ?, correo_normalizado = ?, revision_acceso = revision_acceso + 1,
    actualizada_en = CURRENT_TIMESTAMP
WHERE id = ? AND rol = 'OPERADOR' AND revision_acceso = ?
