#!/usr/bin/env bash
set -euo pipefail
umask 077

mkdir -p /fixtures
: > /fixtures/fixture-db-errors.log
chmod 600 /fixtures/fixture-db-errors.log

for intento in $(seq 1 120); do
  if [[ "$(psql -qAt -X -c "SELECT to_regclass('public.vision_ocupacion') IS NOT NULL" 2>/dev/null || true)" == t ]]; then
    break
  fi
  sleep 1
done

if [[ "$(psql -qAt -X -c "SHOW track_commit_timestamp" 2>/dev/null || true)" != on ]]; then
  printf 'PostgreSQL QA no tiene track_commit_timestamp activo.\n' >&2
  exit 4
fi

psql -qAt -X -v ON_ERROR_STOP=1 >>/fixtures/fixture-db-errors.log 2>&1 <<'SQL'
CREATE TABLE IF NOT EXISTS qa_vision_commit_marker (
    observado_en TIMESTAMPTZ NOT NULL,
    cajon_id UUID NOT NULL,
    txid XID NOT NULL,
    PRIMARY KEY (observado_en, cajon_id)
);

ALTER TABLE qa_vision_commit_marker
  ALTER COLUMN txid TYPE XID USING txid::xid;

CREATE OR REPLACE FUNCTION qa_registrar_commit_vision()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $qa$
BEGIN
    INSERT INTO qa_vision_commit_marker (observado_en, cajon_id, txid)
    VALUES (NEW.observado_en, NEW.cajon_id, pg_current_xact_id()::xid)
    ON CONFLICT (observado_en, cajon_id)
    DO UPDATE SET txid = EXCLUDED.txid;
    RETURN NEW;
END
$qa$;

DROP TRIGGER IF EXISTS qa_vision_commit_marker_trigger ON vision_ocupacion;
CREATE TRIGGER qa_vision_commit_marker_trigger
AFTER INSERT OR UPDATE ON vision_ocupacion
FOR EACH ROW EXECUTE FUNCTION qa_registrar_commit_vision();

CREATE TABLE IF NOT EXISTS qa_vision_rollback_control (
    id BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (id),
    armado BOOLEAN NOT NULL DEFAULT FALSE
);
INSERT INTO qa_vision_rollback_control (id, armado)
VALUES (TRUE, FALSE)
ON CONFLICT (id) DO UPDATE SET armado = FALSE;

CREATE OR REPLACE FUNCTION qa_fallar_vision_si_armado()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $qa$
BEGIN
    IF EXISTS (SELECT 1 FROM qa_vision_rollback_control WHERE id AND armado) THEN
        RAISE EXCEPTION 'Fallo de rollback deliberado en la prueba QA.';
    END IF;
    RETURN NEW;
END
$qa$;

DROP TRIGGER IF EXISTS qa_vision_rollback_trigger ON vision_ocupacion;
CREATE TRIGGER qa_vision_rollback_trigger
BEFORE INSERT OR UPDATE ON vision_ocupacion
FOR EACH ROW EXECUTE FUNCTION qa_fallar_vision_si_armado();
SQL

responder() {
  local destino="$1"
  local cuerpo="$2"
  local temporal="$destino.tmp"
  printf '%s' "$cuerpo" >"$temporal"
  mv "$temporal" "$destino"
}

