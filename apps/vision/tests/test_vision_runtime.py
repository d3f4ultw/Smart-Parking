from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import cv2
import numpy as np

from vision_runtime import (
    PublicadorRuntime,
    PublicadorVistaPrevia,
    VisionRuntime,
    VisionRuntimeBus,
    ajustar_cursor_inferencia,
    codificar_jpeg,
    limitar_dimension,
)
from smart_parking_client import ConfiguracionRemota, VisionAPIError


class VisionRuntimeTests(unittest.TestCase):
    def test_camera_mode_requires_an_explicit_http_source(self):
        with patch.dict(
            "os.environ",
            {
                "VISION_SOURCE_URL": "",
                "VISION_BEARER_TOKEN": "test-token-" + "x" * 50,
            },
        ):
            with self.assertRaisesRegex(ValueError, "VISION_SOURCE_URL"):
                VisionRuntime("http://127.0.0.1:8000", modo="camera")

    def test_camera_mode_accepts_the_configured_http_source(self):
        with patch.dict(
            "os.environ",
            {
                "VISION_SOURCE_URL": "http://127.0.0.1:4747/video",
                "VISION_BEARER_TOKEN": "test-token-" + "x" * 50,
            },
        ):
            runtime = VisionRuntime("http://127.0.0.1:8000", modo="camera")

        self.assertEqual(runtime.source_url, "http://127.0.0.1:4747/video")

    def test_camera_mode_rejects_non_http_sources(self):
        with patch.dict(
            "os.environ",
            {
                "VISION_SOURCE_URL": "rtsp://127.0.0.1/live",
                "VISION_BEARER_TOKEN": "test-token-" + "x" * 50,
            },
        ):
            with self.assertRaisesRegex(ValueError, "VISION_SOURCE_URL"):
                VisionRuntime("http://127.0.0.1:8000", modo="camera")

    def test_simulation_mode_does_not_require_a_camera_url(self):
        with patch.dict(
            "os.environ",
            {
                "VISION_SOURCE_URL": "",
                "VISION_BEARER_TOKEN": "test-token-" + "x" * 50,
            },
        ):
            runtime = VisionRuntime("http://127.0.0.1:8000", modo="simulation")

        self.assertEqual(runtime.source_url, "")

    def test_inference_thread_limits_are_loaded_from_runtime_environment(self):
        with patch.dict(
            "os.environ",
            {
                "VISION_BEARER_TOKEN": "test-token-" + "x" * 50,
                "VISION_TORCH_NUM_THREADS": "4",
                "VISION_TORCH_NUM_INTEROP_THREADS": "1",
                "VISION_OPENCV_NUM_THREADS": "2",
            },
        ):
            runtime = VisionRuntime("http://127.0.0.1:8000", modo="simulation")

        self.assertEqual(runtime.torch_num_threads, 4)
        self.assertEqual(runtime.torch_num_interop_threads, 1)
        self.assertEqual(runtime.opencv_num_threads, 2)

    def test_configuration_refresh_schedules_next_check_when_revision_is_unchanged(
        self,
    ):
        configuration = ConfiguracionRemota(1, 1, ())
        client = Mock()
        client.session_id = uuid4()
        client.configuracion = configuration
        client.cargar_configuracion.return_value = configuration
        publisher = PublicadorRuntime(
            client,
            VisionRuntimeBus(),
            "simulation",
            threading.Event(),
        )
        publisher.proxima_configuracion = time.monotonic() - 1.0

        publisher._actualizar_configuracion()

        self.assertGreater(publisher.proxima_configuracion, time.monotonic())
        self.assertAlmostEqual(
            publisher.proxima_configuracion - time.monotonic(),
            1.0,
            delta=0.1,
        )
        client.iniciar_sesion.assert_not_called()

    def test_configuration_refresh_keeps_session_and_resets_only_stale_annotation(self):
        session_id = uuid4()
        anterior = ConfiguracionRemota(1, 1, ())
        actual = ConfiguracionRemota(2, 1, ())
        bus = VisionRuntimeBus()
        bus.actualizar_contexto(session_id, anterior)
        raw = np.full((12, 16, 3), 40, dtype=np.uint8)
        annotated = np.full((12, 16, 3), 60, dtype=np.uint8)
        bus.ofrecer_frame("raw", raw)
        bus.ofrecer_frame("annotated", annotated)

        client = Mock()
        client.session_id = session_id
        client.configuracion = anterior

        def cargar_configuracion():
            client.configuracion = actual
            return actual

        client.cargar_configuracion.side_effect = cargar_configuracion
        publisher = PublicadorRuntime(
            client,
            bus,
            "camera",
            threading.Event(),
        )

        publisher._actualizar_configuracion()

        session_actual, config_actual, frames, observations, _, _ = bus.obtener_snapshot()
        self.assertEqual(session_actual, session_id)
        self.assertEqual(config_actual.revision, 2)
        self.assertEqual(set(frames), {"raw"})
        self.assertEqual(frames["raw"].sequence, 1)
        self.assertIsNone(observations)
        self.assertEqual(client.session_id, session_id)
        client.iniciar_sesion.assert_not_called()
        self.assertGreater(publisher.proxima_configuracion, time.monotonic())
        self.assertAlmostEqual(
            publisher.proxima_configuracion - time.monotonic(),
            1.0,
            delta=0.1,
        )

        self.assertFalse(
            bus.ofrecer_frame(
                "annotated",
                annotated,
                session_id=session_id,
                revision=1,
            )
        )
        self.assertTrue(
            bus.ofrecer_frame(
                "annotated",
                annotated,
                session_id=session_id,
                revision=2,
            )
        )
        _, _, frames, _, _, _ = bus.obtener_snapshot()
        self.assertEqual(frames["annotated"].sequence, 2)

    def test_conflict_renews_session_when_configuration_revision_is_unchanged(self):
        session_id = uuid4()
        next_session_id = uuid4()
        configuration = ConfiguracionRemota(63, 31, ())
        bus = VisionRuntimeBus()
        bus.actualizar_contexto(session_id, configuration)
        client = Mock()
        client.session_id = session_id
        client.configuracion = configuration
        client.cargar_configuracion.return_value = configuration

        def iniciar_sesion() -> None:
            client.session_id = next_session_id

        client.iniciar_sesion.side_effect = iniciar_sesion
        publisher = PublicadorRuntime(
            client, bus, "camera", threading.Event()
        )

        publisher._resolver_conflicto()

        client.heartbeat.assert_not_called()
        client.iniciar_sesion.assert_called_once()
        self.assertEqual(bus.obtener_contexto()[0], next_session_id)

    def test_conflict_applies_new_revision_without_renewing_a_valid_session(self):
        session_id = uuid4()
        anterior = ConfiguracionRemota(63, 31, ())
        actual = ConfiguracionRemota(64, 31, ())
        bus = VisionRuntimeBus()
        bus.actualizar_contexto(session_id, anterior)
        client = Mock()
        client.session_id = session_id
        client.configuracion = anterior

        def cargar_configuracion() -> ConfiguracionRemota:
            client.configuracion = actual
            return actual

        client.cargar_configuracion.side_effect = cargar_configuracion
        publisher = PublicadorRuntime(
            client, bus, "camera", threading.Event()
        )

        publisher._resolver_conflicto()

        self.assertEqual(client.session_id, session_id)
        self.assertEqual(client.configuracion, actual)
        self.assertEqual(bus.obtener_contexto(), (session_id, actual))
        client.heartbeat.assert_called_once_with()
        client.iniciar_sesion.assert_not_called()

    def test_conflict_renews_session_if_heartbeat_rejects_changed_revision(self):
        session_id = uuid4()
        next_session_id = uuid4()
        anterior = ConfiguracionRemota(63, 31, ())
        actual = ConfiguracionRemota(64, 31, ())
        bus = VisionRuntimeBus()
        bus.actualizar_contexto(session_id, anterior)
        client = Mock()
        client.session_id = session_id
        client.configuracion = anterior
        client.heartbeat.side_effect = VisionAPIError(409)

        def cargar_configuracion() -> ConfiguracionRemota:
            client.configuracion = actual
            return actual

        client.cargar_configuracion.side_effect = cargar_configuracion

        def iniciar_sesion() -> None:
            client.session_id = next_session_id

        client.iniciar_sesion.side_effect = iniciar_sesion
        publisher = PublicadorRuntime(
            client, bus, "camera", threading.Event()
        )

        publisher._resolver_conflicto()

        self.assertEqual(client.session_id, next_session_id)
        self.assertEqual(bus.obtener_contexto(), (next_session_id, actual))
        client.heartbeat.assert_called_once_with()
        client.iniciar_sesion.assert_called_once_with()

    def test_bus_retains_only_latest_raw_and_annotated_frames(self):
        bus = VisionRuntimeBus()
        session_id = uuid4()
        configuration = ConfiguracionRemota(1, 1, ())
        bus.actualizar_contexto(session_id, configuration)
        first = np.full((24, 32, 3), 20, dtype=np.uint8)
        latest = np.full((24, 32, 3), 90, dtype=np.uint8)
        bus.ofrecer_frame("annotated", first)
        bus.ofrecer_frame("annotated", latest)
        bus.ofrecer_frame("raw", first)

        _, _, frames, _, _, _ = bus.obtener_snapshot()
        self.assertEqual(set(frames), {"raw", "annotated"})
        self.assertEqual(frames["annotated"].sequence, 2)
        self.assertEqual(int(frames["annotated"].frame[0, 0, 0]), 90)
        self.assertIs(frames["annotated"].frame, latest)
        self.assertEqual(frames["raw"].sequence, 1)

    def test_raw_capture_records_source_rate_without_copying_the_frame(self):
        bus = VisionRuntimeBus()
        bus.actualizar_contexto(uuid4(), ConfiguracionRemota(1, 1, ()))
        first = np.full((12, 16, 3), 20, dtype=np.uint8)
        latest = np.full((12, 16, 3), 90, dtype=np.uint8)

        bus.ofrecer_frame("raw", first)
        time.sleep(0.02)
        bus.ofrecer_frame("raw", latest)

        _, _, frames, _, _, state = bus.obtener_snapshot()
        self.assertIs(frames["raw"].frame, latest)
        self.assertGreater(state.source_fps, 0.0)

    def test_preview_publisher_sends_raw_frame_without_waiting_for_yolo_publisher(self):
        bus = VisionRuntimeBus()
        session_id = uuid4()
        bus.actualizar_contexto(session_id, ConfiguracionRemota(1, 1, ()))
        frame = np.random.default_rng(720).integers(
            0,
            256,
            (720, 1280, 3),
            dtype=np.uint8,
        )
        bus.ofrecer_frame("raw", frame)
        detener = threading.Event()
        client = Mock()
        client.session_id = session_id
        client.publicar_frame.side_effect = lambda *_args: detener.set()
        publisher = PublicadorVistaPrevia(client, bus, detener, 25.0)

        publisher.start()
        publisher.join(timeout=1.0)

        self.assertFalse(publisher.is_alive())
        client.publicar_frame.assert_called_once()
        self.assertEqual(client.publicar_frame.call_args.args[0], "raw")
        self.assertEqual(client.publicar_frame.call_args.args[1], session_id)
        jpeg = client.publicar_frame.call_args.args[4]
        self.assertLessEqual(len(jpeg), 1_048_576)
        decodificado = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(decodificado.shape[:2], (720, 1280))

    def test_annotated_upload_is_independent_of_runtime_status_failure(self):
        bus = VisionRuntimeBus()
        session_id = uuid4()
        bus.actualizar_contexto(session_id, ConfiguracionRemota(1, 1, ()))
        frame = np.random.default_rng(720).integers(
            0,
            256,
            (720, 1280, 3),
            dtype=np.uint8,
        )
        bus.ofrecer_frame("annotated", frame)
        detener = threading.Event()
        client = Mock()
        client.session_id = session_id
        client.configuracion = ConfiguracionRemota(1, 1, ())
        client.publicar_frame.side_effect = lambda *_args: detener.set()
        client.publicar_estado_runtime.side_effect = VisionAPIError(503)
        publisher = PublicadorRuntime(
            client, bus, "camera", detener, display_fps=10.0
        )
        publisher.proxima_configuracion = time.monotonic() + 10.0
        publisher.proximo_heartbeat = time.monotonic() + 10.0

        publisher.run()

        client.publicar_frame.assert_called_once()
        self.assertEqual(publisher.annotated_upload_attempts, 1)
        self.assertEqual(publisher.annotated_published_sequence, 1)
        jpeg = client.publicar_frame.call_args.args[4]
        self.assertLessEqual(len(jpeg), 1_048_576)
        decodificado = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(decodificado.shape[:2], (540, 960))

    def test_annotated_upload_failure_records_stage_and_retries_with_backoff(self):
        bus = VisionRuntimeBus()
        session_id = uuid4()
        bus.actualizar_contexto(session_id, ConfiguracionRemota(1, 1, ()))
        bus.ofrecer_frame(
            "annotated", np.full((24, 32, 3), 90, dtype=np.uint8)
        )
        client = Mock()
        client.session_id = session_id
        client.publicar_frame.side_effect = VisionAPIError(503)
        publisher = PublicadorRuntime(
            client, bus, "camera", threading.Event(), display_fps=10.0
        )
        _, _, frames, _, _, _ = bus.obtener_snapshot()

        publisher._publicar_frames(session_id, frames)

        self.assertEqual(publisher.annotated_upload_attempts, 1)
        self.assertEqual(publisher.annotated_upload_failures, 1)
        self.assertEqual(publisher.annotated_published_sequence, 0)
        self.assertEqual(publisher.annotated_last_failure_stage, "upload")
        self.assertGreater(publisher._proximo_intento_anotado, time.monotonic())

    def test_new_session_resets_frame_fences_and_discards_prior_images(self):
        bus = VisionRuntimeBus()
        configuration = ConfiguracionRemota(1, 1, ())
        first_session = uuid4()
        next_session = uuid4()
        bus.actualizar_contexto(first_session, configuration)
        bus.ofrecer_frame("raw", np.full((12, 16, 3), 40, dtype=np.uint8))
        bus.actualizar_contexto(next_session, ConfiguracionRemota(2, 1, ()))
        _, active_configuration, frames, observations, _, _ = bus.obtener_snapshot()
        self.assertEqual(active_configuration.revision, 2)
        self.assertEqual(frames, {})
        self.assertIsNone(observations)
        bus.ofrecer_frame("raw", np.full((12, 16, 3), 60, dtype=np.uint8))
        _, _, frames, _, _, _ = bus.obtener_snapshot()
        self.assertEqual(frames["raw"].session_id, next_session)
        self.assertEqual(frames["raw"].sequence, 1)

    def test_inference_cursor_resets_when_the_api_creates_a_new_session(self):
        session_id = uuid4()
        next_session_id = uuid4()

        same_session, same_sequence = ajustar_cursor_inferencia(
            session_id, session_id, 82
        )
        new_session, new_sequence = ajustar_cursor_inferencia(
            next_session_id, session_id, 5037
        )

        self.assertEqual((same_session, same_sequence), (session_id, 82))
        self.assertEqual((new_session, new_sequence), (next_session_id, 0))

    def test_annotated_generation_diagnostic_distinguishes_raw_from_render(self):
        bus = VisionRuntimeBus()
        session_id = uuid4()
        bus.actualizar_contexto(session_id, ConfiguracionRemota(1, 1, ()))
        bus.ofrecer_frame("raw", np.full((24, 32, 3), 90, dtype=np.uint8))
        client = Mock()
        client.session_id = session_id
        publisher = PublicadorRuntime(
            client, bus, "camera", threading.Event(), display_fps=10.0
        )
        _, _, frames, _, _, _ = bus.obtener_snapshot()
        publisher._diagnosticar_generacion_anotada(
            session_id, frames, processing=True, ahora=0.0
        )

        bus.ofrecer_frame("raw", np.full((24, 32, 3), 90, dtype=np.uint8))
        _, _, frames, _, _, _ = bus.obtener_snapshot()
        publisher._diagnosticar_generacion_anotada(
            session_id, frames, processing=True, ahora=5.1
        )

        self.assertEqual(publisher.annotated_generation_stalls, 1)
        self.assertEqual(publisher.annotated_last_failure_stage, "inference_render")

    def test_frame_resize_and_single_jpeg_encoding_stay_within_limits(self):
        frame = np.full((1200, 2000, 3), 160, dtype=np.uint8)
        reducido = limitar_dimension(frame, 960)
        self.assertLessEqual(max(reducido.shape[:2]), 960)
        self.assertAlmostEqual(
            reducido.shape[1] / reducido.shape[0], 2000 / 1200, places=2
        )
        jpeg = codificar_jpeg(reducido)
        self.assertIsNotNone(jpeg)
        assert jpeg is not None
        self.assertLessEqual(len(jpeg), 1_048_576)
        self.assertTrue(jpeg.startswith(b"\xff\xd8"))
        self.assertTrue(jpeg.endswith(b"\xff\xd9"))


if __name__ == "__main__":
    unittest.main()
