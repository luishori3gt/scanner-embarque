# MEMORIA TECNICA - HERRAMIENTA SCANNER FINAL
# Scanner de Embarque VPC v3.0

---

## IDENTIFICADOR
**Nombre clave:** herramienta scanner Final
**Version:** 3.0
**Empresa:** Vida Produce Company (VPC)
**Desarrollador:** Luis Hori
**Fecha ultima actualizacion:** 2026-06-02

---

## QUE ES

Aplicacion web para verificar embarques comparando lo que dice el picking (PDF) vs lo que realmente se escanea (QR de etiquetas). Funciona con dos dispositivos simultaneos: Admin en PC y Operador en celular.

**URL de produccion (Render):** https://scanner-embarque.onrender.com
**Repositorio GitHub:** https://github.com/luishori3gt/scanner-embarque

---

## ARQUITECTURA

### Roles

| Rol | Dispositivo | Funcion |
|-----|-------------|---------|
| Admin | PC/Navegador | Sube PDF, ve dashboard, descarga reportes, monitoreo |
| Operador | Celular | Escanear QR con camara, ver progreso, iniciar/finalizar escaneo |

### URLs

| Ruta | Proposito |
|------|-----------|
| `/` | Panel Admin |
| `/scan/<pedido_id>` | App del Operador |
| `/upload` | Subir picking PDF |
| `/status/<pedido_id>` | Status en tiempo real |
| `/scan_qr/<pedido_id>` | Endpoint de escaneo QR |
| `/finalizar/<pedido_id>` | Finalizar escaneo |
| `/download/excel/<pedido_id>` | Descargar Excel |
| `/download/pdf/<pedido_id>` | Descargar PDF manifiesto |
| `/guardar_drive/<pedido_id>` | Guardar en Google Drive |

---

## ESTRUCTURA DE ARCHIVOS

```
scanner-embarque/
|-- app_multi_v3.py              # Backend Flask principal
|-- requirements.txt              # Dependencias Python
|-- render.yaml                   # Configuracion Render
|-- .gitignore                    # Ignora credentials.json
|-- credentials.json              # Google Drive (NO en Git)
|-- static/
|   |-- logo-vpc.png              # Logo de la empresa
|   |-- instructivo.html          # Instructivo web para operadores
|   |-- Manual_Scanner_Embarque_VPC.pdf  # Manual PDF
|-- templates/
|   |-- admin_v3.html             # Panel de administracion
|   |-- operador_v3.html          # App del operador (celular)
```

---

## FUNCIONALIDADES IMPLEMENTADAS

### Core (100% funcional)
1. Extraccion de PDFs de picking (parser blindado v4)
2. Generacion de QR para conexion del operador
3. Escaneo de etiquetas QR con camara del celular
4. Modo manual (ingresar lote por teclado)
5. Dashboard en tiempo real (actualiza cada 2 seg)
6. Timer automatico (inicia con primer scan, termina al finalizar)
7. Cierre de escaneo desde operador (boton "TERMINAR ESCANEO")
8. Reporte Excel descargable (2 hojas: Resumen Embarque + General)
9. Reporte PDF Manifiesto descargable
10. Subida automatica a Google Drive
11. Logo VPC en admin, operador y PDF
12. Pestaña de Monitoreo con historial
13. Usuario operador (4 letras)
14. Stats bar en admin (sesiones, cajas, scans activos/completados)
15. Reporte "Uso Acumulado" Excel descargable

### Parser PDF (blindado v4)
- Maneja cantidades europeas (1.200,00 -> 1200)
- Header limpio (Cliente, Destinatario, Entrega, Fechas)
- Descripciones multilinea
- Items tarima/sueltas
- 100% de cobertura de items extraidos

### Cajas fuera de pedido
- Backend detecta correctamente items no en el picking
- Dashboard muestra metricas separadas
- Operador ve banner "CAJAS FUERA DE PEDIDO" al finalizar
- Excel incluye items fuera de pedido

---

## CONFIGURACION RENDER

### Start Command
```
gunicorn app_multi_v3:app
```

### Environment Variables
| Variable | Valor |
|----------|-------|
| GOOGLE_DRIVE_FOLDER_ID | 1HChYtZB51EQkuAlHebmllIju1AUsGI1u |
| GOOGLE_DRIVE_CREDENTIALS | [contenido de credentials.json] |

### NOTA CRITICA
El archivo `credentials.json` NUNCA debe subirse a GitHub. Solo configurar como variable de entorno en Render.

---

## DEPENDENCIAS (requirements.txt)

```
Flask==3.0.0
pdfplumber==0.10.0
reportlab==4.0.7
openpyxl==3.1.2
qrcode==7.4.2
Pillow==10.1.0
gunicorn==21.2.0
google-auth==2.23.4
google-auth-oauthlib==1.1.0
google-auth-httplib2==0.1.1
google-api-python-client==2.109.0
```

---

## ERRORES CONOCIDOS Y SOLUCIONES

| Error | Causa | Solucion |
|-------|-------|----------|
| "Pedido no encontrado" | Render se durmio (plan gratuito) | Usar UptimeRobot para mantener activo, o recargar PDF |
| Camara no abre en celular | HTTP en vez de HTTPS / permisos | Usar HTTPS, permitir camara, usar modo manual |
| "No se pudo extraer lote" | Etiqueta danada | Usar modo manual e ingresar lote |
| Sonido no suena (iPhone) | Restriccion iOS | Tocar pantalla una vez antes de escanear |

---

## PROXIMOS PASOS SUGERIDOS

1. Configurar UptimeRobot para mantener Render activo (plan gratuito se duerme)
2. Agregar colores y bordes al Excel (sin usar openpyxl.styles/openpyxl.drawing que crashean en Render)
3. Implementar base de datos para persistencia de pedidos (evitar perdida al reiniciar)
4. Upgrade a Render Starter ($7/mes) para evitar que se duerma

---

## NOTAS PARA REFERENCIA FUTURA

- Cuando el usuario diga "herramienta scanner Final", se refiere a ESTA aplicacion
- El parser de PDF esta en `app_multi_v3.py`, funcion `extraer_picking_pdf()`
- La version estable NO usa openpyxl.styles ni openpyxl.drawing (crashean en Render)
- El Excel es simple (sin colores) pero funcional
- El logo se usa en: admin_v3.html, operador_v3.html, PDF manifiesto, static/logo-vpc.png
- La herramienta esta diseñada especificamente para los pickings de VPC (formato PDF especifico)
