"""
database.py — capa de datos para facturas-app.
Usa SQLite local (archivo data/facturas.db).
"""
import os
import re
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


# ── Ruta de la base de datos ──────────────────────────────────────────────────

DB_PATH = Path(__file__).parent / 'data' / 'facturas.db'
DB_PATH.parent.mkdir(exist_ok=True)


# ── Conexión ──────────────────────────────────────────────────────────────────

@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Creación de tablas ────────────────────────────────────────────────────────

def _migrate():
    """Agrega columnas nuevas a tablas existentes (seguro si ya existen)."""
    nuevas = [
        ("facturas", "pagada",     "INTEGER DEFAULT 0"),
        ("facturas", "fecha_pago", "TEXT"),
        ("facturas", "tipo",         "TEXT DEFAULT 'FC'"),
        ("facturas", "archivo_path", "TEXT"),
        ("pagos",    "moneda",       "TEXT DEFAULT 'ARS'"),
    ]
    with get_conn() as conn:
        for tabla, col, definicion in nuevas:
            try:
                conn.execute(f"ALTER TABLE {tabla} ADD COLUMN {col} {definicion}")
            except Exception:
                pass  # la columna ya existe

    _migrar_numero_unico()


def _migrar_numero_unico():
    """
    Reconstruye 'facturas' para quitar el UNIQUE global sobre 'numero'.
    El número debe ser único POR proveedor+tipo, no en todo el sistema
    (dos proveedores pueden tener el mismo número de comprobante).
    """
    con = sqlite3.connect(DB_PATH)
    con.isolation_level = None  # autocommit, para poder usar PRAGMA y BEGIN/COMMIT
    try:
        row = con.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='facturas'"
        ).fetchone()
        if not row or not re.search(r'numero\s+TEXT\s+UNIQUE', row[0], re.IGNORECASE):
            return  # ya migrado o tabla inexistente

        cols = [r[1] for r in con.execute("PRAGMA table_info(facturas)").fetchall()]
        collist = ', '.join(cols)

        con.execute("PRAGMA foreign_keys=OFF")
        con.executescript(f"""
            BEGIN;
            CREATE TABLE facturas_new (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                proveedor_id    INTEGER NOT NULL,
                numero          TEXT NOT NULL,
                fecha           TEXT NOT NULL,
                subtotal        REAL DEFAULT 0,
                iva_21          REAL DEFAULT 0,
                iva_105         REAL DEFAULT 0,
                percepciones    REAL DEFAULT 0,
                total           REAL DEFAULT 0,
                moneda          TEXT DEFAULT 'ARS',
                tipo_cambio     REAL DEFAULT 1.0,
                archivo_nombre  TEXT,
                cae             TEXT,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                pagada          INTEGER DEFAULT 0,
                fecha_pago      TEXT,
                tipo            TEXT DEFAULT 'FC',
                archivo_path    TEXT
            );
            INSERT INTO facturas_new ({collist}) SELECT {collist} FROM facturas;
            DROP TABLE facturas;
            ALTER TABLE facturas_new RENAME TO facturas;
            CREATE INDEX IF NOT EXISTS idx_facturas_fecha ON facturas(fecha);
            CREATE INDEX IF NOT EXISTS idx_facturas_prov  ON facturas(proveedor_id);
            COMMIT;
        """)
        con.execute("PRAGMA foreign_keys=ON")
    finally:
        con.close()


