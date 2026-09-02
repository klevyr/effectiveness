"""Generación de reportes con Polars.

Exporta informes de efectividad a Excel basándose en la configuración
de estados y entidades.
"""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl

from efectividad.logger import setup_logger
from efectividad.storage import read_parquet

log = setup_logger()

_ID_RE = re.compile(r"^[0-9]{10}$")


def generate_reports(
    base_path: Path,
    date_str: str,
    statuses: list[dict],
    other_reports: dict[str, str] | None = None,
) -> list[Path]:
    """Genera reportes de efectividad exportados a Excel.

    Parameters
    ----------
    base_path : Path
        Directorio raíz de datos Parquet.
    date_str : str
        Fecha en formato ``YYYYMMDD``.
    statuses : list[dict]
        Definiciones de estado del YAML.
    other_reports : dict[str, str] | None
        Entidades adicionales ``{nombre: entidad_id}``.

    Returns
    -------
    list[Path]
        Rutas de archivos generados.
    """
    report_dir = base_path.parent / "exportaciones" / date_str[:6]
    report_dir.mkdir(parents=True, exist_ok=True)

    report = read_parquet(base_path, "reporte", date_str)
    if report.collect().is_empty():
        log.warning("No hay datos de reporte para %s", date_str)
        return []

    exported: list[Path] = []

    # --- Reporte General ---
    file_general = report_dir / f"SMS-General_{date_str}.xlsx"
    _export_report(report, file_general)
    exported.append(file_general)

    # --- Rechazos (solo para General) ---
    rechazos = _filter_rechazos(report)
    if rechazos.height > 0:
        file_rechazos = report_dir / f"SMS-Rechazos_{date_str}.xlsx"
        rechazos.write_excel(file_rechazos)
        log.info("Rechazos exportados: %s", file_rechazos)
        exported.append(file_rechazos)
    else:
        log.info("No se generó informacion de rechazos para %s", date_str)

    # --- Reportes por entidad ---
    if other_reports:
        for nombre, entidad_id in other_reports.items():
            ent_report = report.filter(pl.col("Entidad") == entidad_id)
            if not ent_report.is_empty():
                file_ent = report_dir / f"SMS-OTH-{nombre}_{date_str}.xlsx"
                _export_report(ent_report, file_ent)
                exported.append(file_ent)

    log.info("Reportes generados: %d archivos", len(exported))
    return exported


def generate_length_report(
    base_path: Path,
    date_str: str,
) -> pl.DataFrame | None:
    """Genera reporte de SMS con longitud mayor a 160 caracteres.

    Returns
    -------
    pl.DataFrame | None
        DataFrame con los SMS largos, o ``None`` si no hay.
    """
    report = read_parquet(base_path, "reporte", date_str)
    if report.is_empty():
        return None

    long_msgs = report.filter(pl.col("Mensaje").str.len_chars() > 160)
    if long_msgs.is_empty():
        log.info("No hay SMS con longitud > 160 para %s", date_str)
        return None

    log.info("SMS largos encontrados: %d", long_msgs.height)

    # Resumen por código y campaña
    summary = long_msgs.group_by(["CdMensaje", "Desc_Campania"]).agg(
        pl.col("TransactionId").count().alias("Cantidad")
    )

    # Exportar
    export_dir = base_path.parent / "exportaciones" / date_str[:6]
    export_dir.mkdir(parents=True, exist_ok=True)
    file_out = export_dir / f"SMS-OTH-LONGITUDES_{date_str}.xlsx"

    with pl.ExcelWriter(file_out) as writer:
        summary.write_excel(writer, sheet_name="Resume")
        long_msgs.write_excel(writer, sheet_name="Database")

    log.info("Reporte de longitudes exportado: %s", file_out)
    return summary


def _export_report(report: pl.DataFrame, filepath: Path) -> None:
    """Exporta un reporte con resume y database."""
    # Crear resume: agrupar por Area x Estado
    if "Fecha" in report.columns:
        group_cols = ["Fecha", "Estado_Proveedor", "Estado_Operadora"]
    else:
        group_cols = ["Estado_Proveedor", "Estado_Operadora"]

    resume = report.group_by(group_cols).agg(
        pl.col("TransactionId").count().alias("Volumen")
    )

    with pl.ExcelWriter(filepath) as writer:
        resume.write_excel(writer, sheet_name="Resume")
        report.write_excel(writer, sheet_name="Database")

    log.info("Reporte exportado: %s", filepath)


def _filter_rechazos(report: pl.DataFrame) -> pl.DataFrame:
    """Filtra registros rechazados para análisis de cartera."""
    required_cols = [
        "Estado_Operadora",
        "Estado_Proveedor",
        "Volumen",
        "Porc_Rechazo",
        "Entidad",
        "Tarjeta_Cuenta",
        "Desc_AreaCampania",
        "DescriptionStatus",
        "Num_Doc_Identificacion",
        "NumCelular",
    ]
    if not all(c in report.columns for c in required_cols):
        return pl.DataFrame()

    filtered = report.filter(
        (pl.col("Estado_Operadora") == "No Entregado")
        & (pl.col("Estado_Proveedor") == "Entregado")
        & (pl.col("Volumen") > 10)
        & (pl.col("Porc_Rechazo") == 100.0)
        & (pl.col("Entidad").is_in(["DC", "ID"]))
        & (pl.col("Desc_AreaCampania") == "Analisis de Cartera")
        & (
            pl.col("DescriptionStatus").is_in(
                [
                    "MT number is unknown (code 1)",
                    "Teleservice Not Provisioned (code 11)",
                ]
            )
        )
    )

    # Validar cédula de 10 dígitos
    if not filtered.is_empty():
        filtered = filtered.filter(
            pl.col("Num_Doc_Identificacion").str.contains(r"^\d{10}$")
        )
        filtered = filtered.unique(subset=["Num_Doc_Identificacion", "NumCelular"])

    log.info("Rechazos filtrados: %d registros", filtered.height)
    return filtered
