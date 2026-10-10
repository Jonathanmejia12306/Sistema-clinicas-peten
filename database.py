import sqlite3
import os
from werkzeug.security import generate_password_hash

DATABASE_NAME = 'clinica.db'

def crear_base_de_datos():
    # Eliminamos la base de datos anterior solo si estamos reiniciando el sistema
    if os.path.exists(DATABASE_NAME):
        try:
            os.remove(DATABASE_NAME)
            print(f"Archivo anterior '{DATABASE_NAME}' eliminado para limpieza.")
        except Exception as e:
            print(f"Advertencia: No se pudo borrar el archivo: {e}")

    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    print("Creando estructura de base de datos...")

    try:
        # USUARIOS
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            nombre TEXT NOT NULL,
            rol TEXT DEFAULT 'admin'
        );
        """)

        # PACIENTES
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS pacientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            apellido TEXT NOT NULL,
            fecha_nacimiento DATE,
            telefono TEXT,
            creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            deleted_at TIMESTAMP
        );
        """)

        # EXPEDIENTES
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS expedientes (
            id_expediente INTEGER PRIMARY KEY AUTOINCREMENT,
            id_paciente INTEGER NOT NULL,
            fecha_expediente DATE NOT NULL,
            motivo_consulta TEXT,
            enfermedades TEXT,
            vasos_agua TEXT,
            alimentos TEXT,
            problemas_hormonales TEXT,
            alergias TEXT,
            menstruacion TEXT,
            caida_cabello TEXT,
            caspa TEXT,
            horas_sueno TEXT,
            productos_corporales TEXT,
            otros_sintomas TEXT,
            skincare_limpieza TEXT,
            skincare_hidratacion TEXT,
            skincare_ojos TEXT,
            skincare_fotoproteccion TEXT,
            skincare_noche TEXT,
            skincare_tratamiento TEXT,
            sustancias_ingeridas TEXT,
            skincare_nuevo_limpieza TEXT,
            skincare_nuevo_hidratacion TEXT,
            skincare_nuevo_ojos TEXT,
            skincare_nuevo_fotoproteccion TEXT,
            skincare_nuevo_noche TEXT,
            skincare_nuevo_tratamiento TEXT,
            FOREIGN KEY (id_paciente) REFERENCES pacientes (id)
        );
        """)

        cursor.execute("CREATE TABLE IF NOT EXISTS sesiones (id_sesion INTEGER PRIMARY KEY AUTOINCREMENT, id_expediente INTEGER NOT NULL, fecha_sesion DATE NOT NULL, tratamiento TEXT NOT NULL, resultados TEXT, FOREIGN KEY (id_expediente) REFERENCES expedientes (id_expediente));")
        cursor.execute("CREATE TABLE IF NOT EXISTS documentos (id_documento INTEGER PRIMARY KEY AUTOINCREMENT, id_expediente INTEGER NOT NULL, nombre_archivo TEXT NOT NULL, ruta_archivo TEXT NOT NULL, fecha_subida TIMESTAMP DEFAULT CURRENT_TIMESTAMP, is_deleted INTEGER NOT NULL DEFAULT 0, deleted_at TIMESTAMP, FOREIGN KEY (id_expediente) REFERENCES expedientes (id_expediente));")

        # INVENTARIO
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS inventario (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo_barras TEXT,
            nombre TEXT NOT NULL,
            descripcion TEXT,
            tipo TEXT NOT NULL,
            precio_venta REAL NOT NULL,
            precio_compra REAL,
            porcentaje_ganancia REAL,
            cantidad INTEGER,
            fecha_vencimiento DATE,
            ruta_foto TEXT,
            creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            deleted_at TIMESTAMP
        );
        """)

        cursor.execute("CREATE TABLE IF NOT EXISTS movimientos_inventario (id INTEGER PRIMARY KEY AUTOINCREMENT, id_item INTEGER NOT NULL, tipo_movimiento TEXT NOT NULL, cantidad INTEGER NOT NULL, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP, descripcion TEXT, FOREIGN KEY (id_item) REFERENCES inventario (id));")
        
        # CITAS
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS citas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            id_paciente INTEGER NOT NULL,
            fecha_cita DATE NOT NULL,
            hora_cita TIME NOT NULL,
            descripcion TEXT,
            estado TEXT NOT NULL DEFAULT 'Pendiente',
            creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (id_paciente) REFERENCES pacientes (id)
        );
        """)

        # VENTAS
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS ventas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            id_paciente INTEGER NOT NULL,
            fecha_venta TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            monto_total REAL NOT NULL,
            descuento_total REAL DEFAULT 0,
            metodo_pago TEXT,
            referencia_pago TEXT,
            saldo_pendiente REAL DEFAULT 0,
            estado_pago TEXT DEFAULT 'Pagado',
            estado TEXT DEFAULT 'Completada',
            id_cita INTEGER,
            FOREIGN KEY (id_paciente) REFERENCES pacientes (id),
            FOREIGN KEY (id_cita) REFERENCES citas (id)
        );
        """)

        cursor.execute("CREATE TABLE IF NOT EXISTS ventas_detalle (id INTEGER PRIMARY KEY AUTOINCREMENT, id_venta INTEGER NOT NULL, id_item_inventario INTEGER NOT NULL, cantidad INTEGER NOT NULL, precio_unitario REAL NOT NULL, descuento REAL DEFAULT 0, FOREIGN KEY (id_venta) REFERENCES ventas (id), FOREIGN KEY (id_item_inventario) REFERENCES inventario (id));")
        
        # ABONOS, CAJA Y GASTOS
        cursor.execute("CREATE TABLE IF NOT EXISTS abonos (id INTEGER PRIMARY KEY AUTOINCREMENT, id_venta INTEGER NOT NULL, fecha_abono TIMESTAMP DEFAULT CURRENT_TIMESTAMP, monto REAL NOT NULL, metodo_pago TEXT NOT NULL, referencia_pago TEXT, saldo_actual_snapshot REAL, notas TEXT, FOREIGN KEY (id_venta) REFERENCES ventas (id));")
        cursor.execute("CREATE TABLE IF NOT EXISTS cierres_caja (id INTEGER PRIMARY KEY AUTOINCREMENT, fecha_apertura TIMESTAMP DEFAULT CURRENT_TIMESTAMP, fecha_cierre TIMESTAMP, monto_inicial REAL NOT NULL, total_ventas_efectivo REAL, total_ventas_otros REAL, monto_final_calculado REAL, monto_final_real REAL, diferencia REAL, estado TEXT NOT NULL);")
        cursor.execute("CREATE TABLE IF NOT EXISTS gastos (id INTEGER PRIMARY KEY AUTOINCREMENT, descripcion TEXT NOT NULL, proveedor TEXT, monto REAL NOT NULL, fecha_emision DATE, fecha_vencimiento DATE, estado TEXT DEFAULT 'Pendiente', fecha_pago DATE, comprobante_ruta TEXT, saldo_pendiente REAL, creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP);")
        cursor.execute("CREATE TABLE IF NOT EXISTS abonos_gastos (id INTEGER PRIMARY KEY AUTOINCREMENT, id_gasto INTEGER NOT NULL, fecha_abono TIMESTAMP DEFAULT CURRENT_TIMESTAMP, monto REAL NOT NULL, metodo_pago TEXT NOT NULL, referencia_pago TEXT, saldo_actual_snapshot REAL, notas TEXT, FOREIGN KEY (id_gasto) REFERENCES gastos (id));")

        # DATOS INICIALES - Contraseña cambiada a 46663627
        password = generate_password_hash("46663627")
        cursor.execute("INSERT INTO usuarios (username, password, nombre, rol) VALUES (?, ?, ?, ?)", ('admin', password, 'Administrador', 'admin'))
        cursor.execute("INSERT INTO pacientes (nombre, apellido, fecha_nacimiento, telefono) VALUES (?, ?, ?, ?)", ('Cliente', 'Mostrador', '2000-01-01', '00000000'))

        conn.commit()
        print("✅ Base de datos creada exitosamente.")

    except Exception as e:
        print(f"❌ Error al crear base de datos: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == '__main__':
    crear_base_de_datos()