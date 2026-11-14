package mx.smartparking.ownerconsole.servicio;

import static mx.smartparking.ownerconsole.servicio.JavaFxPropietarioTestSupport.*;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import javafx.scene.Node;
import javafx.scene.Scene;
import javafx.scene.control.ComboBox;
import javafx.scene.control.ToggleButton;
import javafx.scene.layout.StackPane;
import javafx.stage.Stage;
import javafx.stage.Window;
import mx.smartparking.ownerconsole.controlador.ControladorAplicacion;
import mx.smartparking.ownerconsole.controlador.EjecutorJavaFx;
import mx.smartparking.ownerconsole.controlador.configuracion.ControladorAsistenteConfiguracion;
import mx.smartparking.ownerconsole.controlador.panel.ControladorPanelPropietario;
import mx.smartparking.ownerconsole.controlador.sesion.ControladorSesionPropietario;
import mx.smartparking.ownerconsole.modelo.PasoConfiguracion;
import mx.smartparking.ownerconsole.vista.VistaAcceso;
import mx.smartparking.ownerconsole.vista.VistaPanel;
import mx.smartparking.ownerconsole.vista.configuracion.VistaAsistente;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

/** Interacción JavaFX programática con API sintética de loopback; no usa la API persistente. */
final class InteraccionJavaFxPropietarioTest {

    @BeforeAll
    static void iniciarJavaFx() throws Exception {
        JavaFxPropietarioTestSupport.iniciarJavaFx();
    }

    @AfterAll
    static void cerrarJavaFx() {
        JavaFxPropietarioTestSupport.cerrarJavaFx();
    }

    @BeforeEach
    void compruebaQueNoQuedenVentanasVisibles() throws Exception {
        assertTrue(fx(() -> Window.getWindows().stream().noneMatch(Window::isShowing)),
                "Cada prueba debe empezar sin ventanas de pruebas anteriores");
    }

    @AfterEach
    void cierraLasVentanasAunqueLaPruebaFalle() throws Exception {
        fx(() -> List.copyOf(Window.getWindows()).forEach(Window::hide));
        assertTrue(fx(() -> Window.getWindows().stream().noneMatch(Window::isShowing)),
                "La limpieza debe cerrar todas las ventanas de la prueba");
    }

