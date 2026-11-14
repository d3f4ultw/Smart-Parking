SELECT id, nombres, primer_apellido, segundo_apellido, correo,
       estado, creada_en, revision_acceso, empleado_id
FROM cuenta WHERE rol = 'OPERADOR' AND empleado_id = ? FOR UPDATE
