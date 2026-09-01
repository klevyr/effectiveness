"""Carga de datos desde archivos gestor (CSV) y vendor (ZIP CSV).

Transforma y almacena los datos en Parquet vía la capa de storage.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import polars as pl

from efectividad.logger import setup_logger
from efectividad.storage import read_parquet, write_parquet

log = setup_logger()

_ONLY_ASCII = r"[^A-Za-z0-9,.\-]"


def _md5(text: str) -> str:
    return hashlib.md5(text.strip().encode("utf-8")).hexdigest()


def _parse_timestamp_gestor(fecha: str, hora: str) -> float:
    """Convierte Fecha+Hora del gestor a timestamp UTC."""
    dt = datetime.strptime(f"{fecha} {hora}", "%Y%m%d %H.%M.%S")
    return dt.replace(tzinfo=timezone.utc).timestamp()


# ---------------------------------------------------------------------------
# Gestor
# ---------------------------------------------------------------------------


def load_gestor(
    transfer_dir: str | Path,
    base_path: Path,
    date_str: str,
    gestor_columns: list[str] | None = None,
) -> pl.LazyFrame:
    """Lee archivos broadcast.csv y megareport.csv, transforma y almacena.

    Parameters
    ----------
    transfer_dir : str | Path
        Directorio donde se encuentran los CSVs del gestor.
    base_path : Path
        Directorio raíz de datos Parquet.
    date_str : str
        Fecha en formato ``YYYYMMDD``.
    gestor_columns : list[str] | None
        Nombres de columnas del gestor definidos en el YAML de configuración.
    skip_transfers : bool
        Si ``True``, omite la descarga de transferencias AS400.

    Returns
    -------
    pl.LazyFrame
        LazyFrame del gestor transformado.
    """
    if not gestor_columns:
        log.error("No se definieron columnas del gestor en la configuración")
        return pl.LazyFrame()

    gestor_schema = dict.fromkeys(gestor_columns, pl.Utf8)

    tdir = Path(transfer_dir)
    frames: list[pl.LazyFrame] = []

    for csv_name, tipo in [("broadcast.csv", "B"), ("megareport.csv", "M")]:
        csv_path = tdir / csv_name
        if not csv_path.exists():
            log.warning("Archivo gestor no encontrado, omitiendo: %s", csv_path)
            continue
        log.info("Leyendo gestor: %s", csv_path)
        df = pl.scan_csv(
            csv_path,
            has_header=False,
            new_columns=gestor_columns,
            schema_overrides=gestor_schema,
            encoding="utf8-lossy",
            null_values=[""],
        )
        df = df.with_columns(pl.lit(tipo).alias("TipoCola"))
        frames.append(df)

    if not frames:
        log.error("No se encontraron archivos de gestor en %s", tdir)
        return pl.LazyFrame()

    result = pl.concat(frames, how="diagonal_relaxed")

    # Limpiar nulos en columnas de texto
    result = result.with_columns(
        [
            pl.col("Cedula").fill_null(""),
            pl.col("ConfId").fill_null(""),
            pl.col("Mensaje").fill_null(""),
        ]
    )

    # Calcular timestamp UTC
    result = result.with_columns(
        pl.struct(["Fecha", "Hora"])
        .map_elements(
            lambda r: _parse_timestamp_gestor(r["Fecha"], r["Hora"]),
            return_dtype=pl.Float64,
        )
        .alias("tsges")
    )
    # Generar MD5 solo de caracteres ASCII
    result = result.with_columns(
        pl.col("Mensaje").str.replace_all(_ONLY_ASCII, "").alias("Mensaje_trim")
    )

    # Calcular MD5 del mensaje
    result = result.with_columns(
        pl.col("Mensaje_trim")
        .map_elements(_md5, return_dtype=pl.Utf8)
        .alias("MessageMD5")
    )

    log.info("Gestor cargado: %s registros", result.select(pl.len()).collect().item())
    write_parquet(result, base_path, "gestor", date_str, mode="overwrite")
    return result


# ---------------------------------------------------------------------------
# Vendor
# ---------------------------------------------------------------------------


def load_vendor(
    vendor_dir: str | Path,
    base_path: Path,
    date_str: str,
    vendor_columns: list[str] | None = None,
) -> pl.LazyFrame:
    """Lee archivos ZIP CSV del vendor, transforma y almacena.

    Parameters
    ----------
    vendor_dir : str | Path
        Directorio donde se encuentran los ZIPs del vendor.
    base_path : Path
        Directorio raíz de datos Parquet.
    date_str : str
        Fecha en formato ``YYYYMMDD``.
    vendor_columns : list[str] | None
        Nombres de columnas del vendor definidos en el YAML de configuración.

    Returns
    -------
    pl.LazyFrame
        LazyFrame del vendor transformado.
    """
    vdir = Path(vendor_dir)
    csv_files = sorted(vdir.glob(f"*{date_str}*.csv"))

    if not csv_files:
        log.warning(
            "No se encontraron archivos CSV para fecha %s en %s", date_str, vdir
        )
        return pl.LazyFrame()

    frames: list[pl.LazyFrame] = []
    for zf in csv_files:
        log.info("Leyendo vendor: %s", zf.name)
        read_kwargs: dict = {
            "schema_overrides": {"Date": pl.Utf8},
            "null_values": [""],
        }
        if vendor_columns:
            read_kwargs["new_columns"] = vendor_columns
            read_kwargs["has_header"] = False
        else:
            read_kwargs["infer_schema"] = True
        lf = pl.scan_csv(zf, 
                         encoding="utf8-lossy",
                         **read_kwargs
                         )
        frames.append(lf)

    result = pl.concat(frames, how="diagonal_relaxed")

    # Separar registros con fecha válida vs inválida
    result = result.with_columns(
        pl.when(pl.col("Date").is_not_null() & (pl.col("Date") != ""))
        .then(pl.col("Date"))
        .otherwise(None)
        .alias("Date_raw")
    )

    # Parsear fecha
    result = result.with_columns(
        pl.col("Date_raw")
        .str.strptime(pl.Datetime, "%Y-%m-%d %H:%M:%S", strict=False)
        .alias("Date_parsed")
    )

    # Registros válidos (con fecha parseable)
    valid = result.filter(pl.col("Date_parsed").is_not_null())

    if valid.collect().is_empty():
        log.warning("Todos los registros del vendor tienen fecha inválida")
        return pl.LazyFrame()

    # Limpiar mensaje: reemplazar triples comillas
    valid = valid.with_columns(
        pl.col("Message").str.replace_all('"', "").fill_null("nd")
    )

    # Campo texto solo ASCII
    valid = valid.with_columns(
        pl.col("Message").str.replace_all(_ONLY_ASCII, "").alias("Message_trim")
    )

    # Agregar columnas derivadas
    valid = valid.with_columns(
        [
            pl.col("Date_parsed").dt.strftime("%Y-%m-%d").alias("Fecha"),
            pl.col("Date_parsed").dt.strftime("%H.%M.%S").alias("Hora"),
        ]
    )

    valid = valid.with_columns(
        pl.col("Date_parsed")
        .map_elements(
            lambda r: (
                r.replace(tzinfo=timezone.utc).timestamp() if r is not None else 0.0
            ),
            return_dtype=pl.Float64,
        )
        .alias("tsvend")
    )

    valid = valid.with_columns(
        pl.col("Message_trim")
        .map_elements(_md5, return_dtype=pl.Utf8)
        .alias("MessageMD5")
    )

    log.info("Vendor cargado: %s registros válidos", valid.select(pl.len()).collect().item())
    write_parquet(valid, base_path, "vendor", date_str, mode="overwrite")
    return valid


def load_stats(
    base_path: Path,
    date_str: str,
    status_lf: pl.LazyFrame,
) -> pl.LazyFrame:
    """Carga reporte de estadisticas desde Parquet.

    Parameters
    ----------
    base_path : Path
        Directorio raíz de datos Parquet.
    date_str : str
        Fecha en formato ``YYYYMMDD``.
    status_lf : pl.LazyFrame
        LazyFrame de definiciones de estado.

    Returns
    -------
    pl.LazyFrame
        Reporte de estadisticas.
    """

    unique_categories = status_lf.select(
        pl.col("estado_operadora")
    ).collect().to_series().unique().to_list()

    stats_path = Path(base_path) / "stats"
    if not stats_path.exists():
        log.warning("Reporte de estadisticas no encontrado: %s", stats_path)
        return pl.LazyFrame()
    log.info("Cargando reporte de estadisticas: %s", stats_path)
    # obtener fecha 30 dias antes de date_str y filtrar por rango de fechas
    start_date = (datetime.strptime(date_str, "%Y%m%d") - timedelta(days=30)).strftime("%Y%m%d")
    end_date = date_str

    lf = (
        pl.scan_parquet(stats_path)
            .filter((pl.col("Fecha") >= start_date) & (pl.col("Fecha") <= end_date))
            .group_by(["NumCelular"])
            .agg(
                [pl.col("Envios").
                filter(
                    pl.col("Estado_Operadora") == cat
                ).sum().alias(cat) for cat in unique_categories] +
                [pl.col("Envios").sum().alias("Volumen")]
            )
        )

    stats = lf.rename(
        {cat: f"Vol_{cat.title()}" for cat in unique_categories}
    )
    
    return stats