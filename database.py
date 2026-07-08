"""
database.py - Capa de abstraccion de base de datos para Scanner VPC v4
Soporta Turso (libSQL) en produccion y SQLite local en desarrollo.

Con Turso, TODOS los datos persisten en la nube:
  - Pedidos activos (recovery automatico en restart)
  - Scans individuales (auditoria completa)
  - Historial de pedidos finalizados
  - Estadisticas de uso
"""
import os
import json
import threading
import urllib.request
import base64
from collections import defaultdict

# Importar libsql si esta disponible (Turso native, rapido)
try:
    import libsql
    HAS_LIBSQL = True
except ImportError:
    HAS_LIBSQL = False

import sqlite3

# ============================================================
# CONFIGURACION
# ============================================================
TURSO_URL = os.environ.get('TURSO_DATABASE_URL', '')
TURSO_TOKEN = os.environ.get('TURSO_AUTH_TOKEN', '')
LOCAL_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scanner_historial.db')

# Lock para operaciones atomicas en la base de datos
DB_LOCK = threading.Lock()

# Pool de conexiones simple
_conn = None
_conn_lock = threading.Lock()


def is_turso():
    """Verificar si estamos usando Turso (credenciales presentes)"""
    return bool(TURSO_URL and TURSO_TOKEN)


# ============================================================
# CLIENTE HTTP TURSO (fallback puro Python cuando libsql no disponible)
# ============================================================
def _convert_param(val):
    """Convertir un valor Python a formato de arg de Turso HTTP API"""
    if val is None:
        return {"type": "null"}
    if isinstance(val, bool):
        return {"type": "integer", "value": 1 if val else 0}
    if isinstance(val, int):
        return {"type": "integer", "value": val}
    if isinstance(val, float):
        return {"type": "float", "value": val}
    if isinstance(val, bytes):
        return {"type": "blob", "base64": base64.b64encode(val).decode()}
    return {"type": "text", "value": str(val)}


def _convert_row(row_array, col_names):
    """Convertir una fila array a diccionario usando nombres de columna"""
    result = {}
    for i, val in enumerate(row_array):
        if i < len(col_names):
            result[col_names[i]] = val
    return result


class TursoHTTPCursor:
    """Cursor que imita sqlite3.Cursor usando Turso HTTP API"""

    def __init__(self, conn):
        self.conn = conn
        self._rows = []
        self._cols = []

    def execute(self, sql, params=()):
        results = self.conn._pipeline([
            {"type": "execute", "stmt": {
                "sql": sql,
                "args": [_convert_param(p) for p in (params or ())],
                "want_rows": True
            }}
        ])
        if results and results[0].get("type") == "ok":
            resp = results[0].get("response", {})
            raw_rows = resp.get("rows", [])
            self._cols = [c.get("name", "") for c in resp.get("cols", [])]
            self._rows = [_convert_row(r, self._cols) for r in raw_rows]
        elif results and results[0].get("type") == "error":
            err = results[0].get("error", {})
            raise RuntimeError(f"Turso error: {err.get('message', 'unknown')}")
        return self

    def fetchone(self):
        if self._rows:
            return self._rows[0]
        return None

    def fetchall(self):
        return list(self._rows)


