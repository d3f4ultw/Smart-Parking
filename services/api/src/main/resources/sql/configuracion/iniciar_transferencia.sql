UPDATE configuracion_estacionamiento
SET estado = 'TRANSFERENCIA_PENDIENTE', revision = ?, revision_propietario = ?,
    dueno_cuenta_id = NULL,
    propietario_nombres = NULL, propietario_primer_apellido = NULL,
    propietario_segundo_apellido = NULL, correo_propietario = NULL,
    hash_contrasena_acceso = NULL, hash_contrasena_administrativa = NULL,
    transfer_id = ?, hash_grant_transferencia = ?, grant_vence_en = ?,
    hash_recuperacion_transferencia = ?, estado_aviso_transferencia = 'RESERVADO',
    estado_aviso_bienvenida = 'NO_APLICA', ultima_operacion_id = ?,
    ultima_clave_idempotencia_hash = ?
WHERE id = 1 AND estado = 'CONFIGURADA'
