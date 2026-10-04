import os
import unittest
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import create_engine, delete, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.models import ActivacionCuenta, RolUsuario, Sesion, Usuario


class PersistenceIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            settings = Settings.model_validate(
                {
                    "database_host": os.environ["DATABASE_HOST"],
                    "database_port": os.environ["DATABASE_PORT"],
                    "database_name": os.environ["DATABASE_NAME"],
                    "database_user": os.environ["DATABASE_USER"],
                    "database_password": os.environ["DATABASE_PASSWORD"],
                    "activation_token_ttl_hours": os.environ[
                        "ACTIVATION_TOKEN_TTL_HOURS"
                    ],
                    "activation_challenge_ttl_minutes": os.environ[
                        "ACTIVATION_CHALLENGE_TTL_MINUTES"
                    ],
                }
            )
            database_url = settings.database_url
        except Exception as error:
            raise unittest.SkipTest(
                "La configuracion tipada de base de datos no esta disponible"
            ) from error

        cls.engine = create_engine(database_url, pool_pre_ping=True)
        with cls.engine.connect() as connection:
            nombre_base = connection.scalar(text("SELECT current_database()"))
        if not isinstance(nombre_base, str) or not nombre_base.startswith(
            "smart_parking_test_"
        ):
            raise AssertionError(
                "Las pruebas de persistencia requieren una base temporal"
            )
        cls.session_factory = sessionmaker(
            bind=cls.engine,
            autoflush=False,
            expire_on_commit=False,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        self.db = self.session_factory()

    def tearDown(self) -> None:
        self.db.rollback()
        self.db.close()

    def _nuevo_usuario(self) -> Usuario:
        return Usuario(
            nombre="Temporal",
            apellido_paterno="Administrador",
            apellido_materno="Prueba",
            correo=f"sp002-{uuid4().hex}@example.test",
            contrasena_hash="hash-only-test-value",
        )

    def _eliminar_arbol_usuario(self, usuario_id: int) -> None:
        self.db.execute(delete(Sesion).where(Sesion.usuario_id == usuario_id))
        self.db.execute(
            delete(ActivacionCuenta).where(ActivacionCuenta.usuario_id == usuario_id)
        )
        self.db.execute(delete(Usuario).where(Usuario.id == usuario_id))
        self.db.commit()

    def test_usuario_activacion_y_sesion_persisten(self) -> None:
        usuario = self._nuevo_usuario()
        self.db.add(usuario)
        self.db.commit()
        self.db.refresh(usuario)

        self.assertFalse(usuario.correo_verificado)
        self.assertTrue(usuario.debe_cambiar_contrasena)
        self.assertTrue(usuario.esta_activo)
        self.assertEqual(usuario.rol, "ADMIN")

        activacion = ActivacionCuenta(
            usuario_id=usuario.id,
            token_hash=f"activation-token-hash-{uuid4().hex}",
            codigo_hash=f"activation-code-hash-{uuid4().hex}",
            expira_en=datetime.now(UTC) + timedelta(hours=1),
        )
        self.db.add(activacion)
        self.db.commit()
        self.db.refresh(activacion)

        sesion = Sesion(
            usuario_id=usuario.id,
            token_hash=f"session-token-hash-{uuid4().hex}",
            expira_en=datetime.now(UTC) + timedelta(hours=1),
        )
        self.db.add(sesion)
        self.db.commit()
        self.db.refresh(sesion)

        usuario_persistido = self.db.get(Usuario, usuario.id)
        activacion_persistida = self.db.get(ActivacionCuenta, activacion.id)
        sesion_persistida = self.db.get(Sesion, sesion.id)

        self.assertIsNotNone(usuario_persistido)
        self.assertIsNotNone(activacion_persistida)
        self.assertIsNotNone(sesion_persistida)
        assert usuario_persistido is not None
        assert activacion_persistida is not None
        assert sesion_persistida is not None
        self.assertEqual(activacion_persistida.usuario_id, usuario_persistido.id)
        self.assertEqual(sesion_persistida.usuario_id, usuario_persistido.id)

        with self.assertRaises(IntegrityError):
            self.db.execute(delete(Usuario).where(Usuario.id == usuario.id))
            self.db.commit()
        self.db.rollback()

        self._eliminar_arbol_usuario(usuario.id)

    def test_rol_operador_persiste_y_se_recarga(self) -> None:
        usuario = self._nuevo_usuario()
        usuario.rol = RolUsuario.OPERADOR.value
        usuario_id: int | None = None

        try:
            self.db.add(usuario)
            self.db.commit()
            usuario_id = usuario.id
            self.db.expunge(usuario)

            usuario_persistido = self.db.get(Usuario, usuario_id)

            self.assertIsNotNone(usuario_persistido)
            assert usuario_persistido is not None
            self.assertEqual(usuario_persistido.rol, RolUsuario.OPERADOR.value)
        finally:
            self.db.rollback()
            if usuario_id is not None:
                self._eliminar_arbol_usuario(usuario_id)

    def test_restricciones_del_estado_pendiente_y_desafio_operador(self) -> None:
        correo = f"sp031-pending-{uuid4().hex}@example.test"
        usuario = Usuario(
            nombre="Temporal",
            apellido_paterno="Operador",
            apellido_materno="Prueba",
            correo=correo,
            contrasena_hash=None,
            rol=RolUsuario.OPERADOR.value,
            correo_verificado=False,
            debe_cambiar_contrasena=False,
            esta_activo=True,
        )
        usuario_id: int | None = None
        admin_pendiente_id: int | None = None

        try:
            self.db.add(usuario)
            self.db.commit()
            usuario_id = usuario.id

            admin_pendiente = Usuario(
                correo=f"sp031-pending-admin-{uuid4().hex}@example.test",
                contrasena_hash=None,
                rol=RolUsuario.ADMIN.value,
                correo_verificado=False,
                debe_cambiar_contrasena=False,
            )
            self.db.add(admin_pendiente)
            self.db.commit()
            admin_pendiente_id = admin_pendiente.id

            operador_verificado_sin_hash = Usuario(
                correo=f"sp031-invalid-operator-{uuid4().hex}@example.test",
                contrasena_hash=None,
                rol=RolUsuario.OPERADOR.value,
                correo_verificado=True,
            )
            self.db.add(operador_verificado_sin_hash)
            with self.assertRaises(IntegrityError):
                self.db.commit()
            self.db.rollback()

            activacion = ActivacionCuenta(
                usuario_id=usuario_id,
                token_hash=f"sp031-token-{uuid4().hex}",
                codigo_hash=None,
                desafio_hash=f"sp031-challenge-{uuid4().hex}",
                desafio_expira_en=datetime.now(UTC) + timedelta(minutes=15),
                expira_en=datetime.now(UTC) + timedelta(hours=24),
            )
            self.db.add(activacion)
            self.db.commit()
            self.db.refresh(activacion)
            self.assertIsNotNone(activacion.desafio_hash)
            self.assertIsNotNone(activacion.desafio_expira_en)

            activacion.desafio_expira_en = None
            with self.assertRaises(IntegrityError):
                self.db.commit()
            self.db.rollback()
        finally:
            self.db.rollback()
            if usuario_id is not None:
                self._eliminar_arbol_usuario(usuario_id)
            if admin_pendiente_id is not None:
                self._eliminar_arbol_usuario(admin_pendiente_id)

    def test_restricciones_y_columnas_sensibles(self) -> None:
        usuario = self._nuevo_usuario()
        self.db.add(usuario)
        self.db.commit()
        self.db.refresh(usuario)

        duplicado = Usuario(
            correo=usuario.correo,
            contrasena_hash="another-hash-only-test-value",
        )
        self.db.add(duplicado)
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

        activacion_invalida = ActivacionCuenta(
            usuario_id=usuario.id + 1_000_000,
            token_hash=f"invalid-token-hash-{uuid4().hex}",
            codigo_hash=f"invalid-code-hash-{uuid4().hex}",
            expira_en=datetime.now(UTC) + timedelta(hours=1),
        )
        self.db.add(activacion_invalida)
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

        sesion_invalida = Sesion(
            usuario_id=usuario.id + 1_000_000,
            token_hash=f"invalid-session-token-hash-{uuid4().hex}",
            expira_en=datetime.now(UTC) + timedelta(hours=1),
        )
        self.db.add(sesion_invalida)
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

        inspector = inspect(self.engine)
        tablas = {"usuarios", "activaciones_cuenta", "sesiones"}
        nombres_tabla = set(inspector.get_table_names())
        self.assertTrue(tablas.issubset(nombres_tabla))
        self.assertTrue(
            {"users", "account_activations", "sessions"}.isdisjoint(nombres_tabla)
        )

        columnas = {
            tabla: {columna["name"] for columna in inspector.get_columns(tabla)}
            for tabla in tablas
        }
        self.assertIn("contrasena_hash", columnas["usuarios"])
        self.assertIn("codigo_hash", columnas["activaciones_cuenta"])
        self.assertIn("token_hash", columnas["activaciones_cuenta"])
        self.assertIn("token_hash", columnas["sesiones"])

        nombres_sensibles_prohibidos = {
            "password",
            "contrasena",
            "plaintext_password",
            "raw_session_token",
            "raw_activation_token",
            "raw_verification_code",
            "token",
            "codigo",
        }
        nombres_columnas = set().union(*columnas.values())
        self.assertTrue(nombres_sensibles_prohibidos.isdisjoint(nombres_columnas))

        columnas_temporales = {
            "creado_en",
            "actualizado_en",
            "expira_en",
            "consumido_en",
            "revocado_en",
        }
        for tabla in tablas:
            for columna in inspector.get_columns(tabla):
                if columna["name"] in columnas_temporales:
                    self.assertTrue(getattr(columna["type"], "timezone", False))

        for tabla, nombre_fk in (
            ("activaciones_cuenta", "fk_activaciones_cuenta_usuario_id_usuarios"),
            ("sesiones", "fk_sesiones_usuario_id_usuarios"),
        ):
            claves_foraneas = inspector.get_foreign_keys(tabla)
            clave = next(
                clave for clave in claves_foraneas if clave["name"] == nombre_fk
            )
            self.assertEqual(clave["referred_table"], "usuarios")
            self.assertEqual(clave.get("options", {}).get("ondelete"), "RESTRICT")

        self.assertEqual(
            self.db.scalar(select(Usuario.id).where(Usuario.id == usuario.id)),
            usuario.id,
        )
        self._eliminar_arbol_usuario(usuario.id)


if __name__ == "__main__":
    unittest.main()