    @Test
    void recorreElAsistenteCompletoValidaConservaYLimpiaSecretos() throws Exception {
        try (EjecutorJavaFx ejecutor = new EjecutorJavaFx(); ApiPropietarioSintetica api = new ApiPropietarioSintetica()) {
            AtomicReference<Node> vistaMostrada = new AtomicReference<>();
            AtomicReference<String> avisoFinal = new AtomicReference<>();
            ControladorAsistenteConfiguracion controlador = new ControladorAsistenteConfiguracion(
                    new ClienteApi(api.uri()).configuracion(),
                    new MapeadorSolicitudConfiguracion(),
                    ejecutor,
                    vistaMostrada::set,
                    avisoFinal::set,
                    ignorado -> { },
                    () -> { });

            fx(controlador::iniciar);
            VistaAsistente asistente = assertInstanceOf(vistaMostrada.get(), VistaAsistente.class);
            Stage escenario = fx((java.util.concurrent.Callable<Stage>) Stage::new);
            fx(() -> {
                escenario.setScene(new Scene(asistente, 900, 700));
                escenario.show();
            });
            assertEquals(6, asistente.cantidadPasos());
            assertEquals(PasoConfiguracion.IDENTIDAD, asistente.pasoActual());

            fx(() -> boton(asistente, "Siguiente").fire());
            assertEquals(0, asistente.indice(), "No debe avanzar si falta la identidad");
            assertTrue(campoTexto(asistente, "Nombres").getStyleClass().contains("campo-invalido"));

            fx(() -> {
                campoTexto(asistente, "Nombres").setText("María");
                campoTexto(asistente, "Primer apellido").setText("Pérez");
                boton(asistente, "Siguiente").fire();
            });
            assertEquals(PasoConfiguracion.ACCESO, asistente.pasoActual());

            fx(() -> {
                campoTexto(asistente, "Correo electrónico").setText("propietaria@example.test");
                campoContrasena(asistente, "Contraseña").setText("123456789");
                assertTrue(textoVisible(asistente).contains("Elige una contraseña más larga"));
                campoContrasena(asistente, "Contraseña").setText("1234567890");
                assertTrue(textoVisible(asistente).contains("La contraseña es suficientemente larga."));
                campoContrasena(asistente, "Contraseña").setText(CLAVE_ACCESO);
                ToggleButton ojo = botonOjo(asistente, "Mostrar la contraseña de acceso");
                ojo.fire();
                assertTrue(controlConOjo(asistente, "Contraseña").visible().isVisible());
                assertEquals(CLAVE_ACCESO, controlConOjo(asistente, "Contraseña").visible().getText());
                boton(asistente, "Siguiente").fire();
            });
            assertEquals(PasoConfiguracion.ADMINISTRACION, asistente.pasoActual());

            fx(() -> {
                campoContrasena(asistente, "Contraseña").setText(CLAVE_ADMINISTRATIVA);
                campoContrasena(asistente, "Confirmar contraseña").setText(CLAVE_ADMINISTRATIVA);
                assertTrue(textoVisible(asistente).contains("Es diferente a la de acceso"));
                assertTrue(textoVisible(asistente).contains("Las contraseñas coinciden"));
                boton(asistente, "Siguiente").fire();
            });
            assertEquals(PasoConfiguracion.ESTACIONAMIENTO, asistente.pasoActual());

            fx(() -> {
                campoTexto(asistente, "Nombre del estacionamiento").setText("Estacionamiento sintético");
                ComboBox<?> tipo = combo(asistente, "Tipo de estacionamiento");
                tipo.getSelectionModel().selectFirst();
                boton(asistente, "Siguiente").fire();
            });
            assertEquals(PasoConfiguracion.HORARIO, asistente.pasoActual());

            fx(() -> {
                boton(asistente, "Horario fijo todos los días").fire();
                campoTexto(asistente, "Zona horaria").setText("America/Mexico_City");
                campoTexto(asistente, "Apertura").setText("08:15");
                campoTexto(asistente, "Cierre").setText("21:15");
                boton(asistente, "Siguiente").fire();
            });
            assertEquals(PasoConfiguracion.REVISION, asistente.pasoActual());
            String revision = fx(() -> textoVisible(asistente));
            assertTrue(revision.contains("María Pérez"));
            assertTrue(revision.contains("propietaria@example.test"));
            assertTrue(revision.contains("Estacionamiento sintético"));
            assertFalse(revision.contains(CLAVE_ACCESO));
            assertFalse(revision.contains(CLAVE_ADMINISTRATIVA));

            fx(() -> boton(asistente, "Anterior").fire());
            assertEquals(PasoConfiguracion.HORARIO, asistente.pasoActual());
            assertEquals("America/Mexico_City", fx(() -> campoTexto(asistente, "Zona horaria").getText()));
            fx(() -> boton(asistente, "Siguiente").fire());
            assertEquals(PasoConfiguracion.REVISION, asistente.pasoActual());

            fx(() -> controlador.completar("DESCONOCIDO"));
            assertEquals(
                    "La configuración está lista y ya puedes entrar. "
                            + "Si no encuentras el mensaje de bienvenida, revisa el correo no deseado.",
                    avisoFinal.get());
            fx(() -> {
                asistente.mostrarPaso(PasoConfiguracion.ACCESO.ordinal());
                assertEquals("", campoContrasena(asistente, "Contraseña").getText());
                asistente.mostrarPaso(PasoConfiguracion.ADMINISTRACION.ordinal());
                assertEquals("", campoContrasena(asistente, "Contraseña").getText());
                assertEquals("", campoContrasena(asistente, "Confirmar contraseña").getText());
            });
            fx(escenario::close);
        }
    }

