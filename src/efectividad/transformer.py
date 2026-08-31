"""Transformaciones y cruces de efectividad.

Realiza el JOIN entre gestor y vendor para generar el consolidado,
usando Polars en lugar de SQL.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from efectividad.loader import load_stats
from efectividad.logger import setup_logger
from efectividad.storage import read_parquet, write_parquet, write_partitioned_parquet

log = setup_logger()


def generate_effectiveness(
    base_path: Path,
    date_str: str,
) -> pl.LazyFrame:
    """Cruza gestor con vendor para generar el consolidado de efectividad.

    Realiza dos joins:
    1. Join estándar por fecha + numcel + MensajeMD5 + rango timestamp (-10 a 1200s)
       Excluye código 0260 (PINES).
    2. Join para PINES (código 0260) con rango de timestamp más ajustado (-10 a 600s).

    Parameters
    ----------
    base_path : Path
        Directorio raíz de datos Parquet.
    date_str : str
        Fecha en formato ``YYYYMMDD``.

    Returns
    -------
    pl.LazyFrame
        Consolidado de efectividad.
    """
    ges = read_parquet(base_path, "gestor", date_str)
    vend = read_parquet(base_path, "vendor", date_str)

    if ges.collect().is_empty():
        log.error("No hay datos de gestor para %s", date_str)
        return pl.LazyFrame()
    if vend.collect().is_empty():
        log.error("No hay datos de vendor para %s", date_str)
        return pl.LazyFrame()

    log.info(
        "Generando efectividad para %s (gestor=%d, vendor=%d)",
        date_str,
        ges.select(pl.len()).collect().item(),
        vend.select(pl.len()).collect().item(),
    )

    # Preparar campos de join
    ges = ges.with_columns(pl.col("NumCel").alias("NumCelular"))
    vend = vend.with_columns(pl.col("MobileNumber").alias("NumCelular"))

    # Join 1: Estándar (excluye PINES 0260)
    ges_std = ges.filter(pl.col("IdCodigo") != "0260")
    join_std = _do_join(ges_std, vend, ts_min=-10, ts_max=1200)

    # Join 2: PINES (solo código 0260)
    ges_pin = ges.filter(pl.col("IdCodigo") == "0260")
    join_pin = _do_join(ges_pin, vend, ts_min=-10, ts_max=600, cross_type="pin")

    # Consolidar
    frames = [lf for lf in [join_std, join_pin] if not lf.collect().is_empty()]
    if not frames:
        log.warning("No se generaron cruces para %s", date_str)
        return pl.LazyFrame()

    result = pl.concat(frames, how="diagonal_relaxed")
    log.info("Consolidado generado: %s registros", result.select(pl.len()).collect().item())
    # write_parquet(result, base_path, "consolidado", date_str, mode="overwrite")
    return result


def _do_join(
    ges: pl.LazyFrame,
    vend: pl.LazyFrame,
    ts_min: int,
    ts_max: int,
    cross_type: str = "standard",
) -> pl.LazyFrame:
    """Realiza el LEFT JOIN entre gestor y vendor con filtro de timestamp.

    Parameters
    ----------
    ts_min, ts_max : int
        Rango permitido de diferencia de segundos entre gestor y vendor.
    """
    if ges.collect().is_empty():
        return pl.LazyFrame()

    _on_join = ["NumCelular", "MessageMD5"]
    if cross_type != "standard":
        _on_join = ["NumCelular"]

    # Join por número de celular + mensaje MD5
    joined = ges.join(
        vend,
        on=_on_join,
        how="left",
        suffix="_vend",
    )

    # Calcular diferencia de segundos
    joined = joined.with_columns(
        (pl.col("tsvend") - pl.col("tsges")).alias("seconds_diff")
    )

    # Filtrar por rango de tiempo
    joined = joined.filter(
        (pl.col("seconds_diff") >= ts_min) & (pl.col("seconds_diff") <= ts_max)
    )

    # Seleccionar y renombrar columnas al formato consolidado
    result = joined.select(
        [
            pl.col("Fecha"),
            pl.col("Hora"),
            pl.col("Entidad"),
            pl.col("Marca"),
            pl.col("IdCodigo").alias("CdMensaje"),
            pl.col("Tarjeta_Cuenta"),
            pl.col("Cedula").alias("Num_Doc_Identificacion"),
            pl.col("NumCel").alias("NumCelular"),
            pl.col("IdUsuario"),
            pl.col("ConfId"),
            pl.col("TransactionId"),
            pl.col("Mensaje"),
            pl.col("Carrier"),
            pl.col("Date_parsed").alias("Fecha_Hora_YP"),
            pl.col("ApplicationStatus"),
            pl.col("PlatformStatus"),
            pl.col("ShortCode"),
            pl.col("DescriptionStatus"),
            pl.col("seconds_diff"),
        ]
    )

    return result


def generate_global_report(
    consol: pl.LazyFrame,
    base_path: Path,
    date_str: str,
    statuses: list[dict],
) -> pl.LazyFrame:
    """Genera el reporte global cruzando consolidado con definiciones de estado.

    Parameters
    ----------
    base_path : Path
        Directorio raíz de datos Parquet.
    date_str : str
        Fecha en formato ``YYYYMMDD``.
    statuses : list[dict]
        Lista de definiciones de estado del YAML.

    Returns
    -------
    pl.LazyFrame
        Reporte global con estados asignados.
    """

    # Construir DataFrame de estados
    status_lf = pl.DataFrame(statuses).lazy()

    log.info("Generando estadisticas: %s", base_path)
    generate_stats_report(consol, base_path, date_str, status_lf)

    report = _match_statuses(consol, status_lf, date_str)
    stats = load_stats(base_path, date_str)

    # Agregar columnas de volumen (cada registro = 1 SMS)
    report = report.with_columns(
        [
            pl.lit(1).alias("Volumen"),
            pl.col("estado_proveedor")
            .map_elements(
                lambda x: 100.0 if x == "EXITOSO" else 0.0, return_dtype=pl.Float64
            )
            .alias("Porc_Exito"),
            pl.col("estado_proveedor")
            .map_elements(
                lambda x: 0.0 if x == "EXITOSO" else 100.0, return_dtype=pl.Float64
            )
            .alias("Porc_Rechazo"),
        ]
    )

    # Renombrar campos de estado
    report = report.rename(
        {
            "estado_proveedor": "Estado_Proveedor",
            "estado_operadora": "Estado_Operadora",
        }
    )

    log.info("Reporte global generado: %s registros", report.select(pl.len()).collect().item())
    write_parquet(report, base_path, "reporte", date_str, mode="overwrite")
    return report



def generate_stats_report(
    consol: pl.LazyFrame,
    base_path: Path,
    date_str: str,
    status_df: pl.LazyFrame,
) -> pl.LazyFrame:
    """Genera el reporte global cruzando consolidado con definiciones de estado.

    Parameters
    ----------
    base_path : Path
        Directorio raíz de datos Parquet.
    date_str : str
        Fecha en formato ``YYYYMMDD``.
    statuses : list[dict]
        Lista de definiciones de estado del YAML.

    Returns
    -------
    pl.LazyFrame
        Reporte global con estados asignados.
    """
    # Construir DataFrame de estados
    report = _match_statuses(consol, status_df, date_str)

    stats = report.group_by(["Fecha","NumCelular","Estado_Operadora"]).agg(
        [
            pl.len().alias("Envios")
        ]
    )
    stats = stats.with_columns(
        [
            pl.col("Fecha").str.slice(0,6).alias("MesID"),
            pl.col("Fecha").str.slice(6,8).alias("DiaID")
        ]
    )
    
    log.info("Reporte estadisticas generado. %s", base_path)
    write_partitioned_parquet(stats, base_path, "stats", part_fields=["MesID","DiaID"])
    return report


def _match_statuses(
    consol: pl.LazyFrame,
    status_df: pl.LazyFrame,
    date_str: str,
):
    # Mapear ApplicationStatus → Estado_Proveedor / Estado_Operadora
    # Regla: match exacto primero, luego wildcard "*"
    exact_match = status_df.filter(pl.col("application_status") != "*")
    wildcard_match = status_df.filter(pl.col("application_status") == "*")

    # Join con match exacto
    report = consol.join(
        exact_match,
        left_on=["ApplicationStatus", "PlatformStatus"],
        right_on=["application_status", "platform_status"],
        how="left",
    )

    # Para los que no matchearon, intentar con wildcard
    unmatched = report.filter(pl.col("estado_proveedor").is_null())
    if not unmatched.collect().is_empty():
        log.error("Se ha identificado estatus sin matchear en la fecha %s", date_str)
        matched_wild = unmatched.drop(["estado_proveedor", "estado_operadora"]).join(
            wildcard_match,
            left_on=["ApplicationStatus"],
            right_on=["application_status"],
            how="left",
        )
        # Combinar
        already_matched = report.filter(pl.col("estado_proveedor").is_not_null())
        report = pl.concat([already_matched, matched_wild], how="diagonal_relaxed")

    # Rellenar los que siguen sin match
    report = report.with_columns(
        [
            pl.col("estado_proveedor").fill_null("RECHAZADO"),
            pl.col("estado_operadora").fill_null("RECHAZADO"),
        ]
    )

    # Renombrar campos de estado
    report = report.rename(
        {
            "estado_proveedor": "Estado_Proveedor",
            "estado_operadora": "Estado_Operadora",
        }
    )

    return report
