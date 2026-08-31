"""CLI principal para el proceso de efectividad SMS.

Uso:
    efectividad process --fecha 20251022
    efectividad process --desde 20251001 --hasta 20251015
    efectividad report --fecha 20251022
    efectividad download --limite-dias 18
    efectividad clean --fecha 20251022
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import typer

from efectividad.config import load_config
from efectividad.exporter import generate_length_report, generate_reports
from efectividad.loader import load_gestor, load_vendor
from efectividad.logger import setup_logger
from efectividad.storage import delete_date, read_parquet
from efectividad.transformer import generate_effectiveness, generate_global_report
from efectividad.utils import OSTransfersController, SFTPManager
from efectividad.validator import check_effectiveness

app = typer.Typer(
    name="efectividad",
    help="""
▄▖▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄\n
▄▖▐▘    ▗ ▘  ▘ ▌   ▌
▙▖▜▘█▌▛▘▜▘▌▌▌▌▛▌▀▌▛▌
▙▖▐ ▙▖▙▖▐▖▌▚▘▌▙▌█▌▙▌

Generador de reportes de efectividad SMS.
""",
    add_completion=False,
)
log = setup_logger()


def _date_range(desde: str, hasta: str) -> list[str]:
    """Genera lista de fechas YYYYMMDD entre desde y hasta (inclusive)."""
    start = datetime.strptime(desde, "%Y%m%d")
    end = datetime.strptime(hasta, "%Y%m%d")
    dates = []
    current = start
    while current <= end:
        dates.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return dates


def _resolve_dates(
    fecha: Optional[str],
    desde: Optional[str],
    hasta: Optional[str],
    yesterday: bool = False,
) -> list[str]:
    """Resuelve las fechas a procesar según las opciones CLI."""
    if fecha:
        return [fecha]

    if desde and hasta:
        return _date_range(desde, hasta)

    if desde and not hasta:
        return _date_range(desde, desde)

    if yesterday:
        dt = datetime.now() - timedelta(days=1)
        return [dt.strftime("%Y%m%d")]

    dt = datetime.now() - timedelta(days=1)
    return [dt.strftime("%Y%m%d")]


# ---------------------------------------------------------------------------
# process: Flujo completo de efectividad
# ---------------------------------------------------------------------------


@app.command()
def process(
    fecha: Optional[str] = typer.Option(
        None, "--fecha", "-f", help="Fecha específica (YYYYMMDD)"
    ),
    desde: Optional[str] = typer.Option(
        None, "--desde", "-d", help="Fecha inicio rango (YYYYMMDD)"
    ),
    hasta: Optional[str] = typer.Option(
        None, "--hasta", "-h", help="Fecha fin rango (YYYYMMDD)"
    ),
    skip_transfers: bool = typer.Option(
        False, "--skip-transfers", "-st", help="Omitir descarga de transferencias AS400"
    ),
    skip_vendor: bool = typer.Option(
        False, "--skip_vendor", "-sv", help="Omitir descarga de proveedores"
    ),
    env: str = typer.Option("dev", "--env", "-e", help="Entorno de configuración"),
) -> None:
    """Ejecuta el proceso completo: carga gestor → vendor → efectividad → validación."""
    cfg = load_config(env)
    base_path: Path = cfg["paths"]["data"]
    transfer_dir: Path = cfg["paths"]["transfer"]
    vendor_dir: Path = cfg["paths"]["vendor"]

    dates = _resolve_dates(fecha, desde, hasta, yesterday=True)
    statuses = cfg.get("statuses", [])
    checks = cfg.get("validation_checks", {})
    gestor_columns = cfg.get("gestor_columns", [])
    vendor_columns = cfg.get("vendor_columns", [])

    log.info("Procesando %d fecha(s): %s", len(dates), ", ".join(dates))

    for date_str in dates:
        log.info("===== INICIO %s =====", date_str)

        # 1. Transferencias AS400 (si aplica)
        if not skip_transfers:
            log.info("1/6 Descargando transferencias AS400...")
            _run_transfers(cfg, transfer_dir, date_str)
        else:
            log.info("1/6 Transferencias omitidas (--skip-transfers)")

        # 1.1 Desacrga archivos sftp (si aplica)
        if not skip_vendor:
            log.info("2/6 Descargando archivos proveedor...")
            # _run_transfers(cfg, transfer_dir, date_str)
        else:
            log.info("2/6 Archivos omitidos (--skip-vendor)")

        # 2. Cargar gestor
        log.info("2/6 Cargando datos del gestor...")
        load_gestor(
            transfer_dir,
            base_path,
            date_str,
            gestor_columns=gestor_columns,
            skip_transfers=skip_transfers,
        )

        # 3. Cargar vendor
        log.info("3/6 Cargando datos del vendor...")
        load_vendor(
            vendor_dir,
            base_path,
            date_str,
            vendor_columns=vendor_columns,
            skip_vendor=skip_vendor,
        )

        # 4. Generar efectividad
        log.info("4/6 Generando consolidado de efectividad...")
        consol = generate_effectiveness(base_path, date_str)

        # 5. Generar reporte global
        log.info("5/6 Generando reporte global...")
        global_report = generate_global_report(consol, base_path, date_str, statuses)

        # Validación
        log.info("Validando resultados...")
        check_effectiveness(base_path, date_str, checks)

        log.info("===== COMPLETADO %s =====", date_str)

    log.info("Proceso finalizado para %d fecha(s)", len(dates))


# ---------------------------------------------------------------------------
# report: Genera reportes de exportación
# ---------------------------------------------------------------------------


@app.command()
def report(
    fecha: Optional[str] = typer.Option(
        None, "--fecha", "-f", help="Fecha específica (YYYYMMDD)"
    ),
    desde: Optional[str] = typer.Option(
        None, "--desde", "-d", help="Fecha inicio rango (YYYYMMDD)"
    ),
    hasta: Optional[str] = typer.Option(
        None, "--hasta", "-h", help="Fecha fin rango (YYYYMMDD)"
    ),
    env: str = typer.Option("dev", "--env", "-e", help="Entorno de configuración"),
) -> None:
    """Genera reportes Excel de efectividad."""
    cfg = load_config(env)
    base_path: Path = cfg["paths"]["data"]

    dates = _resolve_dates(fecha, desde, hasta)
    statuses = cfg.get("statuses", [])
    other_reports = cfg.get("other_reports", {})

    for date_str in dates:
        log.info("Generando reportes para %s...", date_str)

        files = generate_reports(base_path, date_str, statuses, other_reports)
        for f in files:
            log.info("  → %s", f)

        log.info("Generando reporte de longitudes...")
        generate_length_report(base_path, date_str)

    log.info("Reportes completados")


# ---------------------------------------------------------------------------
# download: Descarga archivos desde SFTP
# ---------------------------------------------------------------------------


@app.command()
def download(
    limite_dias: int = typer.Option(
        18, "--limite-dias", "-l", help="Número máximo de días a mostrar"
    ),
    env: str = typer.Option("dev", "--env", "-e", help="Entorno de configuración"),
) -> None:
    """Descarga archivos vendor desde el servidor SFTP."""
    cfg = load_config(env)
    sftp_cfg = cfg["sftp"]
    vendor_dir: Path = cfg["paths"]["vendor"]

    sftp = SFTPManager(
        host=sftp_cfg["host"],
        port=sftp_cfg["port"],
        uid=sftp_cfg["uid"],
        pwd=sftp_cfg["pwd"],
        remote_path=cfg.get("sftp", {}).get(
            "remote_path", "./LINK MOBILE LINKMBL BTS_ SMS/"
        ),
        local_dir=vendor_dir,
    )

    files = sftp.get_files_list()
    available = sorted(files, reverse=True)[:limite_dias]

    if not available:
        log.warning("No hay archivos disponibles en SFTP")
        return

    log.info("Archivos disponibles (últimos %d días):", limite_dias)
    for i, f in enumerate(available, 1):
        log.info("  %2d. %s", i, f)

    # Descargar el más reciente
    selected = available[0]
    log.info("Descargando archivo más reciente: %s", selected)
    sftp.download_file(selected)
    log.info("Descarga completada")


# ---------------------------------------------------------------------------
# clean: Elimina datos procesados
# ---------------------------------------------------------------------------


@app.command()
def clean(
    fecha: Optional[str] = typer.Option(
        None, "--fecha", "-f", help="Fecha específica (YYYYMMDD)"
    ),
    desde: Optional[str] = typer.Option(
        None, "--desde", "-d", help="Fecha inicio rango (YYYYMMDD)"
    ),
    hasta: Optional[str] = typer.Option(
        None, "--hasta", "-h", help="Fecha fin rango (YYYYMMDD)"
    ),
    env: str = typer.Option("dev", "--env", "-e", help="Entorno de configuración"),
) -> None:
    """Elimina datos procesados para una fecha o rango de fechas."""
    cfg = load_config(env)
    base_path: Path = cfg["paths"]["data"]

    dates = _resolve_dates(fecha, desde, hasta)
    tables = ["gestor", "vendor", "consolidado", "reporte"]

    for date_str in dates:
        log.info("Eliminando datos para %s...", date_str)
        for table in tables:
            deleted = delete_date(base_path, table, date_str)
            if deleted:
                log.info("  Eliminado: %s/%s", table, date_str)

    log.info("Limpieza completada")


# ---------------------------------------------------------------------------
# status: Muestra fechas disponibles en almacenamiento
# ---------------------------------------------------------------------------


@app.command()
def status(
    tabla: str = typer.Option("reporte", "--tabla", "-t", help="Tabla a consultar"),
    env: str = typer.Option("dev", "--env", "-e", help="Entorno de configuración"),
) -> None:
    """Muestra las fechas disponibles en el almacenamiento Parquet."""
    cfg = load_config(env)
    base_path: Path = cfg["paths"]["data"]

    from efectividad.storage import list_dates

    dates = list_dates(base_path, tabla)
    if not dates:
        log.info("No hay datos para la tabla '%s'", tabla)
        return

    log.info("Fechas disponibles en '%s':", tabla)
    for d in dates:
        df = read_parquet(base_path, tabla, d)
        log.info("  %s → %d registros", d, df.height)


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _run_transfers(cfg: dict, transfer_dir: Path, date_str: str) -> None:
    """Ejecuta la descarga de transferencias AS400 para una fecha."""
    as400_cfg = cfg.get("as400", {})
    transfers = OSTransfersController(
        transfer_folder=transfer_dir,
        as400_user=as400_cfg.get("user", ""),
        as400_pass=as400_cfg.get("password", ""),
        acsbundle_path=as400_cfg.get("acsbundle_path", "./.cfg/acsbundle.jar"),
    )
    transfers.acsbundle_init()
    # Configurar filtros de transferencia
    for file_name in cfg["as400"].get("transfer_icons", []):
        transfers.set_config_transfer(
            file_name,
            config_section="SQL",
            config_key="Where",
            config_value=f"S1XX84W NOT IN ('0000000000','0') AND S1Z141Q2 = '{date_str}'",
        )
        transfers.acsbundle_download()
