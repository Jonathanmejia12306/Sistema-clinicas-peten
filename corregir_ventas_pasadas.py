import sqlite3
import shutil
from datetime import datetime

DATABASE = 'clinica.db'

def sincronizar_ventas_inventario():
    print("--- ANALIZANDO VENTAS PASADAS VS INVENTARIO ---")
    
    # 1. Copia de seguridad por seguridad
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    try:
        shutil.copyfile(DATABASE, f"clinica_backup_{timestamp}.db")
        print(f"1. Backup creado: clinica_backup_{timestamp}.db")
    except Exception as e:
        print(f"Error creando backup: {e}")
        return

    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        # 2. Obtener todos los items vendidos que sean 'Producto'
        # Buscamos en ventas_detalle unidos con inventario
        print("2. Buscando ventas que no descontaron stock...")
        
        sql_ventas = """
            SELECT 
                vd.id as id_detalle,
                vd.id_venta,
                vd.id_item_inventario,
                vd.cantidad as cantidad_vendida,
                i.nombre,
                i.cantidad as stock_actual,
                v.fecha_venta
            FROM ventas_detalle vd
            JOIN inventario i ON vd.id_item_inventario = i.id
            JOIN ventas v ON vd.id_venta = v.id
            WHERE (i.tipo LIKE 'Producto%' OR i.tipo LIKE 'producto%')
            AND v.estado != 'Cancelada'
        """
        items_vendidos = cursor.execute(sql_ventas).fetchall()
        
        corregidos = 0
        
        for item in items_vendidos:
            id_venta = item['id_venta']
            id_item = item['id_item_inventario']
            cant = item['cantidad_vendida']
            nombre = item['nombre']
            
            # 3. Verificar si existe el movimiento en el historial
            # Buscamos un movimiento que mencione esta venta en la descripción
            descripcion_esperada = f"Venta #{id_venta}"
            
            sql_check = """
                SELECT id FROM movimientos_inventario 
                WHERE id_item = ? AND descripcion LIKE ?
            """
            movimiento = cursor.execute(sql_check, (id_item, f"%{descripcion_esperada}%")).fetchone()
            
            if not movimiento:
                # ¡AJÁ! Aquí falta el descuento. La venta existe pero el movimiento no.
                print(f"   [DETECTADO] Venta #{id_venta} de '{nombre}' (Cant: {cant}) no se descontó.")
                
                # 4. Aplicar el descuento ahora
                # Usamos COALESCE para asegurar que si es NULL lo trate como 0
                cursor.execute("""
                    UPDATE inventario 
                    SET cantidad = COALESCE(cantidad, 0) - ? 
                    WHERE id = ?
                """, (cant, id_item))
                
                # 5. Crear el registro en el historial para que no se vuelva a descontar
                cursor.execute("""
                    INSERT INTO movimientos_inventario (id_item, tipo_movimiento, cantidad, descripcion, fecha) 
                    VALUES (?, 'Salida (Corrección)', ?, ?, ?)
                """, (id_item, cant, f"Corrección Venta #{id_venta}", item['fecha_venta']))
                
                corregidos += 1
        
        if corregidos > 0:
            conn.commit()
            print(f"\n--- ÉXITO: Se corrigieron {corregidos} registros de inventario. ---")
            print("El stock ahora debería reflejar las ventas que no se restaron antes.")
        else:
            print("\n--- Todo parece correcto. No se encontraron ventas sin descontar. ---")

    except Exception as e:
        print(f"ERROR CRÍTICO: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == '__main__':
    sincronizar_ventas_inventario()