class TursoHTTPConnection:
    """Conexion que imita sqlite3.Connection usando Turso HTTP API"""

    def __init__(self, url, token):
        http_url = url.replace("libsql://", "https://")
        if not http_url.startswith("https://"):
            http_url = "https://" + http_url
        self.pipeline_url = http_url.rstrip("/") + "/v2/pipeline"
        self.token = token

    def cursor(self):
        return TursoHTTPCursor(self)

    def commit(self):
        pass  # HTTP API auto-commits cada statement

    def close(self):
        pass  # Sin estado que cerrar

    def _pipeline(self, requests):
        """Enviar pipeline de requests a Turso HTTP API"""
        body = json.dumps({"requests": requests + [{"type": "close"}]}).encode("utf-8")
        req = urllib.request.Request(
            self.pipeline_url,
            data=body,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json"
            },
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data.get("results", [])
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Turso HTTP {e.code}: {err_body}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Turso connection error: {e}")

    def execute_batch(self, statements):
        """Ejecutar multiples (sql, params) en un solo pipeline request"""
        requests = []
        for sql, params in statements:
            requests.append({
                "type": "execute",
                "stmt": {
                    "sql": sql,
                    "args": [_convert_param(p) for p in (params or ())],
                    "want_rows": False
                }
            })
        results = self._pipeline(requests)
        for r in results:
            if r.get("type") == "error":
                err = r.get("error", {})
                raise RuntimeError(f"Turso batch error: {err.get('message', 'unknown')}")