    @Test
    void loginMuestraValidacionesGenericasOcultaYLimpiaLaContrasena() throws Exception {
        try (EjecutorJavaFx ejecutor = new EjecutorJavaFx(); ApiPropietarioSintetica api = new ApiPropietarioSintetica()) {
            AtomicReference<Node> vistaMostrada = new AtomicReference<>();
            AtomicReference<String> accesoExitoso = new AtomicReference<>();
            ControladorSesionPropietario controlador = new ControladorSesionPropietario(
                    new ClienteApi(api.uri()).sesion(),
                    ejecutor,
                    vistaMostrada::set,
                    accesoExitoso::set,
                    ignorado -> { });

            fx(() -> controlador.mostrarAcceso(""));
            VistaAcceso acceso = assertInstanceOf(vistaMostrada.get(), VistaAcceso.class);
            fx(() -> boton(acceso, "Iniciar sesión").fire());
            assertTrue(textoVisible(acceso).contains("Este campo es obligatorio."));
            assertTrue(campoTexto(acceso, "Correo electrónico").getStyleClass().contains("campo-invalido"));

            fx(() -> {
                campoTexto(acceso, "Correo electrónico").setText("correo-invalido");
                boton(acceso, "Iniciar sesión").fire();
            });
            assertTrue(textoVisible(acceso).contains("Ingresa un correo válido."));

            fx(() -> {
                campoTexto(acceso, "Correo electrónico").setText("duena@example.test");
                campoContrasena(acceso, "Contraseña").setText(CLAVE_ACCESO);
                ToggleButton ojo = botonOjo(acceso, "Mostrar la contraseña");
                ojo.fire();
                assertTrue(controlConOjo(acceso, "Contraseña").visible().isVisible());
                boton(acceso, "Iniciar sesión").fire();
                assertEquals("", campoContrasena(acceso, "Contraseña").getText(),
                        "La vista debe limpiar el secreto antes de iniciar la solicitud");
            });

            assertTrue(esperar(() -> api.iniciosSesion.get() == 1), "El login debe llegar a la API sintética");
            assertTrue(esperar(() -> fx(() -> textoVisible(acceso).contains("Correo o contraseña incorrectos."))));
            assertFalse(fx(() -> textoVisible(acceso)).contains(CLAVE_ACCESO));
            assertFalse(fx(() -> acceso.isDisabled()));
            assertNull(accesoExitoso.get(), "La API sintética rechaza credenciales sin autenticar al usuario");
        }
    }

    @Test
    void operadorNoAbreElPanelYDespuesUnDuenoPuedeIniciarSesion() throws Exception {
        try (EjecutorJavaFx ejecutor = new EjecutorJavaFx(); ApiPropietarioSintetica api = new ApiPropietarioSintetica()) {
            String operador = "{\"autenticada\":true,\"rol\":\"OPERADOR\","
                    + "\"correo\":\"operador@example.test\",\"revisionPropietario\":2,"
                    + "\"csrfToken\":\"token-sintetico\"}";
            String dueno = "{\"autenticada\":true,\"rol\":\"DUENO\","
                    + "\"correo\":\"duena@example.test\",\"revisionPropietario\":2,"
                    + "\"csrfToken\":\"token-sintetico\"}";
            api.respuestaConsultaSesion.set(operador);
            api.respuestaInicioSesion.set(operador);
            AtomicReference<Node> vistaMostrada = new AtomicReference<>();
            AtomicInteger intentosPanel = new AtomicInteger();
            ControladorSesionPropietario controlador = new ControladorSesionPropietario(
                    new ClienteApi(api.uri()).sesion(),
                    ejecutor,
                    vistaMostrada::set,
                    ignorado -> intentosPanel.incrementAndGet(),
                    ignorado -> { });

            fx(controlador::comprobarSesion);
            assertTrue(esperar(() -> api.consultasSesion.get() == 1 && vistaMostrada.get() instanceof VistaAcceso));
            VistaAcceso primerAcceso = assertInstanceOf(vistaMostrada.get(), VistaAcceso.class);
            fx(controlador::comprobarSesion);
            assertTrue(esperar(() -> api.consultasSesion.get() == 2
                    && vistaMostrada.get() instanceof VistaAcceso && vistaMostrada.get() != primerAcceso));
            VistaAcceso acceso = assertInstanceOf(vistaMostrada.get(), VistaAcceso.class);
            assertEquals(0, intentosPanel.get(), "Una sesión OPERADOR no debe intentar abrir el panel");

            fx(() -> {
                campoTexto(acceso, "Correo electrónico").setText("operador@example.test");
                campoContrasena(acceso, "Contraseña").setText(CLAVE_ACCESO);
                boton(acceso, "Iniciar sesión").fire();
            });
            assertTrue(esperar(() -> api.iniciosSesion.get() == 1
                    && fx(() -> textoVisible(acceso).contains("Correo o contraseña incorrectos."))));
            assertEquals(0, intentosPanel.get(), "El login OPERADOR tampoco debe abrir el panel");

            api.respuestaInicioSesion.set(dueno);
            fx(() -> {
                campoTexto(acceso, "Correo electrónico").setText("duena@example.test");
                campoContrasena(acceso, "Contraseña").setText(CLAVE_ACCESO);
                boton(acceso, "Iniciar sesión").fire();
            });
            assertTrue(esperar(() -> intentosPanel.get() == 1));
            assertEquals(2, api.iniciosSesion.get());
            assertTrue(api.cookieUltimoInicio.get().contains("OWNERSESSION=sesion-sintetica"),
                    "El siguiente login debe poder avanzar con la cookie anterior");
        }
    }

