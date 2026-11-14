-- Bloquea escrituras de cuenta durante el backfill y la instalación del trigger.
LOCK TABLE cuenta IN SHARE ROW EXCLUSIVE MODE;

CREATE TABLE cliente_codigo_publico (
    cliente_id UUID PRIMARY KEY,
    numero BIGINT GENERATED ALWAYS AS IDENTITY,
    CONSTRAINT cliente_codigo_publico_cliente_fk
        FOREIGN KEY (cliente_id) REFERENCES cuenta(id) ON DELETE RESTRICT,
    CONSTRAINT cliente_codigo_publico_numero_uq UNIQUE (numero),
    CONSTRAINT cliente_codigo_publico_numero_ck CHECK (numero > 0)
);

INSERT INTO cliente_codigo_publico (cliente_id, numero) OVERRIDING SYSTEM VALUE
SELECT id, ROW_NUMBER() OVER (ORDER BY creada_en ASC, id ASC)::BIGINT
FROM cuenta
WHERE rol = 'CLIENTE';

SELECT setval(
    pg_get_serial_sequence('cliente_codigo_publico', 'numero'),
    COALESCE(MAX(numero), 1),
    MAX(numero) IS NOT NULL
)
FROM cliente_codigo_publico;

CREATE FUNCTION asignar_codigo_publico_cliente() RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.rol = 'CLIENTE' THEN
        INSERT INTO cliente_codigo_publico (cliente_id) VALUES (NEW.id);
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER cuenta_cliente_codigo_publico_ai
AFTER INSERT ON cuenta
FOR EACH ROW
WHEN (NEW.rol = 'CLIENTE')
EXECUTE FUNCTION asignar_codigo_publico_cliente();
