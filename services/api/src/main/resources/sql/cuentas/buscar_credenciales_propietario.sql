SELECT a.id, a.rol, a.revision_acceso, c.revision_propietario,
       a.correo, a.hash_contrasena_acceso
FROM configuracion_estacionamiento c
JOIN cuenta a ON a.id = c.dueno_cuenta_id
WHERE c.id = 1 AND c.estado = 'CONFIGURADA'
  AND a.estado = 'ACTIVA' AND a.rol = 'DUENO'
  AND a.correo_normalizado = ?
UNION ALL
SELECT a.id, a.rol, a.revision_acceso, 0::BIGINT AS revision_propietario,
       a.correo, a.hash_contrasena_acceso
FROM cuenta a
JOIN empleado e ON e.id = a.empleado_id
WHERE a.rol = 'OPERADOR' AND a.estado = 'ACTIVA'
  AND e.estado = 'ACTIVO'
  AND a.hash_contrasena_acceso IS NOT NULL
  AND a.correo_normalizado = ?
