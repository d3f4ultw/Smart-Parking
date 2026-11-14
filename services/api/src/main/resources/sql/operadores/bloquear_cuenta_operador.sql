SELECT id, rol, estado, correo, hash_contrasena_acceso, revision_acceso, empleado_id
FROM cuenta WHERE id = ? FOR UPDATE
