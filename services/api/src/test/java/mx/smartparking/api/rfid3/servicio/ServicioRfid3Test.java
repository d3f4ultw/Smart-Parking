package mx.smartparking.api.rfid3.servicio;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import java.util.Arrays;
import java.util.UUID;
import mx.smartparking.api.configuracion.ErrorConfiguracion;
import mx.smartparking.api.rfid3.persistencia.LecturaRfid3ConflictException;
import mx.smartparking.api.rfid3.persistencia.RepositorioRfid3;
import mx.smartparking.api.rfid3.persistencia.ResultadoSalidaRfid3;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.http.HttpStatus;

class ServicioRfid3Test {

    private static final String UID = "abcdef12";
    private static final String LECTURA = "550e8400-e29b-41d4-a716-446655440000";

    @Test
    void normalizaIdentificadoresYDevuelveLaDecisionPersistida() {
        RepositorioRfid3 repositorio = mock(RepositorioRfid3.class);
        ResultadoSalidaRfid3 confirmado = ResultadoSalidaRfid3.autorizada();
        when(repositorio.registrarSalida("ABCDEF12", UUID.fromString(LECTURA))).thenReturn(confirmado);

        ResultadoSalidaRfid3 resultado = new ServicioRfid3(repositorio).registrarSalida(UID, LECTURA.toUpperCase());

        assertSame(confirmado, resultado);
        verify(repositorio).registrarSalida("ABCDEF12", UUID.fromString(LECTURA));
    }

    @Test
    void rechazaDatosInvalidosSinConsultarPersistencia() {
        RepositorioRfid3 repositorio = mock(RepositorioRfid3.class);
        ServicioRfid3 servicio = new ServicioRfid3(repositorio);
        for (String uid : Arrays.asList(null, "", "ABC", "ABCDEF1G", " ABCDEF12", "ABCDEF120")) {
            ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class,
                    () -> servicio.registrarSalida(uid, LECTURA));
            assertEquals(HttpStatus.BAD_REQUEST, error.estadoHttp());
        }
        for (String lectura : Arrays.asList(null, "", "550e8400e29b41d4a716446655440000",
                "550e8400-e29b-41d4-a716-44665544000z")) {
            ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class,
                    () -> servicio.registrarSalida(UID, lectura));
            assertEquals(HttpStatus.BAD_REQUEST, error.estadoHttp());
        }
        verifyNoInteractions(repositorio);
    }

    @Test
    void conflictoConfirmadoSeTraduceA409SinIdentificadores() {
        RepositorioRfid3 repositorio = mock(RepositorioRfid3.class);
        when(repositorio.registrarSalida("ABCDEF12", UUID.fromString(LECTURA)))
                .thenThrow(new LecturaRfid3ConflictException());

        ErrorConfiguracion error = assertThrows(ErrorConfiguracion.class,
                () -> new ServicioRfid3(repositorio).registrarSalida(UID, LECTURA));

        assertEquals(HttpStatus.CONFLICT, error.estadoHttp());
        assertEquals("LECTURA_EN_CONFLICTO", error.codigo());
        assertEquals("La lectura no se pudo confirmar.", error.getMessage());
    }

    @Test
    void errorDePersistenciaNoSeConvierteEnAutorizacion() {
        RepositorioRfid3 repositorio = mock(RepositorioRfid3.class);
        when(repositorio.registrarSalida("ABCDEF12", UUID.fromString(LECTURA)))
                .thenThrow(new DataAccessResourceFailureException("fallo de prueba"));

        assertThrows(DataAccessResourceFailureException.class,
                () -> new ServicioRfid3(repositorio).registrarSalida(UID, LECTURA));
    }
}
