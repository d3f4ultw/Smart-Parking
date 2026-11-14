UPDATE configuracion_estacionamiento
SET estado = 'CONFIGURADA', revision = ?, revision_propietario = ?,
    dueno_cuenta_id = ?, propietario_nombres = NULL, propietario_primer_apellido = NULL,
    propietario_segundo_apellido = NULL, correo_propietario = NULL,
    hash_contrasena_acceso = NULL, hash_contrasena_administrativa = ?,
    nombre_estacionamiento = ?, tipo_estacionamiento = ?, modo_horario = ?, zona_horaria = ?,
    hora_apertura = ?, hora_cierre = ?, transfer_id = NULL, hash_grant_transferencia = NULL,
    grant_vence_en = NULL, hash_recuperacion_transferencia = NULL,
    estado_aviso_transferencia = 'NO_APLICA', estado_aviso_bienvenida = 'RESERVADO',
    ultima_operacion_id = ?, ultima_clave_idempotencia_hash = ?
WHERE id = 1 AND estado = 'TRANSFERENCIA_PENDIENTE'
