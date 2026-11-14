SELECT EXISTS (
    SELECT 1
    FROM asociacion_tarjeta_rfid1
    WHERE empleado_id = ? AND estado = 'ACTIVA'
)
