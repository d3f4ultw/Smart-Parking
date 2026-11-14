SELECT cuenta.id
FROM cliente_codigo_publico AS codigo
JOIN cuenta ON cuenta.id = codigo.cliente_id
WHERE codigo.cliente_id = ?
FOR UPDATE OF codigo, cuenta
