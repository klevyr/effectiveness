"""Capa de almacenamiento Parquet (reemplaza MySQL).

Proporciona funciones de lectura, escritura y gestión de archivos Parquet
organizados por tabla y fecha.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq

from efectividad.logger import setup_logger

log = setup_logger()


def _table_dir(base: Path, table: str) -> Path:
    """Retorna el directorio de una tabla, creándolo si no existe."""
    d = base / table
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_parquet(
    df: pl.DataFrame,
    base_path: Path,
    table: str,
    date_str: str,
    mode: str = "overwrite",
) -> Path:
    """Escribe un DataFrame como Parquet particionado por fecha.

    Parameters
    ----------
    df : pl.DataFrame
        Datos a almacenar.
    base_path : Path
        Directorio raíz de datos.
    table : str
        Nombre de la tabla (subdirectorio).
    date_str : str
        Fecha en formato ``YYYYMMDD``.
    mode : str
        ``"overwrite"`` reemplaza archivos existentes, ``"append"`` concatena.

    Returns
    -------
    Path
        Ruta del archivo Parquet escrito.
    """
    target_dir = _table_dir(base_path, table)
    target_file = target_dir / f"{date_str}.parquet"

    if mode == "append" and target_file.exists():
        existing = read_parquet(base_path, table, date_str)
        df = pl.concat([existing, df])

    df.write_parquet(target_file)
    log.info("Escrito %s registros en %s", df.height, target_file)
    return target_file


def read_parquet(
    base_path: Path,
    table: str,
    date_str: str | None = None,
) -> pl.DataFrame:
    """Lee datos Parquet de una tabla, opcionalmente filtrando por fecha.

    Parameters
    ----------
    base_path : Path
        Directorio raíz de datos.
    table : str
        Nombre de la tabla.
    date_str : str | None
        Si se indica, solo lee esa fecha. Si es ``None``, lee todas las fechas.

    Returns
    -------
    pl.DataFrame
    """
    target_dir = _table_dir(base_path, table)

    if date_str:
        target_file = target_dir / f"{date_str}.parquet"
        if not target_file.exists():
            log.warning("Archivo no encontrado: %s", target_file)
            return pl.DataFrame()
        return pl.read_parquet(target_file)

    files = sorted(target_dir.glob("*.parquet"))
    if not files:
        return pl.DataFrame()
    return pl.read_parquet(files)


def list_dates(base_path: Path, table: str) -> list[str]:
    """Lista las fechas disponibles para una tabla.

    Returns
    -------
    list[str]
        Fechas en formato ``YYYYMMDD`` ordenadas.
    """
    target_dir = _table_dir(base_path, table)
    return sorted(p.stem for p in target_dir.glob("*.parquet"))


def delete_date(base_path: Path, table: str, date_str: str) -> bool:
    """Elimina los datos de una fecha específica.

    Returns
    -------
    bool
        ``True`` si se eliminó algún archivo.
    """
    target_dir = _table_dir(base_path, table)
    target_file = target_dir / f"{date_str}.parquet"
    if target_file.exists():
        target_file.unlink()
        log.info("Eliminado: %s", target_file)
        return True
    log.warning("Archivo no encontrado para eliminar: %s", target_file)
    return False


def table_exists(base_path: Path, table: str, date_str: str) -> bool:
    """Verifica si existen datos para una tabla y fecha."""
    target_dir = base_path / table
    return (target_dir / f"{date_str}.parquet").exists()
