#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

raiz="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
directorio_unidades="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
unidades=(smartparking-vision-adb.service smartparking-vision-runtime-path.service smartparking-vision.service)
accion="${1:-ayuda}"

uso() {
  cat <<'EOF'
Uso: infra/vision/gestionar_servicios_usuario.sh {instalar|iniciar|detener|desinstalar|ayuda}

instalar    Copia las unidades sin reemplazar archivos distintos; habilita el supervisor USB y prepara la ruta efímera.
iniciar     Inicia primero el supervisor USB y luego el servicio Vision.
detener     Detiene Vision y después el supervisor USB.
desinstalar Detiene/deshabilita los servicios y retira solo unidades idénticas.

Vision queda deshabilitado para el arranque automático. El preparador solo crea
el directorio privado que necesitan los controles manuales de Podman; no inicia
el contenedor. Use `iniciar` o el acceso de escritorio cuando quiera arrancarlo.
Para ejecutar las unidades auxiliares antes del login, habilite lingering para el usuario.
La vista gráfica de calibración pausa y reanuda smartparking-vision.service automáticamente.
EOF
}

if [[ "$accion" == ayuda || "$accion" == --help || "$accion" == -h ]]; then
  uso
  exit 0
fi

command -v systemctl >/dev/null || { echo 'Falta systemctl.' >&2; exit 1; }

case "$accion" in
  instalar)
    if [[ ! -d "$directorio_unidades" ]]; then
      mkdir -p "$directorio_unidades"
      chmod 700 "$directorio_unidades"
    fi
    for unidad in "${unidades[@]}"; do
      origen="$raiz/infra/podman/systemd/$unidad"
      destino="$directorio_unidades/$unidad"
      if [[ -e "$destino" ]]; then
        cmp -s -- "$origen" "$destino" || { echo "La unidad existente $unidad difiere; no se reemplazó." >&2; exit 1; }
      else
        install -m 644 -- "$origen" "$destino"
      fi
    done
    systemctl --user daemon-reload
    systemctl --user enable smartparking-vision-adb.service
    systemctl --user enable --now smartparking-vision-runtime-path.service
    systemctl --user disable smartparking-vision.service
    ;;
  iniciar)
    systemctl --user start smartparking-vision-runtime-path.service
    systemctl --user start smartparking-vision-adb.service
    systemctl --user start smartparking-vision.service
    ;;
  detener)
    systemctl --user stop smartparking-vision.service
    systemctl --user stop smartparking-vision-adb.service
    ;;
  desinstalar)
    systemctl --user stop smartparking-vision.service
    systemctl --user stop smartparking-vision-adb.service
    systemctl --user stop smartparking-vision-runtime-path.service
    systemctl --user disable "${unidades[@]}"
    for unidad in "${unidades[@]}"; do
      origen="$raiz/infra/podman/systemd/$unidad"
      destino="$directorio_unidades/$unidad"
      if [[ -f "$destino" ]] && cmp -s -- "$origen" "$destino"; then
        rm -- "$destino"
      fi
    done
    systemctl --user daemon-reload
    ;;
  *) uso >&2; exit 2 ;;
esac