    @Test
    void respuestaDeSesionMalformadaNoSolicitaElPanel() throws Exception {
        try (EjecutorJavaFx ejecutor = new EjecutorJavaFx(); ApiPropietarioSintetica api = new ApiPropietarioSintetica()) {
            api.respuestaConsultaSesion.set("{}");
            api.respuestaInicioSesion.set("{}");
            AtomicReference<Node> vistaMostrada = new AtomicReference<>();
            AtomicInteger intentosPanel = new AtomicInteger();
            ControladorSesionPropietario controlador = new ControladorSesionPropietario(
                    new ClienteApi(api.uri()).sesion(),
                    ejecutor,
                    vistaMostrada::set,
                    ignorado -> intentosPanel.incrementAndGet(),
                    ignorado -> { });

            fx(controlador::comprobarSesion);
            assertTrue(esperar(() -> api.consultasSesion.get() == 1 && vistaMostrada.get() instanceof VistaAcceso));
            VistaAcceso acceso = assertInstanceOf(vistaMostrada.get(), VistaAcceso.class);
            fx(() -> {
                campoTexto(acceso, "Correo electrónico").setText("duena@example.test");
                campoContrasena(acceso, "Contraseña").setText(CLAVE_ACCESO);
                boton(acceso, "Iniciar sesión").fire();
            });
            assertTrue(esperar(() -> api.iniciosSesion.get() == 1
                    && fx(() -> textoVisible(acceso).contains("Correo o contraseña incorrectos."))));
            assertEquals(0, intentosPanel.get());
        }
    }

    @Test
    void apiNoDisponibleAlInicioMuestraLaVistaDeConexionYPermiteReintentar() throws Exception {
        try (ApiPropietarioSintetica api = new ApiPropietarioSintetica()) {
            Stage escenario = fx((java.util.concurrent.Callable<Stage>) Stage::new);
            StackPane raiz = fx((java.util.concurrent.Callable<StackPane>) StackPane::new);
            ControladorAplicacion aplicacion = fx(() -> new ControladorAplicacion(
                    escenario, raiz, new ClienteApi(api.uri())));
            try {
                fx(() -> {
                    escenario.setScene(new Scene(raiz, 900, 620));
                    escenario.show();
                    aplicacion.iniciar();
                });
                assertTrue(esperar(() -> fx(() -> textoVisible(raiz)
                        .contains("Smart Parking no está disponible ahora. Inténtalo de nuevo más tarde."))));
                assertEquals(1, api.consultasEstado.get());
                assertTrue(fx(() -> raiz.getChildren().size() == 1));
                fx(() -> boton(raiz, "Intentar de nuevo").fire());
                assertTrue(esperar(() -> api.consultasEstado.get() == 2));
                assertTrue(esperar(() -> fx(() -> textoVisible(raiz)
                        .contains("Smart Parking no está disponible ahora. Inténtalo de nuevo más tarde."))));
            } finally {
                fx(() -> {
                    aplicacion.cerrar();
                    escenario.close();
                });
            }
        }
    }