def init_db():
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS proveedores (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre          TEXT NOT NULL,
            cuit            TEXT UNIQUE,
            moneda_default  TEXT DEFAULT 'ARS',
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS facturas (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            proveedor_id    INTEGER NOT NULL,
            numero          TEXT UNIQUE NOT NULL,
            fecha           TEXT NOT NULL,
            subtotal        REAL DEFAULT 0,
            iva_21          REAL DEFAULT 0,
            iva_105         REAL DEFAULT 0,
            percepciones    REAL DEFAULT 0,
            total           REAL DEFAULT 0,
            moneda          TEXT DEFAULT 'ARS',
            tipo_cambio     REAL DEFAULT 1.0,
            archivo_nombre  TEXT,
            cae             TEXT,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (proveedor_id) REFERENCES proveedores(id)
        );

        CREATE TABLE IF NOT EXISTS items (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            factura_id       INTEGER NOT NULL,
            sku              TEXT NOT NULL,
            descripcion      TEXT,
            cantidad         REAL DEFAULT 0,
            precio_unit      REAL DEFAULT 0,
            descuento_pct    REAL DEFAULT 0,
            precio_neto_unit REAL DEFAULT 0,
            iva_pct          REAL DEFAULT 21.0,
            subtotal_siva    REAL DEFAULT 0,
            moneda           TEXT DEFAULT 'ARS',
            FOREIGN KEY (factura_id) REFERENCES facturas(id)
        );

        CREATE INDEX IF NOT EXISTS idx_items_sku      ON items(sku);
        CREATE INDEX IF NOT EXISTS idx_items_factura  ON items(factura_id);
        CREATE INDEX IF NOT EXISTS idx_facturas_fecha ON facturas(fecha);
        CREATE INDEX IF NOT EXISTS idx_facturas_prov  ON facturas(proveedor_id);

        CREATE TABLE IF NOT EXISTS proveedor_config (
            cuit        TEXT PRIMARY KEY,
            config_json TEXT NOT NULL,
            updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS pagos (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            proveedor_id INTEGER NOT NULL,
            monto        REAL NOT NULL,
            fecha        TEXT NOT NULL,
            descripcion  TEXT,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (proveedor_id) REFERENCES proveedores(id)
        );

        CREATE INDEX IF NOT EXISTS idx_pagos_prov ON pagos(proveedor_id);
        """)
    _migrate()


# ── Utilidades de fecha ───────────────────────────────────────────────────────

def _to_iso(fecha_str):
    """'27/04/2026' → '2026-04-27'. Acepta también formato ISO."""
    if not fecha_str:
        return None
    s = str(fecha_str).strip()
    if len(s) == 10 and s[2] == '/':
        d, m, y = s.split('/')
        return f"{y}-{m}-{d}"
    return s


def _to_display(fecha_iso):
    """'2026-04-27' → '27/04/2026'."""
    if not fecha_iso:
        return ''
    s = str(fecha_iso).strip()
    if len(s) == 10 and s[4] == '-':
        y, m, d = s.split('-')
        return f"{d}/{m}/{y}"
    return s


# ── Escritura ─────────────────────────────────────────────────────────────────

def upsert_proveedor(nombre, cuit, moneda_default='ARS'):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO proveedores (nombre, cuit, moneda_default)
            VALUES (?, ?, ?)
            ON CONFLICT(cuit) DO UPDATE SET nombre = excluded.nombre
        """, (nombre, cuit, moneda_default))
        row = conn.execute(
            "SELECT id FROM proveedores WHERE cuit = ?", (cuit,)
        ).fetchone()
        return row['id']


def insert_factura(proveedor_id, numero, fecha, subtotal, iva_21, iva_105,
                   percepciones, total, moneda, tipo_cambio, archivo_nombre, cae,
                   tipo='FC'):
    fecha_iso = _to_iso(fecha)
    with get_conn() as conn:
        # Duplicado = mismo proveedor + mismo tipo + mismo número
        existing = conn.execute("""
            SELECT id FROM facturas
            WHERE proveedor_id = ? AND numero = ? AND COALESCE(tipo,'FC') = ?
        """, (proveedor_id, numero, tipo)).fetchone()
        if existing:
            return None
        cur = conn.execute("""
            INSERT INTO facturas
                (proveedor_id, numero, fecha, subtotal, iva_21, iva_105,
                 percepciones, total, moneda, tipo_cambio, archivo_nombre, cae, tipo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (proveedor_id, numero, fecha_iso, subtotal, iva_21, iva_105,
              percepciones, total, moneda, tipo_cambio, archivo_nombre, cae, tipo))
        return cur.lastrowid


def insert_items(factura_id, items):
    rows = [(
        factura_id,
        it['sku'],
        it.get('descripcion', ''),
        it.get('cantidad', 0),
        it.get('precio_unit', 0),
        it.get('descuento_pct', 0),
        it.get('precio_neto_unit', 0),
        it.get('iva_pct', 21.0),
        it.get('subtotal_siva', 0),
        it.get('moneda', 'ARS'),
    ) for it in items]
    with get_conn() as conn:
        conn.executemany("""
            INSERT INTO items
                (factura_id, sku, descripcion, cantidad, precio_unit,
                 descuento_pct, precio_neto_unit, iva_pct, subtotal_siva, moneda)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)


# ── Lectura ───────────────────────────────────────────────────────────────────

def marcar_pagada(factura_id, fecha_pago=None):
    """Marca una factura como pagada."""
    import datetime
    if not fecha_pago:
        fecha_pago = datetime.date.today().strftime('%Y-%m-%d')
    with get_conn() as conn:
        conn.execute(
            "UPDATE facturas SET pagada=1, fecha_pago=? WHERE id=?",
            (fecha_pago, factura_id)
        )


def marcar_impaga(factura_id):
    """Quita el estado de pagada de una factura."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE facturas SET pagada=0, fecha_pago=NULL WHERE id=?",
            (factura_id,)
        )


def insert_pago(proveedor_id, monto, fecha, descripcion='', moneda='ARS'):
    """Registra un pago a un proveedor (en ARS o USD)."""
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO pagos (proveedor_id, monto, fecha, descripcion, moneda)
            VALUES (?, ?, ?, ?, ?)
        """, (proveedor_id, monto, _to_iso(fecha), descripcion, moneda))


