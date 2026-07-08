# Setup de Turso - Base de Datos Gratuita en la Nube

## Problema que resuelve
Render usa disco efimero: cada reinicio/deploy borra el SQLite local.
Turso guarda los datos en la nube, asi sobreviven reinicios.

## Plan gratuito de Turso
- 9 GB de almacenamiento
- 1 billon de reads/mes
- 25 million de writes/mes
- Suficiente para miles de pedidos

## Paso 1: Crear cuenta de Turso
1. Ve a https://turso.tech
2. Click "Sign Up" (puedes usar GitHub)
3. Verifica tu email

## Paso 2: Crear base de datos
1. En el dashboard, click "New Database"
2. Nombre: `scanner-vpc`
3. Selecciona la region mas cercana (us-east-1 o similar)
4. Click "Create"

## Paso 3: Obtener URL y Token
1. En la pagina de tu base de datos, busca "Connections"
2. Copia la **Database URL** (formato: `libsql://scanner-vpc-xxx.turso.io`)
3. Click "Create Auth Token" y copia el token

## Paso 4: Configurar variables en Render
1. Ve a tu servicio en Render.com
2. Environment > Add Environment Variable
3. Agrega:
   - `TURSO_DATABASE_URL` = `libsql://scanner-vpc-xxx.turso.io`
   - `TURSO_AUTH_TOKEN` = `eyJhbGciOi...` (el token que copiaste)
4. Guarda y redeploy

## Paso 5: Para desarrollo local
Crea un archivo `.env` en la carpeta scanner-embarque (NO subir a git):
```
TURSO_DATABASE_URL=libsql://scanner-vpc-xxx.turso.io
TURSO_AUTH_TOKEN=eyJhbGciOi...
```

O exporta las variables en tu terminal:
```bash
# Windows PowerShell
$env:TURSO_DATABASE_URL="libsql://scanner-vpc-xxx.turso.io"
$env:TURSO_AUTH_TOKEN="eyJhbGciOi..."

# Linux/Mac
export TURSO_DATABASE_URL="libsql://scanner-vpc-xxx.turso.io"
export TURSO_AUTH_TOKEN="eyJhbGciOi..."
```

## Como funciona
- **Sin Turso configurado**: usa SQLite local (scanner_historial.db) - desarrollo
- **Con Turso configurado**: usa Turso en la nube - produccion
- La deteccion es automatica (presencia de TURSO_DATABASE_URL y TURSO_AUTH_TOKEN)

## Que se persiste en Turso
1. **pedidos_activos**: pedidos en curso (recovery automatico en restart)
2. **pedidos_items**: items/lotes de cada pedido
3. **pedidos_scans**: cada scan individual con usuario y timestamp
4. **pedidos_fuera**: cajas escaneadas fuera del pedido
5. **pedidos_historial**: pedidos finalizados con resultados completos
6. **escaneos_historial**: detalle de escaneos por lote

## Verificar que funciona
Despues de configurar, en los logs de Render deberias ver:
```
[DB] Base de datos inicializada: Turso (libSQL)
[DB] 0 pedidos activos cargados desde base de datos
```

Si dice "SQLite local", las variables de entorno no estan configuradas.
