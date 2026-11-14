INSERT INTO empleado (
    nombres, primer_apellido, segundo_apellido, correo, correo_normalizado)
VALUES (?, ?, ?, ?, ?) RETURNING id