def delete_pago(pago_id):
    """Elimina un pago registrado."""
    with get_conn() as conn:
        conn.execute("DELETE FROM pagos WHERE id = ?", (pago_id,))


def factura_ya_cargada(proveedor_cuit, numero, tipo='FC'):
    """
    Devuelve la factura existente (dict) si ya se cargó este comprobante
    (mismo proveedor por CUIT + mismo número + mismo tipo), o None.
    """
    if not numero:
        return None
    with get_conn() as conn:
        row = conn.execute("""
            SELECT f.id, f.numero, f.fecha, f.total, f.created_at
            FROM facturas f
            JOIN proveedores p ON f.proveedor_id = p.id
            WHERE p.cuit = ? AND f.numero = ? AND COALESCE(f.tipo,'FC') = ?
        """, (proveedor_cuit, numero, tipo)).fetchone()
    return dict(row) if row else None


def set_archivo_factura(factura_id, path):
    """Guarda la ruta del archivo original (PDF/imagen) de una factura."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE facturas SET archivo_path = ? WHERE id = ?",
            (path, factura_id)
        )


# Carpeta donde se guardan los comprobantes originales
ARCHIVOS_DIR = DB_PATH.parent / 'archivos'
ARCHIVOS_DIR.mkdir(exist_ok=True)


def get_cuenta_corriente(proveedor_id, moneda='ARS'):
    """
    Devuelve (movimientos, saldo_actual) de UNA moneda para un proveedor.
    Movimientos ordenados por fecha: facturas (debe) + pagos (haber).
    """
    with get_conn() as conn:
        facturas = conn.execute("""
            SELECT fecha,
                   CASE COALESCE(tipo,'FC')
                        WHEN 'NC' THEN 'N. CRÉDITO'
                        WHEN 'ND' THEN 'N. DÉBITO'
                        ELSE 'FACTURA' END AS tipo,
                   (CASE COALESCE(tipo,'FC')
                        WHEN 'NC' THEN 'N.Créd. '
                        WHEN 'ND' THEN 'N.Déb. '
                        ELSE 'Factura ' END) || numero AS descripcion,
                   CASE WHEN COALESCE(tipo,'FC')='NC' THEN 0.0 ELSE total END AS debe,
                   CASE WHEN COALESCE(tipo,'FC')='NC' THEN total ELSE 0.0 END AS haber,
                   id AS ref_id
            FROM facturas WHERE proveedor_id = ? AND moneda = ?
        """, (proveedor_id, moneda)).fetchall()

        pagos = conn.execute("""
            SELECT fecha, 'PAGO' AS tipo,
                   COALESCE(descripcion, 'Pago') AS descripcion,
                   0.0 AS debe, monto AS haber, id AS ref_id
            FROM pagos WHERE proveedor_id = ? AND COALESCE(moneda,'ARS') = ?
        """, (proveedor_id, moneda)).fetchall()

    movs = [dict(r) for r in facturas] + [dict(r) for r in pagos]
    movs.sort(key=lambda x: x['fecha'] or '')

    saldo = 0.0
    for m in movs:
        saldo += m['debe'] - m['haber']
        m['saldo']         = saldo
        m['fecha_display'] = _to_display(m['fecha'])

    return movs, saldo


def get_monedas_proveedor(proveedor_id):
    """Devuelve las monedas en las que el proveedor tiene facturas o pagos."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT moneda FROM facturas WHERE proveedor_id = ?
            UNION
            SELECT COALESCE(moneda,'ARS') FROM pagos WHERE proveedor_id = ?
        """, (proveedor_id, proveedor_id)).fetchall()
    monedas = sorted({r['moneda'] for r in rows if r['moneda']})
    return monedas or ['ARS']


def get_saldos_proveedores():
    """
    Saldo por proveedor, separado por moneda (ARS y USD):
    saldo = total facturas - total pagos, por cada moneda.
    """
    # Facturas y N. Débito suman; N. Crédito resta; pagos restan.
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT p.id, p.nombre, p.cuit,
                   COALESCE(f.fact_ars, 0) AS fact_ars,
                   COALESCE(f.fact_usd, 0) AS fact_usd,
                   COALESCE(f.nc_ars,   0) AS nc_ars,
                   COALESCE(f.nc_usd,   0) AS nc_usd,
                   COALESCE(pg.pago_ars, 0) AS pago_ars,
                   COALESCE(pg.pago_usd, 0) AS pago_usd
            FROM proveedores p
            LEFT JOIN (
                SELECT proveedor_id,
                  SUM(CASE WHEN moneda='ARS' AND COALESCE(tipo,'FC')!='NC' THEN total ELSE 0 END) AS fact_ars,
                  SUM(CASE WHEN moneda='USD' AND COALESCE(tipo,'FC')!='NC' THEN total ELSE 0 END) AS fact_usd,
                  SUM(CASE WHEN moneda='ARS' AND COALESCE(tipo,'FC')='NC'  THEN total ELSE 0 END) AS nc_ars,
                  SUM(CASE WHEN moneda='USD' AND COALESCE(tipo,'FC')='NC'  THEN total ELSE 0 END) AS nc_usd
                FROM facturas GROUP BY proveedor_id
            ) f ON f.proveedor_id = p.id
            LEFT JOIN (
                SELECT proveedor_id,
                  SUM(CASE WHEN COALESCE(moneda,'ARS')='ARS' THEN monto ELSE 0 END) AS pago_ars,
                  SUM(CASE WHEN moneda='USD' THEN monto ELSE 0 END) AS pago_usd
                FROM pagos GROUP BY proveedor_id
            ) pg ON pg.proveedor_id = p.id
        """).fetchall()

    result = []
    for r in rows:
        d = dict(r)
        d['saldo_ars'] = d['fact_ars'] - d['nc_ars'] - d['pago_ars']
        d['saldo_usd'] = d['fact_usd'] - d['nc_usd'] - d['pago_usd']
        result.append(d)
    result.sort(key=lambda x: x['saldo_ars'], reverse=True)
    return result