procesar_fixture_archivo() {
  local id accion cajon_id temporal resultado consulta
  temporal="/fixtures/solicitud.processing"
  mv /fixtures/solicitud.json "$temporal"
  local json
  json="$(cat "$temporal")"
  id="$(printf '%s' "$json" | sed -n 's/.*"id":"\([0-9a-fA-F-]\{36\}\)".*/\1/p')"
  accion="$(printf '%s' "$json" | sed -n 's/.*"accion":"\([a-z_]*\)".*/\1/p')"
  cajon_id="$(printf '%s' "$json" | sed -n 's/.*"cajonId":"\([0-9a-fA-F-]\{36\}\)".*/\1/p')"
  if [[ ! "$id" =~ ^[0-9a-fA-F-]{36}$ ]]; then
    rm -f "$temporal"
    return
  fi

  case "$accion" in
    reiniciar_vision)
      consulta="BEGIN; DELETE FROM qa_vision_commit_marker; DELETE FROM vision_solicitud; DELETE FROM vision_ocupacion; DELETE FROM vision_zona; DELETE FROM vision_fuente; DELETE FROM vision_cajon; COMMIT;"
      ;;
    sembrar_estados)
      consulta="DO \$qa\$
      DECLARE fuente UUID; sesion UUID;
      BEGIN
        SELECT fuente_id INTO STRICT fuente FROM vision_fuente
          WHERE revision_calibracion IS NOT NULL
          ORDER BY calibracion_activada_en DESC NULLS LAST LIMIT 1;
        sesion := gen_random_uuid();
        UPDATE vision_fuente SET sesion_id = sesion, sesion_iniciada_en = clock_timestamp(),
          ultima_secuencia = 0, ultimo_observado_en = NULL WHERE fuente_id = fuente;
        DELETE FROM vision_ocupacion WHERE cajon_id IN
          (SELECT cajon_id FROM vision_zona WHERE fuente_id = fuente);
        INSERT INTO vision_ocupacion
          (cajon_id, fuente_id, sesion_id, revision_calibracion, hash_calibracion,
           ultimo_estado, observado_en, recibido_en)
        SELECT z.cajon_id, f.fuente_id, f.sesion_id, f.revision_calibracion, f.hash_calibracion,
          CASE c.etiqueta WHEN 'C01' THEN 'LIBRE' WHEN 'C02' THEN 'OCUPADO' ELSE 'LIBRE' END,
          clock_timestamp(), clock_timestamp()
        FROM vision_zona z
        JOIN vision_cajon c ON c.cajon_id = z.cajon_id
        JOIN vision_fuente f ON f.fuente_id = z.fuente_id
        WHERE z.fuente_id = fuente AND z.activa AND c.etiqueta <> 'C03';
      END
      \$qa\$;"
      ;;
    crear_suelto)
      consulta="WITH creado AS (
        INSERT INTO vision_cajon (cajon_id, estacionamiento_id, etiqueta)
        SELECT gen_random_uuid(), estacionamiento_id, 'Prueba dinámica'
        FROM configuracion_estacionamiento WHERE id = 1 AND estado = 'CONFIGURADA'
        RETURNING cajon_id
      ) SELECT cajon_id FROM creado;"
      ;;
    borrar_suelto)
      if [[ ! "$cajon_id" =~ ^[0-9a-fA-F-]{36}$ ]]; then
        responder "/fixtures/respuesta-$id.json" '{"ok":false}'
        rm -f "$temporal"
        return
      fi
      consulta="DELETE FROM vision_cajon WHERE cajon_id = '$cajon_id'::uuid AND etiqueta = 'Prueba dinámica' RETURNING cajon_id;"
      ;;
    armar_rollback)
      consulta="UPDATE qa_vision_rollback_control SET armado = TRUE WHERE id = TRUE;"
      ;;
    desarmar_rollback)
      consulta="UPDATE qa_vision_rollback_control SET armado = FALSE WHERE id = TRUE;"
      ;;
    *)
      responder "/fixtures/respuesta-$id.json" '{"ok":false}'
      rm -f "$temporal"
      return
      ;;
  esac

  if resultado="$(psql -qAt -X -v ON_ERROR_STOP=1 -c "$consulta" 2>>/fixtures/fixture-db-errors.log)"; then
    if [[ "$accion" == crear_suelto && "$resultado" =~ ^[0-9a-fA-F-]{36}$ ]]; then
      responder "/fixtures/respuesta-$id.json" "{\"ok\":true,\"cajonId\":\"$resultado\"}"
    else
      responder "/fixtures/respuesta-$id.json" '{"ok":true}'
    fi
  else
    responder "/fixtures/respuesta-$id.json" '{"ok":false}'
  fi
  rm -f "$temporal"
}

procesar_consulta_commit() {
  local temporal json id observado_en commit_at consulta
  temporal="/fixtures/consulta-commit.processing"
  mv /fixtures/consulta-commit.json "$temporal"
  json="$(cat "$temporal")"
  id="$(printf '%s' "$json" | sed -n 's/.*"id":"\([0-9a-fA-F-]\{36\}\)".*/\1/p')"
  observado_en="$(printf '%s' "$json" | sed -n 's/.*"observadoEn":"\([0-9T:.Z+-]*\)".*/\1/p')"
  if [[ ! "$id" =~ ^[0-9a-fA-F-]{36}$ || ! "$observado_en" =~ ^[0-9T:.Z+-]+$ ]]; then
    rm -f "$temporal"
    return
  fi
  consulta="SELECT to_char(pg_xact_commit_timestamp(txid) AT TIME ZONE 'UTC',
    'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"')
    FROM qa_vision_commit_marker WHERE observado_en = '$observado_en'::timestamptz
    ORDER BY pg_xact_commit_timestamp(txid) DESC LIMIT 1;"
  if commit_at="$(psql -qAt -X -v ON_ERROR_STOP=1 -c "$consulta" 2>>/fixtures/fixture-db-errors.log)"; then
    if [[ -n "$commit_at" ]]; then
      responder "/fixtures/marca-commit-$id.json" "{\"ok\":true,\"commitAt\":\"$commit_at\"}"
    else
      responder "/fixtures/marca-commit-$id.json" '{"ok":false}'
    fi
  else
    responder "/fixtures/marca-commit-$id.json" '{"ok":false}'
  fi
  rm -f "$temporal"
}

while true; do
  if [[ -f /fixtures/solicitud.json ]]; then
    procesar_fixture_archivo
  fi
  if [[ -f /fixtures/consulta-commit.json ]]; then
    procesar_consulta_commit
  fi
  sleep 0.05
done
