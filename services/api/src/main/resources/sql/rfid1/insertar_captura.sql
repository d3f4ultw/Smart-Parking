INSERT INTO captura_rfid1 (
    captura_id, tipo_entidad, codigo_persona, cliente_id, empleado_id,
    propietario_cuenta_id, revision_acceso, revision_propietario, huella_sesion,
    clave_inicio_hash, huella_solicitud, estado, creada_en, actualizada_en, vence_en)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDIENTE', ?, ?, ?)
ON CONFLICT DO NOTHING
