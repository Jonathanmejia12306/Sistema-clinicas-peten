# Gestión de Clínica

Aplicación Flask para pacientes, expedientes, citas, inventario, ventas, caja, cuentas por cobrar/pagar y reportes.

## Configuración

Usa Python del entorno virtual y configura un archivo local `.env` a partir de `.env.example`. No publiques `.env` ni uses las credenciales de ejemplo. PostgreSQL se selecciona con `DATABASE_URL`; si está vacío, la app usa SQLite en `SQLITE_DB`.

Variables importantes:

- `DATABASE_URL`: conexión PostgreSQL.
- `SQLITE_DB`: ruta de SQLite cuando no se configura PostgreSQL.
- `SECRET_KEY`: clave aleatoria y privada para sesiones. Es obligatoria con `APP_ENV=production`.
- `COOKIE_SECURE=1`: activa cookies `Secure`; úsalo detrás de HTTPS.
- `INITIAL_ADMIN_PASSWORD`: contraseña inicial solo al crear un SQLite nuevo; no cambia administradores existentes.
- `FLASK_DEBUG=1`: activa el depurador únicamente durante desarrollo local. Por defecto está desactivado.

Para ejecutar en PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python app.py
```

En producción configura `APP_ENV=production`, `SECRET_KEY` y HTTPS con cookies seguras. No uses el servidor de desarrollo de Flask para publicar el sistema.

## Base de datos

`python database.py` inicializa SQLite de forma idempotente y ya no elimina un archivo existente. Para una migración SQLite a PostgreSQL, ejecuta primero `python migrate_sqlite_to_postgres.py --dry-run`; el destino debe ser un esquema vacío. El migrador se niega a reemplazar tablas existentes para proteger los datos. Haz un respaldo verificado antes de cualquier migración productiva.

Si una base ya migrada tiene secuencias por detrás de los IDs importados, respalda primero y verifica el destino. El comando `python migrate_sqlite_to_postgres.py --sync-sequences-only --postgres-url $env:DATABASE_URL` solo avanza secuencias; no cambia filas. No lo ejecutes sin autorización sobre una base productiva.

## Pruebas

Ejecuta la suite aislada con:

```powershell
python -m unittest discover -s tests -v
```

Las pruebas usan bases temporales y datos ficticios; no deben apuntarse a la base clínica activa.
