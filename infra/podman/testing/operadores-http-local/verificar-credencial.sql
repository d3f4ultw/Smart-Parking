\getenv correo_operador TEST_OPERATOR_EMAIL
\getenv contrasena_inicial TEST_OPERATOR_PASSWORD_INITIAL
\getenv contrasena_final TEST_OPERATOR_PASSWORD_FINAL

SELECT count(*) = 1
           AND bool_and(
               left(hash_contrasena_acceso, length('{pbkdf2@SpringSecurity_v5_8_600k}'))
                   = '{pbkdf2@SpringSecurity_v5_8_600k}'
               AND hash_contrasena_acceso <> :'contrasena_inicial'
               AND hash_contrasena_acceso <> :'contrasena_final')
           AS una_cuenta_activa_con_hash_versionado
FROM cuenta
WHERE correo_normalizado = lower(:'correo_operador')
  AND rol = 'OPERADOR'
  AND estado = 'ACTIVA';