def get_connection():
    """Obtener conexion a la base de datos (Turso nativo, Turso HTTP, o SQLite local)"""
    global _conn
    if is_turso():
        with _conn_lock:
            if _conn is None:
                if HAS_LIBSQL:
                    _conn = libsql.connect(TURSO_URL, auth_token=TURSO_TOKEN)
                    print("[DB] Conexion Turso via libsql nativo")
                else:
                    _conn = TursoHTTPConnection(TURSO_URL, TURSO_TOKEN)
                    print("[DB] Conexion Turso via HTTP API (fallback)")
            return _conn
    else:
        conn = sqlite3.connect(LOCAL_DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn


def _execute(sql, params=(), fetchone=False, fetchall=False, commit=False):
    """Ejecutar SQL de forma segura con lock"""
    conn = get_connection()
    cur = conn.cursor()

    with DB_LOCK:
        cur.execute(sql, params)
        result = None
        if fetchone:
            row = cur.fetchone()
            result = dict(row) if row else None
        elif fetchall:
            rows = cur.fetchall()
            result = [dict(r) for r in rows] if rows else []
        if commit:
            conn.commit()

    # Solo cerrar si es SQLite local (Turso usa conexion persistente)
    if not is_turso():
        conn.close()

    return result


def _execute_many(statements, commit=True):
    """Ejecutar multiples statements atomicamente"""
    conn = get_connection()
    cur = conn.cursor()

    with DB_LOCK:
        if hasattr(conn, 'execute_batch'):
            conn.execute_batch(statements)
        else:
            for sql, params in statements:
                cur.execute(sql, params)
            if commit:
                conn.commit()

    if not is_turso():
        conn.close()


# ============================================================
# INICIALIZACION
# ============================================================
def init_db():
    """Crear todas las tablas si no existen"""
    conn = get_connection()
    cur = conn.cursor()

    with DB_LOCK:
        # Tabla de pedidos historial (compatible con version anterior)
        cur.execute('''
            CREATE TABLE IF NOT EXISTS pedidos_historial (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pedido_id TEXT UNIQUE NOT NULL,
                nombre_archivo TEXT,
                header_data_json TEXT,
                resultados_json TEXT,
                resumen_json TEXT,
                fecha_creacion TEXT,
                fecha_finalizacion TEXT,
                usuario_operador TEXT,
                tiempo_total TEXT,
                total_articulos INTEGER DEFAULT 0,
                total_pedido INTEGER DEFAULT 0,
                total_escaneado INTEGER DEFAULT 0,
                cajas_ok INTEGER DEFAULT 0,
                cajas_fuera_pedido INTEGER DEFAULT 0,
                ok_count INTEGER DEFAULT 0,
                faltantes_count INTEGER DEFAULT 0,
                embarque TEXT
            )
        ''')

        cur.execute('''
            CREATE TABLE IF NOT EXISTS escaneos_historial (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pedido_id TEXT NOT NULL,
                lote TEXT NOT NULL,
                codigo TEXT,
                descripcion TEXT,
                cantidad_escaneada INTEGER DEFAULT 0
            )
        ''')

        # NUEVAS TABLAS - persistencia de pedidos activos
        cur.execute('''
            CREATE TABLE IF NOT EXISTS pedidos_activos (
                pedido_id TEXT PRIMARY KEY,
                nombre_archivo TEXT,
                header_data_json TEXT,
                fecha_creacion TEXT,
                inicio_scan TEXT,
                fin_scan TEXT,
                tiempo_total TEXT,
                usuario_operador TEXT,
                usuarios_operadores_json TEXT DEFAULT '[]',
                estado TEXT DEFAULT 'activo',
                total_lineas INTEGER DEFAULT 0
            )
        ''')

        cur.execute('''
            CREATE TABLE IF NOT EXISTS pedidos_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pedido_id TEXT NOT NULL,
                lote TEXT NOT NULL,
                codigo TEXT,
                descripcion TEXT,
                calibre TEXT,
                categoria TEXT,
                cantidad_pedido INTEGER DEFAULT 0,
                cantidad_escaneada INTEGER DEFAULT 0,
                UNIQUE(pedido_id, lote)
            )
        ''')

        cur.execute('''
            CREATE TABLE IF NOT EXISTS pedidos_scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pedido_id TEXT NOT NULL,
                lote TEXT NOT NULL,
                qr_data TEXT,
                cantidad INTEGER DEFAULT 1,
                usuario TEXT,
                timestamp TEXT
            )
        ''')

        cur.execute('''
            CREATE TABLE IF NOT EXISTS pedidos_fuera (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pedido_id TEXT NOT NULL,
                lote TEXT NOT NULL,
                descripcion TEXT,
                cantidad INTEGER DEFAULT 0,
                UNIQUE(pedido_id, lote)
            )
        ''')

        # Indices para performance
        cur.execute('CREATE INDEX IF NOT EXISTS idx_items_pid ON pedidos_items(pedido_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_scans_pid ON pedidos_scans(pedido_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_fuera_pid ON pedidos_fuera(pedido_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_hist_fecha ON pedidos_historial(fecha_finalizacion)')

        conn.commit()

    if not is_turso():
        conn.close()

    db_type = "Turso (libSQL)" if is_turso() else f"SQLite local ({LOCAL_DB_PATH})"
    print(f"[DB] Base de datos inicializada: {db_type}")


# ============================================================
# PEDIDOS ACTIVOS - PERSISTENCIA EN TIEMPO REAL
# ============================================================
def save_pedido_activo(pedido_id, info, pedido_cache):
    """Crear o reemplazar un pedido activo completo en la base de datos"""
    header = info.get('header_data', {})
    usuarios = info.get('usuarios_operadores', [])

    statements = [
        (
            '''INSERT OR REPLACE INTO pedidos_activos
               (pedido_id, nombre_archivo, header_data_json, fecha_creacion,
                inicio_scan, fin_scan, tiempo_total, usuario_operador,
                usuarios_operadores_json, estado, total_lineas)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                pedido_id,
                info.get('nombre_archivo', ''),
                json.dumps(header),
                info.get('fecha_creacion', ''),
                info.get('inicio_scan'),
                info.get('fin_scan'),
                info.get('tiempo_total'),
                info.get('usuario_operador', ''),
                json.dumps(usuarios),
                'finalizado' if info.get('fin_scan') else 'activo',
                info.get('total_lineas', 0)
            )
        )
    ]

    # Guardar items del pedido
    for lote, data in pedido_cache.items():
        statements.append((
            '''INSERT OR REPLACE INTO pedidos_items
               (pedido_id, lote, codigo, descripcion, calibre, categoria,
                cantidad_pedido, cantidad_escaneada)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                pedido_id, lote, data['codigo'], data['descripcion'],
                data['calibre'], data['categoria'],
                data['pedido'], data['escaneado']
            )
        ))

    _execute_many(statements)
    print(f"[DB] Pedido activo {pedido_id} guardado ({len(pedido_cache)} items)")


