import importlib.util
import io
import os
import pathlib
import re
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from datetime import date, datetime

import app as clinic_app
import database


PROJECT_DIR = pathlib.Path(__file__).resolve().parents[1]
MIGRATION_PATH = PROJECT_DIR / "migrate_sqlite_to_postgres.py"


@contextmanager
def sqlite_connection(path):
    conn = sqlite3.connect(path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


class ClinicRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = pathlib.Path(self.temp_dir.name) / "test_clinica.sqlite"
        self.previous_database_name = database.DATABASE_NAME
        self.previous_database = clinic_app.DATABASE
        self.previous_database_url = clinic_app.DATABASE_URL
        self.previous_admin_password = os.environ.get("INITIAL_ADMIN_PASSWORD")

        os.environ["INITIAL_ADMIN_PASSWORD"] = "isolated-test-admin-password"
        database.DATABASE_NAME = self.db_path
        clinic_app.DATABASE = str(self.db_path)
        clinic_app.DATABASE_URL = None
        self.previous_upload_config = {
            key: clinic_app.app.config[key]
            for key in ("UPLOAD_FOLDER", "PRODUCT_UPLOAD_FOLDER", "EXPENSE_UPLOAD_FOLDER")
        }
        self.upload_root = pathlib.Path(self.temp_dir.name) / "uploads"
        clinic_app.app.config["UPLOAD_FOLDER"] = str(self.upload_root)
        clinic_app.app.config["PRODUCT_UPLOAD_FOLDER"] = str(self.upload_root / "productos")
        clinic_app.app.config["EXPENSE_UPLOAD_FOLDER"] = str(self.upload_root / "comprobantes_gastos")
        database.crear_base_de_datos()

        self.client = clinic_app.app.test_client()
        login_page = self.client.get("/login")
        csrf_match = re.search(
            r'name="csrf_token" value="([^"]+)"',
            login_page.get_data(as_text=True),
        )
        self.assertIsNotNone(csrf_match)
        self.csrf_token = csrf_match.group(1)
        response = self.client.post(
            "/login",
            data={
                "username": "admin",
                "password": "isolated-test-admin-password",
                "csrf_token": self.csrf_token,
            },
        )
        self.assertEqual(response.status_code, 302)

    def tearDown(self):
        clinic_app.DATABASE = self.previous_database
        clinic_app.DATABASE_URL = self.previous_database_url
        database.DATABASE_NAME = self.previous_database_name
        clinic_app.app.config.update(self.previous_upload_config)
        if self.previous_admin_password is None:
            os.environ.pop("INITIAL_ADMIN_PASSWORD", None)
        else:
            os.environ["INITIAL_ADMIN_PASSWORD"] = self.previous_admin_password
        self.temp_dir.cleanup()

    def query(self, sql, params=()):
        with sqlite_connection(self.db_path) as conn:
            return conn.execute(sql, params).fetchall()

    def add_product(self, price=25, quantity=5):
        with sqlite_connection(self.db_path) as conn:
            conn.execute(
                "INSERT INTO inventario "
                "(nombre, tipo, precio_venta, precio_compra, cantidad, is_deleted) "
                "VALUES ('Test product', 'Producto', ?, 10, ?, 0)",
                (price, quantity),
            )

    def open_cash(self):
        return self.client.post(
            "/caja/abrir",
            data={"csrf_token": self.csrf_token, "monto_inicial": "0"},
        )

    def test_patient_expedient_session_and_protected_document_flow(self):
        response = self.client.post(
            "/pacientes/nuevo",
            data={
                "csrf_token": self.csrf_token,
                "nombre": "Paciente",
                "apellido": "Ficticio",
                "telefono": "55500001",
                "fecha_nacimiento": "1990-01-01",
            },
        )
        self.assertEqual(response.status_code, 302)
        patient_id = self.query("SELECT id FROM pacientes WHERE telefono='55500001'")[0][0]

        fields = [
            "enfermedades", "vasos_agua", "alimentos", "problemas_hormonales", "alergias",
            "menstruacion", "caida_cabello", "caspa", "horas_sueno", "productos_corporales",
            "otros_sintomas", "skincare_limpieza", "skincare_hidratacion", "skincare_ojos",
            "skincare_fotoproteccion", "skincare_noche", "skincare_tratamiento",
            "sustancias_ingeridas", "skincare_nuevo_limpieza", "skincare_nuevo_hidratacion",
            "skincare_nuevo_ojos", "skincare_nuevo_fotoproteccion", "skincare_nuevo_noche",
            "skincare_nuevo_tratamiento",
        ]
        form = {
            "csrf_token": self.csrf_token,
            "p_nombre": "Paciente",
            "p_apellido": "Ficticio",
            "p_fecha_nacimiento": "1990-01-01",
            "p_telefono": "55500001",
            "fecha_expediente": "2026-10-10",
            "motivo_consulta": "Prueba ficticia",
        }
        form.update({field: "dato ficticio" for field in fields})
        response = self.client.post(
            f"/paciente/{patient_id}/expediente/nuevo",
            data=form,
        )
        self.assertEqual(response.status_code, 302)
        expediente_id = self.query(
            "SELECT id_expediente FROM expedientes WHERE id_paciente=?", (patient_id,)
        )[0][0]

        response = self.client.post(
            f"/sesion/nueva/{expediente_id}",
            data={
                "csrf_token": self.csrf_token,
                "fecha_sesion": "2026-10-10",
                "tratamiento": "Seguimiento ficticio",
                "resultados": "Sin datos reales",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.query("SELECT COUNT(*) FROM sesiones WHERE id_expediente=?", (expediente_id,)),
            [(1,)],
        )

        response = self.client.post(
            f"/documento/subir/{expediente_id}",
            data={
                "csrf_token": self.csrf_token,
                "documento": (io.BytesIO(b"%PDF-fictitious-test"), "scan.pdf"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 302)
        document_id, filename = self.query(
            "SELECT id_documento, ruta_archivo FROM documentos WHERE id_expediente=?",
            (expediente_id,),
        )[0]
        download = self.client.get(f"/uploads/{filename}")
        self.assertEqual(download.status_code, 200)
        self.assertIn("attachment", download.headers.get("Content-Disposition", ""))
        download.close()
        self.assertEqual(
            clinic_app.app.test_client().get(f"/uploads/{filename}").status_code,
            302,
        )

        self.client.post(
            f"/documento/eliminar/{document_id}",
            data={"csrf_token": self.csrf_token},
        )
        self.assertEqual(
            self.query("SELECT is_deleted FROM documentos WHERE id_documento=?", (document_id,)),
            [(1,)],
        )
        self.client.post(
            f"/documento/restaurar/{document_id}",
            data={"csrf_token": self.csrf_token},
        )
        self.assertEqual(
            self.query("SELECT is_deleted FROM documentos WHERE id_documento=?", (document_id,)),
            [(0,)],
        )

    def test_cash_open_close_is_validated_and_idempotent(self):
        self.assertEqual(self.open_cash().status_code, 302)
        self.client.post(
            "/caja/abrir",
            data={"csrf_token": self.csrf_token, "monto_inicial": "50"},
        )
        self.assertEqual(self.query("SELECT COUNT(*) FROM cierres_caja WHERE estado='Abierta'"), [(1,)])
        response = self.client.post(
            "/caja/cerrar",
            data={"csrf_token": self.csrf_token, "monto_final_real": "50"},
        )
        self.assertEqual(response.status_code, 302)
        self.client.post(
            "/caja/cerrar",
            data={"csrf_token": self.csrf_token, "monto_final_real": "50"},
        )
        self.assertEqual(self.query("SELECT estado, monto_final_real FROM cierres_caja"), [("Cerrada", 50.0)])

    def test_service_profit_report_treats_null_purchase_cost_as_zero(self):
        with sqlite_connection(self.db_path) as conn:
            conn.execute(
                "INSERT INTO inventario (nombre, tipo, precio_venta, precio_compra, cantidad, is_deleted) "
                "VALUES ('Test service', 'Servicio', 100, NULL, NULL, 0)"
            )
        self.open_cash()
        self.client.post(
            "/ventas/nueva",
            data={
                "csrf_token": self.csrf_token,
                "id_paciente": "1",
                "item_ids[]": "1",
                "quantities[]": "1",
                "discounts[]": "0",
                "descuento_general": "0",
                "metodo_pago": "Efectivo",
            },
        )
        today = date.today().isoformat()
        report = self.client.post(
            "/reporte/financiero",
            data={
                "csrf_token": self.csrf_token,
                "fecha_inicio": today,
                "fecha_fin": today,
            },
        )
        self.assertEqual(report.status_code, 200)
        self.assertIn("Q100.00", report.get_data(as_text=True))

    def test_database_initializer_is_repeatable_and_preserves_data(self):
        with sqlite_connection(self.db_path) as conn:
            conn.execute("CREATE TABLE sentinel (value TEXT NOT NULL)")
            conn.execute("INSERT INTO sentinel VALUES ('keep')")
        database.crear_base_de_datos()
        self.assertEqual(self.query("SELECT value FROM sentinel"), [("keep",)])
        self.assertEqual(self.query("SELECT COUNT(*) FROM usuarios WHERE username='admin'"), [(1,)])
        self.assertEqual(self.query("SELECT COUNT(*) FROM pacientes"), [(1,)])

    def test_post_requests_require_csrf_and_logout_is_post_only(self):
        anonymous = clinic_app.app.test_client()
        response = anonymous.post("/login", data={"username": "admin", "password": "bad"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(anonymous.get("/logout").status_code, 405)
        authenticated_response = self.client.get("/")
        self.assertEqual(authenticated_response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(authenticated_response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(authenticated_response.headers["Cache-Control"], "no-store")

    def test_native_database_dates_render_and_serialize_as_iso(self):
        self.assertEqual(clinic_app.calcular_edad(date(1990, 1, 1)), 36)
        self.assertEqual(clinic_app.calcular_edad(datetime(1990, 1, 1, 12, 30)), 36)
        self.assertEqual(clinic_app.iso_date_value(datetime(2026, 10, 10)), "2026-10-10")
        self.assertEqual(
            clinic_app.app.json.dumps({"date": date(2026, 10, 10)}),
            '{"date": "2026-10-10"}',
        )
        formatter = clinic_app.app.jinja_env.filters["db_datetime"]
        self.assertEqual(formatter(datetime(2026, 10, 10, 15, 45), True), "2026-10-10")
        self.assertEqual(formatter(datetime(2026, 10, 10, 15, 45)), "2026-10-10 15:45")

    def test_sale_stock_and_cancellation_are_consistent(self):
        self.add_product()
        self.assertEqual(self.open_cash().status_code, 302)
        sale_data = {
            "csrf_token": self.csrf_token,
            "id_paciente": "1",
            "item_ids[]": "1",
            "discounts[]": "0",
            "descuento_general": "0",
            "metodo_pago": "Efectivo",
        }
        oversale = self.client.post(
            "/ventas/nueva", data={**sale_data, "quantities[]": "6"}
        )
        self.assertEqual(oversale.status_code, 302)
        self.assertEqual(self.query("SELECT COUNT(*) FROM ventas"), [(0,)])
        self.assertEqual(self.query("SELECT cantidad FROM inventario WHERE id=1"), [(5,)])

        self.client.post(
            "/ventas/nueva", data={**sale_data, "quantities[]": "2"}
        )
        sale_id = self.query("SELECT id FROM ventas")[0][0]
        self.assertEqual(self.query("SELECT cantidad FROM inventario WHERE id=1"), [(3,)])
        self.assertEqual(self.query("SELECT COUNT(*) FROM movimientos_inventario"), [(1,)])

        response = self.client.post(
            f"/ventas/cancelar/{sale_id}", data={"csrf_token": self.csrf_token}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.query("SELECT cantidad FROM inventario WHERE id=1"), [(5,)])
        self.assertEqual(
            self.query("SELECT estado FROM ventas WHERE id=?", (sale_id,)),
            [("Cancelada",)],
        )
        self.assertEqual(self.query("SELECT COUNT(*) FROM movimientos_inventario"), [(2,)])

    def test_credit_installments_cannot_overpay(self):
        self.add_product(price=50)
        self.assertEqual(self.open_cash().status_code, 302)
        self.client.post(
            "/ventas/nueva",
            data={
                "csrf_token": self.csrf_token,
                "id_paciente": "1",
                "item_ids[]": "1",
                "quantities[]": "1",
                "discounts[]": "0",
                "descuento_general": "0",
                "metodo_pago": "Crédito",
            },
        )
        sale_id = self.query("SELECT id FROM ventas")[0][0]
        payment = {
            "csrf_token": self.csrf_token,
            "monto_abono": "30",
            "metodo_abono": "Efectivo",
            "referencia_abono": "",
            "origen_url": "creditos",
        }
        self.client.post(f"/ventas/abonar/{sale_id}", data=payment)
        self.client.post(f"/ventas/abonar/{sale_id}", data=payment)
        self.assertEqual(
            self.query("SELECT saldo_pendiente FROM ventas WHERE id=?", (sale_id,)),
            [(20.0,)],
        )
        self.assertEqual(
            self.query("SELECT COUNT(*) FROM abonos WHERE id_venta=?", (sale_id,)),
            [(1,)],
        )

    def test_expense_installments_cannot_overpay(self):
        with sqlite_connection(self.db_path) as conn:
            conn.execute(
                "INSERT INTO gastos (descripcion, monto, saldo_pendiente, estado) "
                "VALUES ('Test expense', 50, 50, 'Pendiente')"
            )
        payment = {
            "csrf_token": self.csrf_token,
            "monto_abono": "30",
            "metodo_abono": "Efectivo",
            "referencia_abono": "",
        }
        self.client.post("/pagos/abonar/1", data=payment)
        self.client.post("/pagos/abonar/1", data=payment)
        self.assertEqual(self.query("SELECT saldo_pendiente FROM gastos WHERE id=1"), [(20.0,)])
        self.assertEqual(
            self.query("SELECT COUNT(*) FROM abonos_gastos WHERE id_gasto=1"),
            [(1,)],
        )

    def test_appointment_edit_rejects_occupied_time(self):
        with sqlite_connection(self.db_path) as conn:
            conn.execute("INSERT INTO pacientes (nombre, apellido) VALUES ('Test', 'Patient')")
            conn.execute(
                "INSERT INTO citas (id_paciente, fecha_cita, hora_cita, estado) "
                "VALUES (1, '2026-12-01', '09:00', 'Pendiente')"
            )
            conn.execute(
                "INSERT INTO citas (id_paciente, fecha_cita, hora_cita, estado) "
                "VALUES (2, '2026-12-01', '10:00', 'Pendiente')"
            )
        response = self.client.post(
            "/citas/editar/2",
            data={
                "csrf_token": self.csrf_token,
                "id_paciente": "2",
                "fecha_cita": "2026-12-01",
                "hora_cita": "09:00",
                "descripcion": "Conflict",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.query("SELECT hora_cita FROM citas WHERE id=2"), [("10:00",)])

    def test_stock_adjustment_cannot_make_negative_or_change_service_stock(self):
        self.add_product(quantity=3)
        with sqlite_connection(self.db_path) as conn:
            conn.execute(
                "INSERT INTO inventario (nombre, tipo, precio_venta, cantidad, is_deleted) "
                "VALUES ('Test service', 'Servicio', 10, NULL, 0)"
            )
        self.client.post(
            "/inventario/stock/remover/1",
            data={"csrf_token": self.csrf_token, "cantidad_a_remover": "9"},
        )
        self.client.post(
            "/inventario/stock/agregar/2",
            data={"csrf_token": self.csrf_token, "cantidad_a_agregar": "4"},
        )
        self.assertEqual(self.query("SELECT cantidad FROM inventario WHERE id=1"), [(3,)])
        self.assertEqual(self.query("SELECT cantidad FROM inventario WHERE id=2"), [(None,)])
        self.assertEqual(self.query("SELECT COUNT(*) FROM movimientos_inventario"), [(0,)])

    def test_upload_allowlist(self):
        self.assertTrue(clinic_app.allowed_file("scan.PDF", clinic_app.DOCUMENT_EXTENSIONS))
        self.assertTrue(clinic_app.allowed_file("photo.webp", clinic_app.IMAGE_EXTENSIONS))
        self.assertFalse(clinic_app.allowed_file("page.html", clinic_app.DOCUMENT_EXTENSIONS))
        self.assertFalse(clinic_app.allowed_file("graphic.svg", clinic_app.IMAGE_EXTENSIONS))
        self.assertFalse(clinic_app.allowed_file("no-extension", clinic_app.DOCUMENT_EXTENSIONS))

    def load_migration_module(self, name):
        spec = importlib.util.spec_from_file_location(name, MIGRATION_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_migration_schema_preserves_username_unique_and_date_type(self):
        migration = self.load_migration_module("migration_schema_test")
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute(
                "CREATE TABLE usuarios (id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, creado DATE)"
            )
            ddl = migration.build_create_table_sqlite(conn, "usuarios")
        finally:
            conn.close()
        self.assertIn('UNIQUE ("username")', ddl)
        self.assertIn('"creado" DATE', ddl)
        self.assertEqual(migration.column_type_sqlite_to_postgres("TIME"), "TIME")

    def test_sequence_repair_only_advances_when_behind(self):
        migration = self.load_migration_module("sequence_guard_test")
        self.assertTrue(migration.sequence_needs_advance(1, False, 734))
        self.assertTrue(migration.sequence_needs_advance(733, True, 734))
        self.assertFalse(migration.sequence_needs_advance(734, True, 734))
        self.assertFalse(migration.sequence_needs_advance(1, False, None))

    def test_sequence_sync_command_advances_only_the_stale_sequence(self):
        migration = self.load_migration_module("sequence_sync_test")

        class FakeCursor:
            def __init__(self):
                self.rows = []
                self.row = None
                self.composed_query_count = 0
                self.set_values = []
                self.closed = False

            def execute(self, statement, params=None):
                if isinstance(statement, str) and "information_schema.columns" in statement:
                    self.rows = [("pacientes", "id")]
                elif isinstance(statement, str) and "pg_get_serial_sequence" in statement:
                    self.row = ("public.pacientes_id_seq",)
                elif isinstance(statement, str) and "setval" in statement:
                    self.set_values.append(params)
                else:
                    self.composed_query_count += 1
                    self.row = (1, False) if self.composed_query_count == 1 else (734,)

            def fetchall(self):
                return self.rows

            def fetchone(self):
                return self.row

            def close(self):
                self.closed = True

        class FakeConnection:
            def __init__(self):
                self.fake_cursor = FakeCursor()
                self.committed = False
                self.rolled_back = False
                self.closed = False

            def cursor(self):
                return self.fake_cursor

            def commit(self):
                self.committed = True

            def rollback(self):
                self.rolled_back = True

            def close(self):
                self.closed = True

        class FakePostgres:
            def __init__(self):
                self.fake_connection = FakeConnection()

            def connect(self, url):
                return self.fake_connection

        fake_postgres = FakePostgres()
        original_psycopg2 = migration.psycopg2
        migration.psycopg2 = fake_postgres
        try:
            synchronized = migration.synchronize_postgres_sequences("unused")
        finally:
            migration.psycopg2 = original_psycopg2
        self.assertEqual(synchronized, ["pacientes.id"])
        self.assertEqual(fake_postgres.fake_connection.fake_cursor.set_values, [("public.pacientes_id_seq", 734)])
        self.assertTrue(fake_postgres.fake_connection.committed)
        self.assertFalse(fake_postgres.fake_connection.rolled_back)
        self.assertTrue(fake_postgres.fake_connection.closed)

    def test_migration_refuses_nonempty_postgres_schema(self):
        migration = self.load_migration_module("migration_guard_test")

        class FakeCursor:
            def __init__(self):
                self.statements = []
                self.closed = False

            def execute(self, sql, params=None):
                self.statements.append(sql)

            def fetchone(self):
                return ("existing_table",)

            def close(self):
                self.closed = True

        class FakeConnection:
            def __init__(self):
                self.fake_cursor = FakeCursor()
                self.rolled_back = False
                self.closed = False

            def cursor(self):
                return self.fake_cursor

            def rollback(self):
                self.rolled_back = True

            def close(self):
                self.closed = True

        class FakePostgres:
            def __init__(self):
                self.fake_connection = FakeConnection()

            def connect(self, url):
                return self.fake_connection

        with tempfile.TemporaryDirectory() as temp_dir:
            sqlite_path = pathlib.Path(temp_dir) / "source.sqlite"
            with sqlite_connection(sqlite_path) as conn:
                conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)")
            fake_postgres = FakePostgres()
            old_psycopg2 = migration.psycopg2
            migration.psycopg2 = fake_postgres
            try:
                with self.assertRaisesRegex(RuntimeError, "not empty"):
                    migration.migrate_sqlite_to_postgres(str(sqlite_path), "unused")
            finally:
                migration.psycopg2 = old_psycopg2
            self.assertTrue(fake_postgres.fake_connection.rolled_back)
            self.assertTrue(fake_postgres.fake_connection.closed)
            self.assertTrue(fake_postgres.fake_connection.fake_cursor.closed)
            self.assertFalse(
                any("DROP TABLE" in sql for sql in fake_postgres.fake_connection.fake_cursor.statements)
            )


if __name__ == "__main__":
    unittest.main()
