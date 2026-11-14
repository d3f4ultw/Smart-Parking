SELECT c.estado, c.revision, c.revision_propietario, c.estacionamiento_id,
       a.nombres AS propietario_nombres, a.primer_apellido AS propietario_primer_apellido,
       a.segundo_apellido AS propietario_segundo_apellido, a.correo AS correo_propietario,
       NULL::VARCHAR AS hash_contrasena_acceso, c.hash_contrasena_administrativa,
       c.nombre_estacionamiento, c.tipo_estacionamiento, c.modo_horario, c.zona_horaria,
       c.hora_apertura, c.hora_cierre, c.transfer_id, c.hash_grant_transferencia,
       c.grant_vence_en, c.hash_recuperacion_transferencia, c.estado_aviso_transferencia,
       c.estado_aviso_bienvenida, c.ultima_operacion_id, c.ultima_clave_idempotencia_hash
FROM configuracion_estacionamiento c
LEFT JOIN cuenta a ON a.id = c.dueno_cuenta_id
WHERE c.id = 1