def update_pedido_info(pedido_id, info):
    """Actualizar solo la info de un pedido (inicio_scan, fin_scan, etc.)"""
    usuarios = info.get('usuarios_operadores', [])
    _execute(
        '''UPDATE pedidos_activos
           SET inicio_scan = ?, fin_scan = ?, tiempo_total = ?,
               usuario_operador = ?, usuarios_operadores_json = ?,
               estado = ?
           WHERE pedido_id = ?''',
        (
            info.get('inicio_scan'),
            info.get('fin_scan'),
            info.get('tiempo_total'),
            info.get('usuario_operador', ''),
            json.dumps(usuarios),
            'finalizado' if info.get('fin_scan') else 'activo',
            pedido_id
        ),
        commit=True
    )


def save_scan(pedido_id, lote, qr_data, cantidad, usuario, timestamp):
    """Guardar un scan individual y actualizar contadores"""
    statements = [
        (
            '''INSERT INTO pedidos_scans
               (pedido_id, lote, qr_data, cantidad, usuario, timestamp)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (pedido_id, lote, qr_data[:200] if qr_data else '', cantidad, usuario, timestamp)
        ),
        (
            '''UPDATE pedidos_items
               SET cantidad_escaneada = cantidad_escaneada + ?
               WHERE pedido_id = ? AND lote = ?''',
            (cantidad, pedido_id, lote)
        )
    ]

    # Verificar si el lote esta fuera de pedido
    row = _execute(
        'SELECT 1 FROM pedidos_items WHERE pedido_id = ? AND lote = ?',
        (pedido_id, lote),
        fetchone=True
    )

    if not row:
        # Lote fuera de pedido - actualizar o insertar en pedidos_fuera
        statements.append((
            '''INSERT INTO pedidos_fuera (pedido_id, lote, descripcion, cantidad)
               VALUES (?, ?, 'Producto no listado', ?)
               ON CONFLICT(pedido_id, lote)
               DO UPDATE SET cantidad = cantidad + ?''',
            (pedido_id, lote, cantidad, cantidad)
        ))

    _execute_many(statements)
    print(f"[DB] Scan guardado: pedido={pedido_id} lote={lote} cant={cantidad} user={usuario}")


def load_pedidos_activos():
    """Cargar todos los pedidos activos desde la base de datos (recovery en restart)"""
    conn = get_connection()
    cur = conn.cursor()
    pedidos = {}

    with DB_LOCK:
        # Cargar pedidos activos (no finalizados)
        cur.execute("SELECT * FROM pedidos_activos WHERE estado = 'activo'")
        rows = cur.fetchall()

        for row in rows:
            row = dict(row) if not isinstance(row, dict) else row
            pedido_id = row['pedido_id']
            header = json.loads(row.get('header_data_json') or '{}')
            usuarios = json.loads(row.get('usuarios_operadores_json') or '[]')

            pedidos[pedido_id] = {
                'pedido_cache': {},
                'escaneos_cache': defaultdict(lambda: {'cantidad': 0, 'timestamp': [], 'scans': []}),
                'qr_escaneados': set(),
                'info': {
                    'fecha_creacion': row.get('fecha_creacion') or '',
                    'nombre_archivo': row.get('nombre_archivo') or '',
                    'total_lineas': row.get('total_lineas') or 0,
                    'inicio_scan': row.get('inicio_scan'),
                    'fin_scan': row.get('fin_scan'),
                    'tiempo_total': row.get('tiempo_total'),
                    'usuario_operador': row.get('usuario_operador') or '',
                    'usuarios_operadores': usuarios,
                    'header_data': header
                }
            }

            # Cargar items del pedido
            cur.execute('SELECT * FROM pedidos_items WHERE pedido_id = ?', (pedido_id,))
            item_rows = cur.fetchall()
            for item_row in item_rows:
                item_row = dict(item_row) if not isinstance(item_row, dict) else item_row
                pedidos[pedido_id]['pedido_cache'][item_row['lote']] = {
                    'codigo': item_row.get('codigo') or '',
                    'descripcion': item_row.get('descripcion') or '',
                    'calibre': item_row.get('calibre') or '',
                    'categoria': item_row.get('categoria') or '',
                    'pedido': item_row.get('cantidad_pedido') or 0,
                    'escaneado': item_row.get('cantidad_escaneada') or 0
                }

            # Cargar scans individuales
            cur.execute('SELECT * FROM pedidos_scans WHERE pedido_id = ? ORDER BY id', (pedido_id,))
            scan_rows = cur.fetchall()
            for scan_row in scan_rows:
                scan_row = dict(scan_row) if not isinstance(scan_row, dict) else scan_row
                lote = scan_row['lote']
                escaneos = pedidos[pedido_id]['escaneos_cache'][lote]
                escaneos['cantidad'] += scan_row.get('cantidad') or 1
                escaneos['timestamp'].append(scan_row.get('timestamp') or '')
                escaneos['scans'].append({
                    'hora': scan_row.get('timestamp') or '',
                    'qr': (scan_row.get('qr_data') or '')[:50],
                    'cantidad': scan_row.get('cantidad') or 1,
                    'usuario': scan_row.get('usuario') or ''
                })
                # Restaurar QR para prevencion de duplicados
                qr_val = (scan_row.get('qr_data') or '').strip()[:200]
                if qr_val:
                    pedidos[pedido_id]['qr_escaneados'].add(qr_val)

            # Cargar items fuera de pedido
            cur.execute('SELECT * FROM pedidos_fuera WHERE pedido_id = ?', (pedido_id,))
            fuera_rows = cur.fetchall()
            for fuera_row in fuera_rows:
                fuera_row = dict(fuera_row) if not isinstance(fuera_row, dict) else fuera_row
                lote = fuera_row['lote']
                if lote not in pedidos[pedido_id]['pedido_cache']:
                    pedidos[pedido_id]['escaneos_cache'][lote]['cantidad'] = fuera_row.get('cantidad') or 0

    if not is_turso():
        conn.close()

    print(f"[DB] {len(pedidos)} pedidos activos cargados desde base de datos")
    return pedidos


def delete_pedido_activo(pedido_id):
    """Eliminar un pedido activo y todos sus datos relacionados"""
    statements = [
        ('DELETE FROM pedidos_activos WHERE pedido_id = ?', (pedido_id,)),
        ('DELETE FROM pedidos_items WHERE pedido_id = ?', (pedido_id,)),
        ('DELETE FROM pedidos_scans WHERE pedido_id = ?', (pedido_id,)),
        ('DELETE FROM pedidos_fuera WHERE pedido_id = ?', (pedido_id,)),
    ]
    _execute_many(statements)


# ============================================================
# HISTORIAL - PEDIDOS FINALIZADOS
# ============================================================
def finalizar_pedido_db(pedido_id, info, pedido_cache, escaneos_cache, resultados, resumen):
    """Mover un pedido de activo a historial en la base de datos"""
    header = info.get('header_data', {})

    statements = [
        (
            '''INSERT OR REPLACE INTO pedidos_historial
               (pedido_id, nombre_archivo, header_data_json, resultados_json, resumen_json,
                fecha_creacion, fecha_finalizacion, usuario_operador, tiempo_total,
                total_articulos, total_pedido, total_escaneado, cajas_ok, cajas_fuera_pedido,
                ok_count, faltantes_count, embarque)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                pedido_id, info.get('nombre_archivo', ''),
                json.dumps(header), json.dumps(resultados), json.dumps(resumen),
                info.get('fecha_creacion', ''), info.get('fin_scan', ''),
                info.get('usuario_operador', ''), info.get('tiempo_total', ''),
                resumen.get('total_articulos', 0), resumen.get('total_pedido', 0),
                resumen.get('total_escaneado', 0), resumen.get('cajas_ok', 0),
                resumen.get('cajas_fuera_pedido', 0), resumen.get('ok', 0),
                resumen.get('faltantes', 0), header.get('embarque', '')
            )
        ),
        (
            "UPDATE pedidos_activos SET estado = 'finalizado' WHERE pedido_id = ?",
            (pedido_id,)
        )
    ]

    # Guardar escaneos en historial
    for lote, data in escaneos_cache.items():
        if lote in pedido_cache:
            statements.append((
                '''INSERT INTO escaneos_historial
                   (pedido_id, lote, codigo, descripcion, cantidad_escaneada)
                   VALUES (?, ?, ?, ?, ?)''',
                (
                    pedido_id, lote,
                    pedido_cache[lote]['codigo'], pedido_cache[lote]['descripcion'],
                    data['cantidad']
                )
            ))

    _execute_many(statements)
    print(f"[DB] Pedido {pedido_id} finalizado y guardado en historial")
    return True


