SELECT id, nombres, primer_apellido, segundo_apellido, estado, revision,
       correo, correo_normalizado
FROM empleado
WHERE id = ? FOR UPDATE
