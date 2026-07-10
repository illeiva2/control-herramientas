# Control de Herramientas (Pañol)

Sistema local de préstamo de herramientas que reemplaza los Excel
`CONTROL DE HERRAMIENTAS.xlsm` e `Inventario (1).xlsx`. Corre en una sola PC,
sin internet, con base de datos SQLite en `data/panol.db`.

## Instalación en la máquina destino (recomendada: ejecutable)

La carpeta **`instalador/`** contiene el programa ya compilado (no necesita
Python ni internet), compatible con **Windows 7 SP1 o superior, 32 y 64 bits**:

1. Copiar la carpeta `instalador` a la PC (pendrive, red).
2. Doble clic en `INSTALAR.bat` (crea acceso directo, opcional inicio automático).
3. Ver `LEEME.txt` para detalles y solución de problemas en Windows 7.

El exe se compila con Python 3.8.10 x86 + PyInstaller 5.13.2 (últimas versiones
compatibles con Win7) usando `build_exe.bat`.

## Alternativa: correr desde el código (requiere Python 3.10+)

1. Instalar **Python** desde https://www.python.org/downloads/
   (marcar *"Add python.exe to PATH"* durante la instalación).
2. Copiar esta carpeta completa a la máquina (por ej. a `C:\panol`).
3. Doble clic en **`iniciar.bat`**. La primera vez descarga las dependencias
   (necesita internet solo esa vez); después funciona 100% offline.
4. Se abre solo el navegador en `http://127.0.0.1:8177`.
   Dejar la ventana negra abierta mientras se usa el sistema.

## Carga inicial de datos

La base ya viene cargada con el inventario. Si hiciera falta reimportar desde
los Excel originales:

```
python importar_excel.py "CONTROL DE HERRAMIENTAS.xlsm" "Inventario (1).xlsx"
```

El import es idempotente: actualiza herramientas por código y no duplica
movimientos ya cargados.

## Qué hace

- **Registrar**: entregas y devoluciones en una sola pantalla, con búsqueda
  por código o nombre, stock y ubicación a la vista. En devolución muestra
  chips con lo que el trabajador tiene pendiente (un clic completa el formulario).
  Valida stock disponible y pendientes; se puede forzar si el inventario está desactualizado.
- **Herramientas**: catálogo con ubicación física (góndola/módulo/estante),
  inventario, prestadas y disponibles. Detalle con historial y quién la tiene.
- **Trabajadores**: pendientes por persona e historial.
- **Historial**: todos los movimientos con filtros y exportación a CSV
  (se abre directo en Excel). Permite eliminar un movimiento para corregir errores de carga.
- **Maestros**: alta de herramientas, trabajadores, almacenistas y condiciones.

## Resguardo (backup)

Toda la información vive en un solo archivo: `data/panol.db`.
Copiarlo periódicamente a un pendrive o carpeta de red es suficiente.
Contiene nombres y DNI del personal: guardarlo en un lugar con acceso restringido.

## Estructura

```
app.py             aplicación Flask (rutas + API de autocompletado)
run.py             servidor local (waitress) + apertura del navegador
schema.sql         esquema de la base
importar_excel.py  importador de los Excel originales
templates/         páginas (Jinja)
static/            estilos y JS del autocompletado
data/panol.db      base de datos SQLite
iniciar.bat        arranque con doble clic
```
