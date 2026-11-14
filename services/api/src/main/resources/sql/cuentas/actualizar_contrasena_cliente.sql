UPDATE cuenta
SET hash_contrasena_acceso = ?, revision_acceso = revision_acceso + 1, actualizada_en = ?
WHERE id = ? AND rol = 'CLIENTE' AND estado = 'ACTIVA' AND revision_acceso = ?
  AND revision_acceso < 9223372036854775807
