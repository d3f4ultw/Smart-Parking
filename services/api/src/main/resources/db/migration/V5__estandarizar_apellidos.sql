-- Renombramos las columnas sin copiar ni modificar los valores existentes.
ALTER TABLE cuenta
    RENAME COLUMN apellido_paterno TO primer_apellido;

ALTER TABLE cuenta
    RENAME COLUMN apellido_materno TO segundo_apellido;

-- Estos campos singleton permanecen nulos desde V3 y ya no son fuente de identidad.
ALTER TABLE configuracion_estacionamiento
    RENAME COLUMN propietario_apellido_paterno TO propietario_primer_apellido;

ALTER TABLE configuracion_estacionamiento
    RENAME COLUMN propietario_apellido_materno TO propietario_segundo_apellido;