def get_resumen_pagos():
    """Devuelve totales de facturas pagadas y pendientes."""
    with get_conn() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*)                                               AS total,
                COALESCE(SUM(CASE WHEN pagada=0 THEN 1 ELSE 0 END),0) AS pendientes,
                COALESCE(SUM(CASE WHEN pagada=1 THEN 1 ELSE 0 END),0) AS pagadas,
                COALESCE(SUM(CASE WHEN pagada=0 AND moneda='ARS'
                                  THEN total ELSE 0 END), 0)          AS monto_pendiente_ars
            FROM facturas
        """).fetchone()
    return dict(row)


def delete_factura(factura_id):
    """Elimina una factura y todos sus ítems."""
    with get_conn() as conn:
        conn.execute("DELETE FROM items    WHERE factura_id = ?", (factura_id,))
        conn.execute("DELETE FROM facturas WHERE id = ?",         (factura_id,))


def get_proveedor_nombre_por_cuit(cuit):
    """Devuelve el nombre guardado de un proveedor por su CUIT, o None."""
    if not cuit:
        return None
    with get_conn() as conn:
        row = conn.execute(
            "SELECT nombre FROM proveedores WHERE cuit = ?", (cuit,)
        ).fetchone()
    return row['nombre'] if row else None


def get_proveedores():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM proveedores ORDER BY nombre"
        ).fetchall()
        return [dict(r) for r in rows]


def get_facturas(proveedor_id=None, fecha_desde=None, fecha_hasta=None):
    q = """
        SELECT f.*, p.nombre AS proveedor_nombre, p.cuit AS proveedor_cuit
        FROM facturas f
        JOIN proveedores p ON f.proveedor_id = p.id
        WHERE 1=1
    """
    params = []
    if proveedor_id:
        q += " AND f.proveedor_id = ?"
        params.append(proveedor_id)
    if fecha_desde:
        q += " AND f.fecha >= ?"
        params.append(fecha_desde)
    if fecha_hasta:
        q += " AND f.fecha <= ?"
        params.append(fecha_hasta)
    q += " ORDER BY f.fecha DESC"
    with get_conn() as conn:
        rows = conn.execute(q, params).fetchall()
        result = [dict(r) for r in rows]
    for r in result:
        r['fecha_display']     = _to_display(r['fecha'])
        r['fecha_pago_display'] = _to_display(r.get('fecha_pago', ''))
    return result


def get_items_by_sku(sku, proveedor_id=None):
    q = """
        SELECT i.*, f.fecha, f.numero AS factura_numero,
               f.tipo_cambio, p.nombre AS proveedor_nombre
        FROM items i
        JOIN facturas f ON i.factura_id = f.id
        JOIN proveedores p ON f.proveedor_id = p.id
        WHERE i.sku = ?
    """
    params = [sku]
    if proveedor_id:
        q += " AND f.proveedor_id = ?"
        params.append(proveedor_id)
    q += " ORDER BY f.fecha"
    with get_conn() as conn:
        rows = conn.execute(q, params).fetchall()
        result = [dict(r) for r in rows]
    for r in result:
        r['fecha_display'] = _to_display(r['fecha'])
    return result


def search_skus(query_str, proveedor_id=None, limit=50):
    q = """
        SELECT i.sku, i.descripcion, i.moneda,
               p.nombre AS proveedor_nombre, p.id AS proveedor_id,
               COUNT(DISTINCT f.id)  AS veces_comprado,
               SUM(i.cantidad)       AS total_unidades,
               MAX(f.fecha)          AS ultima_compra_iso
        FROM items i
        JOIN facturas f ON i.factura_id = f.id
        JOIN proveedores p ON f.proveedor_id = p.id
        WHERE (i.sku LIKE ? OR i.descripcion LIKE ?)
    """
    params = [f'%{query_str}%', f'%{query_str}%']
    if proveedor_id:
        q += " AND f.proveedor_id = ?"
        params.append(proveedor_id)
    q += (" GROUP BY i.sku, i.descripcion, i.moneda, p.nombre, p.id "
          "ORDER BY veces_comprado DESC LIMIT ?")
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(q, params).fetchall()
        result = [dict(r) for r in rows]
    for r in result:
        r['ultima_compra'] = _to_display(r.get('ultima_compra_iso', ''))
    return result


def get_resumen_proveedor(proveedor_id):
    with get_conn() as conn:
        stats = conn.execute("""
            SELECT
                COUNT(*)                                                        AS n_facturas,
                MIN(fecha)                                                      AS primera_iso,
                MAX(fecha)                                                      AS ultima_iso,
                COALESCE(SUM(CASE WHEN moneda='ARS' THEN subtotal ELSE 0 END), 0) AS total_ars,
                COALESCE(SUM(CASE WHEN moneda='USD' THEN total    ELSE 0 END), 0) AS total_usd
            FROM facturas
            WHERE proveedor_id = ?
        """, (proveedor_id,)).fetchone()
        n_skus = conn.execute("""
            SELECT COUNT(DISTINCT i.sku) AS n_skus
            FROM items i
            JOIN facturas f ON i.factura_id = f.id
            WHERE f.proveedor_id = ?
        """, (proveedor_id,)).fetchone()['n_skus']
    d = dict(stats)
    d['n_skus'] = n_skus
    d['primera'] = _to_display(d.pop('primera_iso', ''))
    d['ultima']  = _to_display(d.pop('ultima_iso',  ''))
    return d


def comparar_entre_proveedores(keyword):
    like = f'%{keyword}%'
    with get_conn() as conn:
        resumen = conn.execute("""
            SELECT
                p.nombre            AS proveedor,
                i.sku               AS codigo,
                i.descripcion,
                i.moneda,
                COUNT(DISTINCT f.id)        AS facturas,
                SUM(i.cantidad)             AS total_unidades,
                MIN(i.precio_neto_unit)     AS precio_min,
                MAX(i.precio_neto_unit)     AS precio_max,
                ROUND(AVG(i.precio_neto_unit), 2) AS precio_prom,
                MAX(f.fecha)        AS ultima_compra_iso
            FROM items i
            JOIN facturas f ON i.factura_id = f.id
            JOIN proveedores p ON f.proveedor_id = p.id
            WHERE i.descripcion LIKE ?
              AND i.precio_neto_unit > 0
            GROUP BY p.id, p.nombre, i.sku, i.descripcion, i.moneda
            ORDER BY i.descripcion, precio_prom
        """, (like,)).fetchall()

        detalle = conn.execute("""
            SELECT
                p.nombre            AS proveedor,
                i.sku               AS codigo,
                i.descripcion,
                f.fecha,
                i.precio_neto_unit  AS precio_neto,
                i.cantidad,
                i.moneda
            FROM items i
            JOIN facturas f ON i.factura_id = f.id
            JOIN proveedores p ON f.proveedor_id = p.id
            WHERE i.descripcion LIKE ?
              AND i.precio_neto_unit > 0
            ORDER BY i.descripcion, f.fecha
        """, (like,)).fetchall()

    resumen_list = [dict(r) for r in resumen]
    for r in resumen_list:
        r['ultima_compra'] = _to_display(r.pop('ultima_compra_iso', ''))

    detalle_list = [dict(r) for r in detalle]
    for d in detalle_list:
        d['fecha_display'] = _to_display(d['fecha'])

    return resumen_list, detalle_list


def get_proveedor_config(cuit):
    """Devuelve el config de extracción guardado para un CUIT, o None si no existe."""
    if not cuit:
        return None
    with get_conn() as conn:
        row = conn.execute(
            "SELECT config_json FROM proveedor_config WHERE cuit = ?", (cuit,)
        ).fetchone()
    return json.loads(row['config_json']) if row else None


def save_proveedor_config(cuit, config):
    """Guarda o actualiza el perfil de extracción para un CUIT."""
    if not cuit or not config:
        return
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO proveedor_config (cuit, config_json)
            VALUES (?, ?)
            ON CONFLICT(cuit) DO UPDATE SET
                config_json = excluded.config_json,
                updated_at  = CURRENT_TIMESTAMP
        """, (cuit, json.dumps(config, ensure_ascii=False)))


def get_compras_por_mes(proveedor_id=None):
    q = """
        SELECT strftime('%Y-%m', fecha) AS mes,
               SUM(CASE WHEN moneda='ARS' THEN subtotal ELSE subtotal * tipo_cambio END) AS total_ars
        FROM facturas
        WHERE 1=1
    """
    params = []
    if proveedor_id:
        q += " AND proveedor_id = ?"
        params.append(proveedor_id)
    q += " GROUP BY mes ORDER BY mes"
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(q, params).fetchall()]
