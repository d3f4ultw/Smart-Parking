package mx.smartparking.ownerconsole.vista.configuracion;

import java.time.ZoneId;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;
import javafx.geometry.Side;
import javafx.scene.control.ContextMenu;
import javafx.scene.control.MenuItem;
import javafx.scene.control.TextField;

/** Campo de zona IANA con sugerencias filtrables por nombre. */
public final class SelectorZonaHoraria extends TextField {

    private final List<String> zonas = ZoneId.getAvailableZoneIds().stream()
            .sorted(Comparator.naturalOrder())
            .toList();
    private final ContextMenu sugerencias = new ContextMenu();

    public SelectorZonaHoraria() {
        setPromptText("Busca tu zona horaria");
        textProperty().addListener((observable, anterior, consulta) -> actualizarSugerencias(consulta));
        focusedProperty().addListener((observable, anterior, enfocada) -> {
            if (enfocada) {
                actualizarSugerencias(getText());
            } else {
                sugerencias.hide();
            }
        });
        setOnAction(evento -> confirmar());
    }

    public void ocultarSugerencias() {
        sugerencias.hide();
    }

    private void actualizarSugerencias(String consulta) {
        if (!isFocused()) {
            return;
        }
        String texto = consulta == null ? "" : consulta.trim();
        if (zonas.contains(texto)) {
            sugerencias.hide();
            return;
        }

        List<String> coincidencias;
        if (texto.isBlank()) {
            coincidencias = List.of(
                    "America/Mexico_City",
                    "America/Cancun",
                    "America/Monterrey",
                    "America/Tijuana",
                    "UTC").stream()
                    .filter(zonas::contains)
                    .toList();
        } else {
            String busqueda = texto.toLowerCase(Locale.ROOT);
            coincidencias = zonas.stream()
                    .filter(zona -> zona.toLowerCase(Locale.ROOT).contains(busqueda))
                    .sorted(Comparator
                            .comparing((String zona) -> !zona.toLowerCase(Locale.ROOT).startsWith(busqueda))
                            .thenComparing(Comparator.naturalOrder()))
                    .limit(12)
                    .toList();
        }

        sugerencias.getItems().setAll(coincidencias.stream().map(this::crearSugerencia).toList());
        if (sugerencias.getItems().isEmpty()) {
            sugerencias.hide();
        } else if (!sugerencias.isShowing()) {
            sugerencias.show(this, Side.BOTTOM, 0, 0);
        }
    }

    private MenuItem crearSugerencia(String zona) {
        MenuItem sugerencia = new MenuItem(zona);
        sugerencia.setOnAction(evento -> seleccionar(zona));
        return sugerencia;
    }

    private void confirmar() {
        String zona = getText().trim();
        if (zonas.contains(zona)) {
            sugerencias.hide();
        } else if (!sugerencias.getItems().isEmpty()) {
            seleccionar(sugerencias.getItems().getFirst().getText());
        }
    }

    private void seleccionar(String zona) {
        sugerencias.hide();
        setText(zona);
        positionCaret(zona.length());
        requestFocus();
    }
}
