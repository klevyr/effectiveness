# Efectividad SMS

## Descripción general

Este proyecto automatiza la medición de efectividad de envíos de SMS para áreas de cobranzas y gestión comercial. Su objetivo es determinar si un mensaje fue entregado o no, cruzando la información del gestor y del proveedor para obtener un indicador consolidado por fecha, entidad, marca y campaña.

El flujo procesa:

- datos del gestor (registro de envíos y metadata comercial),
- datos del proveedor/vendor (estado del mensaje y respuesta operadora),
- validaciones internas del resultado,
- generación de reportes exportables y reportes por longitud.

## Objetivo funcional

La conciliación consiste en identificar el estado final de cada mensaje. Para ello, el sistema cruza:

- el log del gestor (Broadcast `TMSMT20U` / Metroline `TMSMT13U`),
- los archivos del proveedor (vendor),
- la información de campaña, marca, entidad y tipo de SMS que solo aparece en gestor.

Como no siempre existe una clave única compartida confiable, el proceso realiza un cruce por campos como `message`, `mobilenumber` y `transactionId`, apoyado además en un cálculo relacionado con el tiempo de envío y generación del mensaje para casos sin transacción o con información parcial.

## Estado del proceso

El sistema clasifica los resultados en dos niveles:

- `ApplicationStatus`: estado reportado por el proveedor hacia la operadora.
- `PlatformStatus`: respuesta real de la operadora, cuando existe.

La relación vigente del proyecto es la siguiente:

| ApplicationStatus | PlatformStatus | Estado_Proveedor | Estado_Operadora |
|---|---|---|---|
| SUBMITD | DELIVRD | EXITOSO | EXITOSO |
| SUBMITD | UNDELIV | EXITOSO | RECHAZADO |
| UNDELIV | UNDELIV | RECHAZADO | RECHAZADO |
| * | -- | RECHAZADO | RECHAZADO |

## Estructura del proyecto

- `src/efectividad/cli.py`: punto de entrada del CLI.
- `src/efectividad/config.py`: carga de configuración y variables de entorno.
- `src/efectividad/loader.py`: lectura y normalización de datos del gestor y vendor.
- `src/efectividad/transformer.py`: generación del consolidado y reportes globales.
- `src/efectividad/exporter.py`: exportación a reportes.
- `src/efectividad/validator.py`: validación de resultados.
- `cfg/dev.yml`: configuración del entorno actual.
- `data/`: almacenamiento de datos procesados por fecha.
- `vendor/`: archivos del proveedor descargados.
- `transfers/`: transferencias AS400.
- `exportaciones/`: reportes generados.

## Requisitos

- Python >= 3.10
- Dependencias definidas en `pyproject.toml`
- Variables de entorno configuradas para acceso SFTP y AS400:
  - `SFTP_HOST`
  - `SFTP_PORT` (opcional, por defecto `22`)
  - `SFTP_UID`
  - `SFTP_PWD`
  - `AS400_USER`
  - `AS400_PASS`

## Instalación

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

pip install -e .
```

## Configuración

El proyecto usa archivos YAML en la carpeta `cfg/`. El entorno por defecto es `dev`:

```bash
cfg/dev.yml
```

Los valores de conexión no se dejan en el archivo de configuración; el proyecto los toma desde variables de entorno o desde un archivo `.env` ubicado en la raíz del proyecto.

## Uso del CLI

El punto de entrada es:

```bash
efectividad
```

### 1) Procesar efectividad completa

Ejecuta el flujo completo: descarga de transferencias, carga de gestor y vendor, generación de efectividad, validación y reporte global.

```bash
# efectividad de dia anterior (defecto)
efectividad process
# otras variaciones de acuerdo a la necesidad
efectividad process --fecha 20260917
efectividad process --desde 20260901 --hasta 20260915
efectividad process --desde 20260901
efectividad process --fecha 20260917 --skip-transfers
efectividad process --fecha 20260917 --skip-vendor
efectividad process --fecha 20260917 --skip-transfers --skip-vendor
efectividad process --env dev
```

Variaciones reales del comando:

- `--fecha` o `-f`: fecha exacta en formato `YYYYMMDD`.
- `--desde` / `-d` y `--hasta` / `-h`: rango de fechas.
- `--skip-transfers`: omite la descarga de transferencias AS400.
- `--skip-vendor`: omite la descarga de archivos del proveedor desde SFTP.
- `--env` / `-e`: entorno de configuración (`dev` por defecto).

Si no se indica ninguna fecha, el sistema toma el día anterior por defecto.

### 2) Generar reportes exportables

Al igual que otras entregas los reportes se generan conforme a las definiciones de cada hoja dentro del archivo de configuracion `./cfg/EfectividadConfig.xlsx` y adicionalmente informacion de Pichincha y BGR descritos en la seccion `other_reports` dentro de `dev.yml`.

```bash
# efectividad de dia anterior (defecto)
efectividad report
# otras variaciones de acuerdo a la necesidad
efectividad report --fecha 20260917
efectividad report --desde 20260901 --hasta 20260915
efectividad report --env dev
```

Este comando genera los reportes Excel asociados a la efectividad y, además, crea el reporte de longitudes.

### 3) Limpiar datos procesados

```bash
efectividad clean --fecha 20260917
efectividad clean --desde 20260901 --hasta 20260915
efectividad clean --env dev
```

Elimina los datos de las tablas `gestor`, `vendor`, `consolidado` y `reporte` para la(s) fecha(s) indicadas.

### 4) Consultar estado de datos disponibles

```bash
efectividad status --tabla reporte --env dev
efectividad status --tabla gestor
efectividad status -t consolidado
```

Muestra las fechas disponibles en la tabla indicada y una vista resumida del porcentaje de registros efectivos.

## Flujo operativo recomendado

1. Configurar variables de entorno (`.env` o entorno del sistema).
2. Ejecutar el proceso completo (incluido descarga gestor y proveedor):

   ```bash
   efectividad process --fecha 20260917
   ```

3. Generar reportes con base en `EfectividadConfig.xlsx` y `other_reports`:

   ```bash
   efectividad report --fecha 20260917
   ```

### Otras opciones

Revisar estado interno:

```bash
efectividad status --tabla reporte --env dev
```

Limpiar informacion historica:

```bash
efectividad clean --tabla reporte --env dev
```

## Notas de mantenimiento

- La configuración del entorno se encuentra en `cfg/dev.yml` y puede ampliarse a otros archivos como `cfg/prod.yml` o similares.
- Los datos procesados se guardan en `data/` en formato Parquet por tabla y fecha.
- El proyecto no requiere subir archivos ZIP manualmente al directorio `vendor`; el CLI puede descargarlos y dejar la estructura lista para el proceso.
- La información histórica o versiones anteriores del estado del proyecto fue removida porque no refleja el comportamiento actual del sistema.