    @Test
    void panelEditaSuprimeCambiosSinDiferenciasYRecuperaErrores() throws Exception {
        try (EjecutorJavaFx ejecutor = new EjecutorJavaFx(); ApiPropietarioSintetica api = new ApiPropietarioSintetica()) {
            AtomicReference<Node> vistaMostrada = new AtomicReference<>();
            CountDownLatch panelListo = new CountDownLatch(1);
            ControladorPanelPropietario controlador = new ControladorPanelPropietario(
                    new ClienteApi(api.uri()).configuracion(),
                    ejecutor,
                    vista -> {
                        vistaMostrada.set(vista);
                        panelListo.countDown();
                    },
                    ignorado -> { },
                    ignorado -> { },
                    (datos, vista) -> { },
                    vista -> { },
                    ignorado -> { });
            Stage escenario = fx((java.util.concurrent.Callable<Stage>) Stage::new);
            try {
                fx(() -> controlador.cargarPanel(null));
                assertTrue(panelListo.await(ESPERA_UI.toSeconds(), TimeUnit.SECONDS));
                VistaPanel panel = assertInstanceOf(vistaMostrada.get(), VistaPanel.class);
                fx(() -> {
                    escenario.setScene(new Scene(panel, 900, 620));
                    escenario.show();
                });

                assertTrue(fx(() -> textoVisible(panel).contains("Ciudad de México")));
                assertFalse(fx(() -> textoVisible(panel).contains("Reemplazar propietario")),
                        "La interfaz aprobada mantiene oculta la opción de reemplazo");

                fx(() -> {
                    boton(panel, "Cambiar nombre").fire();
                    boton(panel, "Guardar").fire();
                    abrirEditorYGuardar(panel, escenario, false);
                });
                assertEquals(0, api.mutacionesNombre.get());
                assertEquals(0, api.mutacionesDatos.get(), "El tipo y horario sin cambios no envían PATCH");
                assertEquals(1, api.consultasPanel.get());

                fx(() -> abrirEditorYGuardar(panel, escenario, true));
                assertTrue(esperar(() -> api.mutacionesDatos.get() == 1), "El cambio debe enviar un PATCH");
                assertTrue(esperar(() -> fx(() -> textoVisible(panel).contains("Tipo y horario actualizados."))));
                assertEquals("\"4\"", api.ifMatchDatos.get());
                assertEquals("token-sintetico", api.csrfDatos.get());
                assertTrue(api.cuerpoDatos.get().contains("\"tipo\""));
                assertFalse(api.cuerpoDatos.get().contains("MIXTO"));
                assertTrue(api.cuerpoDatos.get().contains("\"zonaHoraria\":\"America/Mexico_City\""));
                assertTrue(api.cuerpoDatos.get().contains("\"horaApertura\":\"22:00\""));
                assertTrue(api.cuerpoDatos.get().contains("\"horaCierre\":\"06:00\""));
                assertTrue(fx(() -> textoVisible(panel).contains(api.etiquetaTipoActualizada.get())));

                Thread.sleep(1_700);
                assertFalse(fx(() -> textoVisible(panel).contains("Tipo y horario actualizados.")),
                        "El aviso exitoso desaparece tras 1.5 segundos");

                fx(() -> {
                    boton(panel, "Cambiar nombre").fire();
                    campoPorPrompt(panel, "Nombre del estacionamiento").setText("Nombre sintético rechazado");
                    boton(panel, "Guardar").fire();
                });
                assertTrue(esperar(() -> api.mutacionesNombre.get() == 1));
                assertTrue(esperar(() -> fx(() -> textoVisible(panel).contains("El nombre sintético fue rechazado."))));
                Thread.sleep(1_700);
                assertTrue(fx(() -> textoVisible(panel).contains("El nombre sintético fue rechazado.")),
                        "Los errores permanecen visibles hasta que el usuario retoma la edición");
                assertFalse(fx(() -> boton(panel, "Editar tipo y horario").isDisabled()));
            } finally {
                fx(escenario::close);
            }
        }
    }

}
