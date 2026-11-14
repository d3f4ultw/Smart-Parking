UPDATE cuenta
SET estado = 'PENDIENTE', hash_contrasena_acceso = NULL,
    correo = ?, correo_normalizado = ?, revision_acceso = revision_acceso + 1,
    actualizada_en = CURRENT_TIMESTAMP
WHERE id = ? AND empleado_id = ? AND rol = 'OPERADOR'
  AND estado = 'INACTIVA' AND revision_acceso = ?
