"""Carga de datos desde archivos gestor (CSV) y vendor (ZIP CSV).

Transforma y almacena los datos en Parquet vía la capa de storage.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from efectividad.logger import setup_logger
from efectividad.models import GESTOR_SCHEMA
from efectividad.storage import read_parquet, write_parquet

log = setup_logger()

_GESTOR_COLS: list[str] = list(GESTOR_SCHEMA.keys())


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
    skip_transfers: bool = False,
) -> pl.DataFrame:
    """Lee archivos broadcast.csv y megareport.csv, transforma y almacena.

    Parameters
    ----------
    transfer_dir : str | Path
        Directorio donde se encuentran los CSVs del gestor.
    base_path : Path
        Directorio raíz de datos Parquet.
    date_str : str
        Fecha en formato ``YYYYMMDD``.
    skip_transfers : bool
        Si ``True``, omite la descarga de transferencias AS400.

    Returns
    -------
    pl.DataFrame
        DataFrame del gestor transformado.
    """
    tdir = Path(transfer_dir)
    frames: list[pl.DataFrame] = []

    for csv_name, tipo in [("broadcast.csv", "B"), ("megareport.csv", "M")]:
        csv_path = tdir / csv_name
        if not csv_path.exists():
            log.warning("Archivo gestor no encontrado, omitiendo: %s", csv_path)
            continue
        log.info("Leyendo gestor: %s", csv_path)
        df = pl.read_csv(
            csv_path,
            has_header=False,
            new_columns=_GESTOR_COLS,
            schema_overrides=GESTOR_SCHEMA,
            encoding="iso-8859-1",
            null_values=[""],
        )
        df = df.with_columns(pl.lit(tipo).alias("TipoCola"))
        frames.append(df)

    if not frames:
        log.error("No se encontraron archivos de gestor en %s", tdir)
        return pl.DataFrame()

    result = pl.concat(frames, how="diagonal_relaxed")

    # Limpiar nulos en columnas de texto
    result = result.with_columns([
        pl.col("Cedula").fill_null(""),
        pl.col("ConfId").fill_null(""),
        pl.col("Mensaje").fill_null(""),
    ])

    # Calcular timestamp UTC
    result = result.with_columns(
        pl.struct(["Fecha", "Hora"])
        .map_elements(
            lambda r: _parse_timestamp_gestor(r["Fecha"], r["Hora"]),
            return_dtype=pl.Float64,
        )
        .alias("tsges")
    )

    # Calcular MD5 del mensaje
    result = result.with_columns(
        pl.col("Mensaje").map_elements(_md5, return_dtype=pl.Utf8).alias("MensajeMD5")
    )

    log.info("Gestor cargado: %s registros", result.height)
    write_parquet(result, base_path, "gestor", date_str, mode="overwrite")
    return result


# ---------------------------------------------------------------------------
# Vendor
# ---------------------------------------------------------------------------

def load_vendor(
    vendor_dir: str | Path,
    base_path: Path,
    date_str: str,
) -> pl.DataFrame:
    """Lee archivos ZIP CSV del vendor, transforma y almacena.

    Parameters
    ----------
    vendor_dir : str | Path
        Directorio donde se encuentran los ZIPs del vendor.
    base_path : Path
        Directorio raíz de datos Parquet.
    date_str : str
        Fecha en formato ``YYYYMMDD``.

    Returns
    -------
    pl.DataFrame
        DataFrame del vendor transformado.
    """
    vdir = Path(vendor_dir)
    zip_files = sorted(vdir.glob(f"*{date_str}*.zip"))

    if not zip_files:
        log.warning("No se encontraron archivos ZIP para fecha %s en %s", date_str, vdir)
        return pl.DataFrame()

    frames: list[pl.DataFrame] = []
    for zf in zip_files:
        log.info("Leyendo vendor: %s", zf.name)
        df = pl.read_csv(zf, schema_overrides={"Date": pl.Utf8}, encoding="iso-8859-1")
        frames.append(df)

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
    valid = result.filter(pl.col("Date_parsed").is_not_null()).copy()

    if valid.is_empty():
        log.warning("Todos los registros del vendor tienen fecha inválida")
        return pl.DataFrame()

    # Limpiar mensaje: reemplazar triples comillas
    valid = valid.with_columns(
        pl.col("Message")
        .str.replace_all('"', "")
        .fill_null("nd")
    )

    # Agregar columnas derivadas
    valid = valid.with_columns([
        pl.col("Date_parsed").dt.strftime("%Y-%m-%d").alias("Fecha"),
        pl.col("Date_parsed").dt.strftime("%H.%M.%S").alias("Hora"),
    ])

    valid = valid.with_columns(
        pl.col("Date_parsed")
        .map_elements(
            lambda r: r.replace(tzinfo=timezone.utc).timestamp() if r is not None else 0.0,
            return_dtype=pl.Float64,
        )
        .alias("tsvend")
    )

    valid = valid.with_columns(
        pl.col("Message")
        .map_elements(_md5, return_dtype=pl.Utf8)
        .alias("MessageMD5")
    )

    log.info("Vendor cargado: %s registros válidos", valid.height)
    write_parquet(valid, base_path, "vendor", date_str, mode="overwrite")
    return valid
