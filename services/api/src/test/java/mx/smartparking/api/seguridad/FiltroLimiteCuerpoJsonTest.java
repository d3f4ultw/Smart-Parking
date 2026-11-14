package mx.smartparking.api.seguridad;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicBoolean;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

class FiltroLimiteCuerpoJsonTest {

    @Test
    void aceptaCuerpoJsonDeUnMiB() throws Exception {
        var request = request(FiltroLimiteCuerpoJson.MAXIMO_BYTES);
        var response = new MockHttpServletResponse();
        AtomicBoolean continued = new AtomicBoolean();

        new FiltroExpuesto().doFilter(request, response, (req, res) -> {
            continued.set(true);
            assertEquals(FiltroLimiteCuerpoJson.MAXIMO_BYTES, req.getInputStream().readAllBytes().length);
        });

        assertTrue(continued.get());
        assertEquals(200, response.getStatus());
    }

    @Test
    void rechazaCuerpoJsonQueExcedeUnMiBAunqueNoDeclareLongitud() throws Exception {
        var request = request(FiltroLimiteCuerpoJson.MAXIMO_BYTES + 1);
        request.removeHeader("Content-Length");
        var response = new MockHttpServletResponse();
        AtomicBoolean continued = new AtomicBoolean();

        new FiltroExpuesto().doFilter(request, response, (req, res) -> continued.set(true));

        assertEquals(413, response.getStatus());
        assertTrue(response.getContentAsString().contains("CUERPO_DEMASIADO_GRANDE"));
        assertFalse(continued.get());
    }

    private static MockHttpServletRequest request(int size) {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setMethod("POST");
        request.setContentType("application/json; charset=UTF-8");
        request.setContent("x".repeat(size).getBytes(StandardCharsets.UTF_8));
        return request;
    }

    private static final class FiltroExpuesto extends FiltroLimiteCuerpoJson {
        void doFilter(MockHttpServletRequest request, MockHttpServletResponse response,
                jakarta.servlet.FilterChain chain) throws Exception {
            doFilterInternal(request, response, chain);
        }
    }
}
