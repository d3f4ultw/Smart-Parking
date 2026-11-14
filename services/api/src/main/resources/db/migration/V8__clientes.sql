ALTER TABLE cuenta
    DROP CONSTRAINT cuenta_rol_check,
    DROP CONSTRAINT cuenta_rol_estado_ck;

ALTER TABLE cuenta
    ADD CONSTRAINT cuenta_rol_ck
        CHECK (rol IN ('DUENO', 'OPERADOR', 'CLIENTE')),
    ADD CONSTRAINT cuenta_rol_estado_ck
        CHECK (
            (rol = 'DUENO' AND estado IN ('ACTIVA', 'INACTIVA'))
            OR (rol = 'OPERADOR' AND estado IN ('PENDIENTE', 'ACTIVA', 'INACTIVA'))
            OR (rol = 'CLIENTE' AND estado IN ('ACTIVA', 'INACTIVA'))
        );
