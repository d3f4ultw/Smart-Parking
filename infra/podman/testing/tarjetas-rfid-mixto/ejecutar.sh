#!/usr/bin/env bash
set -euo pipefail

raiz="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$raiz"
compose_stage2="infra/podman/testing/tarjetas-rfid-stage2/compose.yaml"

leer_contenedores_persistentes() {
    local ids id estado
    ids="$(podman ps -a --filter label=com.docker.compose.project=smartparking --format '{{.ID}}')" || return 1
    while IFS= read -r id; do
        [[ -z "$id" ]] && continue
        estado="$(podman inspect --format '{{.Id}} {{.Name}} {{.Image}} {{.Config.Image}} {{.State.Status}}' "$id")" || return 1
        printf '%s\n' "$estado"
    done < <(printf '%s\n' "$ids" | sort)
}

leer_volumenes_persistentes() {
    local nombres nombre estado
    nombres="$(podman volume ls --format '{{.Name}}')" || return 1
    while IFS= read -r nombre; do
        [[ -z "$nombre" ]] && continue
        estado="$(podman volume inspect --format '{{.Name}} {{.CreatedAt}}' "$nombre")" || return 1
        printf '%s\n' "$estado"
    done < <(printf '%s\n' "$nombres" | awk 'index($0, "smartparking_") == 1' | sort)
}

leer_redes_persistentes() {
    local nombres nombre estado
    nombres="$(podman network ls --format '{{.Name}}')" || return 1
    while IFS= read -r nombre; do
        [[ -z "$nombre" ]] && continue
        estado="$(podman network inspect --format '{{.Name}} {{.Id}}' "$nombre")" || return 1
        printf '%s\n' "$estado"
    done < <(printf '%s\n' "$nombres" | awk 'index($0, "smartparking_") == 1' | sort)
}

contenedores_antes="$(leer_contenedores_persistentes)"
volumenes_antes="$(leer_volumenes_persistentes)"
redes_antes="$(leer_redes_persistentes)"

unset POSTGRES_URL POSTGRES_HOST POSTGRES_PORT POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD
unset SPRING_DATASOURCE_URL SPRING_DATASOURCE_USERNAME SPRING_DATASOURCE_PASSWORD
unset SPRING_PROFILES_ACTIVE RFID1_TOKEN_SHA256 SMARTPARKING_RFID1_TOKEN RFID1_TOKEN

echo "Verificando formato de los nuevos specs dentro de Podman."
bash infra/podman/testing/tarjetas-rfid-mixto/verificar-formato-specs.sh

echo "Ejecutando pruebas API focalizadas, sin acceso a PostgreSQL."
mvn -o -f services/api/pom.xml \
    -Dtest=ServicioTarjetasRfid1Test,RepositorioTarjetasRfidJdbcTest,ServicioEstadoConexionRfid1Test,ControladorEstadoConexionRfid1SeguridadTest \
    test

echo "Empaquetando la API actual para la instancia desechable."
mvn -o -f services/api/pom.xml -DskipTests package

echo "Ejecutando pruebas RFID1 con serial simulado, sin hardware."
for modulo in test_cliente_capturas.py test_estado_dispositivo.py test_heartbeat_bridge.py test_bridge_pty.py; do
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=infra/rfid1-bridge \
        python3 -m unittest discover -s infra/rfid1-bridge/tests -p "$modulo"
done

echo "Ejecutando navegación, MIXTO y conexión con personas elegibles en PostgreSQL desechable."
bash infra/podman/testing/tarjetas-rfid-stage2/ejecutar.sh \
    tarjetas-rfid/01-directorio.spec.ts \
    tarjetas-rfid/07-mixto.spec.ts \
    tarjetas-rfid/08-conexion-rfid1.spec.ts

echo "Ejecutando compatibilidad de asociación en una segunda base desechable."
bash infra/podman/testing/tarjetas-rfid-stage2/ejecutar.sh \
    tarjetas-rfid/02-asociacion.spec.ts

contenedores_despues="$(leer_contenedores_persistentes)" || exit 1
volumenes_despues="$(leer_volumenes_persistentes)" || exit 1
redes_despues="$(leer_redes_persistentes)" || exit 1

if [[ "$contenedores_despues" != "$contenedores_antes" \
    || "$volumenes_despues" != "$volumenes_antes" \
    || "$redes_despues" != "$redes_antes" ]]; then
    echo "Cambió un contenedor, volumen o red persistente SmartParking; no se intenta revertirlo." >&2
    exit 1
fi

echo "PASS: pruebas focalizadas MIXTO/RFID1 completadas en servicios desechables o simulados."
echo "PASS: contenedores, volúmenes y redes persistentes SmartParking conservados."