def cargar_historial_db():
    """Cargar todos los pedidos finalizados desde la base de datos"""
    rows = _execute(
        'SELECT * FROM pedidos_historial ORDER BY fecha_finalizacion DESC',
        fetchall=True
    )

    if not rows:
        return []

    historial = []
    for row in rows:
        historial.append({
            'pedido_id': row['pedido_id'],
            'nombre_archivo': row.get('nombre_archivo') or '',
            'header_data': json.loads(row.get('header_data_json') or '{}'),
            'resultados': json.loads(row.get('resultados_json') or '[]'),
            'resumen': json.loads(row.get('resumen_json') or '{}'),
            'fecha_creacion': row.get('fecha_creacion') or '',
            'fecha_finalizacion': row.get('fecha_finalizacion') or '',
            'usuario_operador': row.get('usuario_operador') or '',
            'tiempo_total': row.get('tiempo_total') or '',
            'embarque': row.get('embarque') or ''
        })

    print(f"[DB] {len(historial)} pedidos cargados desde historial")
    return historial


def get_stats_db():
    """Obtener estadisticas agregadas del historial"""
    row = _execute(
        '''SELECT COUNT(*) as total_pedidos,
                  COALESCE(SUM(total_escaneado), 0) as total_cajas,
                  COALESCE(SUM(total_pedido), 0) as total_pedido_cajas
           FROM pedidos_historial''',
        fetchone=True
    )

    if not row:
        return {'sesiones_totales': 0, 'cajas_escaneadas_totales': 0, 'total_pedido_cajas': 0}

    return {
        'sesiones_totales': row.get('total_pedidos') or 0,
        'cajas_escaneadas_totales': row.get('total_cajas') or 0,
        'total_pedido_cajas': row.get('total_pedido_cajas') or 0
    }


def get_pedido_detalle_db(pedido_id):
    """Obtener el detalle completo de un pedido desde el historial"""
    row = _execute(
        'SELECT * FROM pedidos_historial WHERE pedido_id = ?',
        (pedido_id,),
        fetchone=True
    )

    if not row:
        return None

    return {
        'pedido_id': row['pedido_id'],
        'nombre_archivo': row.get('nombre_archivo') or '',
        'header_data': json.loads(row.get('header_data_json') or '{}'),
        'resultados': json.loads(row.get('resultados_json') or '[]'),
        'resumen': json.loads(row.get('resumen_json') or '{}'),
        'fecha_creacion': row.get('fecha_creacion') or '',
        'fecha_finalizacion': row.get('fecha_finalizacion') or '',
        'usuario_operador': row.get('usuario_operador') or '',
        'tiempo_total': row.get('tiempo_total') or '',
        'embarque': row.get('embarque') or ''
    }
