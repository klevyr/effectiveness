"""Generación de reportes con Polars.

Exporta informes de efectividad a Excel basándose en la configuración
de estados y entidades.
"""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl
import pandas as pd

from efectividad.logger import setup_logger
from efectividad.storage import read_parquet
from efectividad.loader import load_efectividad_config

log = setup_logger()

_ID_RE = re.compile(r"^[0-9]{10}$")


def generate_reports(
    base_path: Path,
    date_str: str,
    output_cols: list,
    other_reports: dict[str, str] | None = None,
) -> list[Path]:
    """Genera reportes de efectividad exportados a Excel.

    Parameters
    ----------
    base_path : Path
        Directorio raíz de datos Parquet.
    date_str : str
        Fecha en formato ``YYYYMMDD``.
    other_reports : dict[str, str] | None
        Entidades adicionales ``{nombre: entidad_id}``.

    Returns
    -------
    list[Path]
        Rutas de archivos generados.
    """
    report_dir = base_path.parent / "exportaciones" / date_str[:6]
    report_dir.mkdir(parents=True, exist_ok=True)

    report_lf = read_parquet(base_path, "reporte", date_str)
    if report_lf.collect().is_empty():
        log.warning("No hay datos de reporte para %s", date_str)
        return []

    efectividad_cfg = load_efectividad_config(base_path)

    exported: list[Path] = []
    for _report in efectividad_cfg.keys():
        rpt_filename = f"SMS-{_report}_{date_str}.xlsx"
        file_path = report_dir / rpt_filename
        cfg_data = efectividad_cfg[_report]
        
        informe_lf = _export_report_efectividad(
            report_lf,
            cfg_data,
            file_path,
            output_cols
        )
        exported.append(file_path)

        if _report == "General":
            rpt_filename = f"SMS-Rechazos_{date_str}.xlsx"
            file_path = report_dir / rpt_filename
            rechazos = _export_report_rechazos(informe_lf, file_path)
            exported.append(file_path)

    # --- Reportes por entidad ---
    if other_reports:
        for nombre, entidad_id in other_reports.items():
            ent_report = report_lf.filter(pl.col("Entidad") == entidad_id)
            if not ent_report.select(pl.len()).collect().is_empty():
                file_ent = report_dir / f"SMS-OTH-{nombre}_{date_str}.xlsx"
                _export_report_entidad(ent_report, file_ent, output_cols)
                exported.append(file_ent)

    log.info("Reportes generados: %d archivos", len(exported))
    return exported


def generate_length_report(
    base_path: Path,
    date_str: str,
) -> pl.LazyFrame | None:
    """Genera reporte de SMS con longitud mayor a 160 caracteres.

    Returns
    -------
    pl.LazyFrame | None
        LazyFrame con los SMS largos, o ``None`` si no hay.
    """
    report_dir = base_path.parent / "exportaciones" / date_str[:6]
    report_dir.mkdir(parents=True, exist_ok=True)

    report_lf = read_parquet(base_path, "reporte", date_str)
    if report_lf.collect().is_empty():
        log.warning("No hay datos de reporte para %s", date_str)
        raise FileNotFoundError("No hay datos de reporte para %s", date_str)
    
    long_msgs = report_lf.filter(pl.col("Mensaje").str.len_chars() > 160)
    if long_msgs.collect().is_empty():
        log.info("No hay SMS con longitud > 160 para %s", date_str)
        return None

    log.info("SMS largos encontrados: %d", long_msgs.select(pl.len()).collect().item())

    # Resumen por código y campaña
    summary = long_msgs.group_by(["Entidad","Marca","CdMensaje"]).agg(
        pl.col("NumCelular").count().alias("Cantidad")
    )

    # Exportar
    export_dir = base_path.parent / "exportaciones" / date_str[:6]
    export_dir.mkdir(parents=True, exist_ok=True)
    file_out = export_dir / f"SMS-OTH-LONGITUDES_{date_str}.xlsx"

    writer = pd.ExcelWriter(file_out, engine='openpyxl')
    summary.collect().to_pandas().to_excel(writer, sheet_name="Resume", index=False)
    long_msgs.collect().to_pandas().to_excel(writer, sheet_name="Database", index=False)
    writer.close()

    log.info("Reporte de longitudes exportado: %s", file_out)
    return summary


def _export_report_efectividad(
        report: pl.LazyFrame,
        cfg: pl.LazyFrame,
        output_filepath: Path,
        output_cols: list
    ) -> pl.LazyFrame:
    """Exporta un reporte con resume y database."""
    # Crear resume: agrupar por Area x Estado
    informe = report.join(
        cfg,
        on=["Marca","CdMensaje"],
        how="inner"
    ).select(output_cols)

    resume = (
        informe.group_by(["Fecha", "Desc_Area", "Estado_Proveedor", "Estado_Operadora"])
        .agg(pl.col("NumCelular").count().alias("Volumen"))
    ).collect().to_pandas()

    writer = pd.ExcelWriter(output_filepath, engine='openpyxl')
    resume.to_excel(writer, sheet_name="Resume", index=False)
    informe.collect().to_pandas().to_excel(writer, sheet_name="Database", index=False)
    writer.close()

    log.info("Reporte exportado: %s", output_filepath.name)

    return informe


def _export_report_entidad(
        report: pl.LazyFrame,
        output_filepath: Path,
        output_cols: list,
    ) -> pl.LazyFrame:
    """Exporta un reporte con resume y database."""
    # Crear resume: agrupar por Area x Estado
    cols_entidad = [col for col in output_cols if col not in ["Desc_Notificacion", "Desc_Area"]]

    informe = report.select(cols_entidad)

    resume = (
        report.group_by(["Fecha", "Estado_Proveedor", "Estado_Operadora"])
        .agg(pl.col("NumCelular").count().alias("Volumen"))
    ).collect().to_pandas()

    writer = pd.ExcelWriter(output_filepath, engine='openpyxl')
    resume.to_excel(writer, sheet_name="Resume", index=False)
    informe.collect().to_pandas().to_excel(writer, sheet_name="Database", index=False)
    writer.close()

    log.info("Reporte exportado: %s", output_filepath.name)

    return informe


def _export_report_rechazos(report: pl.LazyFrame, output_path: Path) -> pl.LazyFrame:
    """Filtra registros rechazados para análisis de cartera."""
    filtered = (
        report.with_columns(
            pl.col("Tarjeta_Cuenta").cast(pl.Int64).alias("Tarjeta_Cuenta_Num")
        )
        .filter(
            (pl.col("Estado_Operadora") == "RECHAZADO")
            & (pl.col("Estado_Proveedor") == "EXITOSO")
            & (pl.col("Volumen") > 10)
            & (pl.col("Porc_Rechazado") == 100.0)
            & (pl.col("Entidad").is_in(["DC", "ID"]))
            & (pl.col("Tarjeta_Cuenta_Num") > 0)
            & (pl.col("Desc_Area") == "MONITOREO DE RIESGO")
            & (pl.col("Num_Doc_Identificacion").str.contains(r"^\d{10}$"))
            & (
                pl.col("DescriptionStatus").is_in(
                    [
                        "MT number is unknown (code 1)",
                        "Teleservice Not Provisioned (code 11)",
                    ]
                )
            )
        )
        .unique(subset=["Num_Doc_Identificacion", "NumCelular"])
    )

    filtered.collect().to_pandas().to_excel(output_path, index=False)

    log.info("Rechazos filtrados: %d registros", filtered.select(pl.len()).collect().item())
    return filtered
