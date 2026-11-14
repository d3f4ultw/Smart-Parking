INSERT INTO cuenta (
    id, nombres, primer_apellido, segundo_apellido, correo, correo_normalizado,
    rol, estado, hash_contrasena_acceso, revision_acceso, empleado_id, creada_en, actualizada_en)
SELECT ?, e.nombres, e.primer_apellido, e.segundo_apellido,
       e.correo, e.correo_normalizado, 'OPERADOR', 'PENDIENTE', NULL,
       0, e.id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
FROM empleado e
WHERE e.id = ? AND e.estado = 'ACTIVO'
RETURNING id
