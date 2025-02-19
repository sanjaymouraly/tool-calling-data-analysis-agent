"""Safe readers for the supported input formats.

Every reader is defensive: the file extension is validated, the size is
capped, archives are checked for zip-bomb behaviour and the number of rows
that is materialised is bounded.  Data is never executed - workbooks are
parsed with ``openpyxl`` in read-only mode and never with macros enabled.
"""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from ..core.errors import ResourceLimitError, ValidationError
from ..core.security import sanitize_filename

ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xlsm", ".parquet"}
#: Legacy ``.xls`` is accepted but only when xlrd is available.
LEGACY_EXTENSIONS = {".xls"}

#: A workbook is rejected when its uncompressed content is more than this
#: many times larger than the file on disk.
MAX_COMPRESSION_RATIO = 120
#: Hard ceiling for the total uncompressed size of a workbook.
MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024


@dataclass
class ReadResult:
    """Outcome of reading a source file."""

    frame: pd.DataFrame
    sheet_name: str | None = None
    available_sheets: list[str] = field(default_factory=list)
    encoding: str | None = None
    truncated: bool = False
    source_row_count: int | None = None


def validate_extension(filename: str) -> str:
    ext = Path(sanitize_filename(filename)).suffix.lower()
    if ext in LEGACY_EXTENSIONS:
        return ".xls"
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(
            f"unsupported file type '{ext or '(none)'}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )
    return ext


def _check_zip_bomb(path: Path) -> None:
    """Reject workbooks whose expanded size is absurd relative to the file."""
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            total = sum(entry.file_size for entry in entries)
            if total > MAX_UNCOMPRESSED_BYTES:
                raise ResourceLimitError(
                    f"workbook expands to {total / 1e6:.0f}MB which exceeds the safety limit"
                )
            if path.stat().st_size > 0 and total / path.stat().st_size > MAX_COMPRESSION_RATIO:
                raise ResourceLimitError("workbook compression ratio is abnormally high (possible zip bomb)")
            if len(entries) > 20_000:
                raise ResourceLimitError("workbook contains too many internal entries")
    except zipfile.BadZipFile as exc:
        raise ValidationError("file is not a valid workbook (corrupt zip container)") from exc


def detect_encoding(path: Path) -> str:
    """Detect the text encoding of a CSV file."""
    sample = path.open("rb").read(64 * 1024)
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            sample.decode(encoding)
        except UnicodeDecodeError:
            continue
        return encoding
    return "latin-1"


def sniff_dialect(path: Path, encoding: str) -> str:
    """Guess the CSV delimiter."""
    with path.open("r", encoding=encoding, errors="replace", newline="") as handle:
        sample = handle.read(8192)
    if not sample.strip():
        return ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        return dialect.delimiter
    except csv.Error:
        counts = {d: sample.count(d) for d in ",;\t|"}
        best = max(counts, key=lambda k: counts[k])
        return best if counts[best] > 0 else ","


def list_sheets(path: Path) -> list[str]:
    """Enumerate the sheets of a workbook."""
    _check_zip_bomb(path)
    try:
        from openpyxl import load_workbook

        workbook = load_workbook(path, read_only=True, data_only=True, keep_links=False)
        try:
            return list(workbook.sheetnames)
        finally:
            workbook.close()
    except ValidationError:
        raise
    except Exception as exc:  # pragma: no cover - malformed workbook
        raise ValidationError(f"could not read workbook: {str(exc)[:200]}") from exc


def read_source(
    path: Path,
    *,
    max_rows: int,
    sheet_name: str | None = None,
) -> ReadResult:
    """Read a source file into a DataFrame, bounded by ``max_rows``."""
    if not path.exists():
        raise ValidationError("file disappeared from the upload directory")
    ext = path.suffix.lower()
    if ext == ".csv":
        return _read_csv(path, max_rows)
    if ext in {".xlsx", ".xlsm"}:
        return _read_excel(path, max_rows, sheet_name)
    if ext == ".xls":
        return _read_legacy_excel(path, max_rows)
    if ext == ".parquet":
        return _read_parquet(path, max_rows)
    raise ValidationError(f"unsupported file type '{ext}'")


def _read_csv(path: Path, max_rows: int) -> ReadResult:
    encoding = detect_encoding(path)
    delimiter = sniff_dialect(path, encoding)
    try:
        frame = pd.read_csv(
            path,
            encoding=encoding,
            sep=delimiter,
            nrows=max_rows + 1,
            low_memory=False,
            skip_blank_lines=True,
            on_bad_lines="skip",
        )
    except pd.errors.EmptyDataError as exc:
        raise ValidationError("the CSV file is empty") from exc
    except UnicodeDecodeError as exc:
        raise ValidationError("the CSV file could not be decoded as text") from exc
    except Exception as exc:
        raise ValidationError(f"could not parse CSV: {str(exc)[:200]}") from exc

    truncated = len(frame) > max_rows
    if truncated:
        frame = frame.head(max_rows)
    frame = _normalise_frame(frame)
    return ReadResult(frame=frame, encoding=encoding, truncated=truncated)


def _read_excel(path: Path, max_rows: int, sheet_name: str | None) -> ReadResult:
    sheets = list_sheets(path)
    if not sheets:
        raise ValidationError("the workbook does not contain any sheets")
    target = sheet_name or sheets[0]
    if target not in sheets:
        raise ValidationError(
            f"sheet '{target}' not found in workbook",
            details={"available_sheets": sheets[:50]},
        )
    try:
        frame = pd.read_excel(path, sheet_name=target, nrows=max_rows + 1, engine="openpyxl")
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError(f"could not parse worksheet '{target}': {str(exc)[:200]}") from exc
    truncated = len(frame) > max_rows
    if truncated:
        frame = frame.head(max_rows)
    frame = _normalise_frame(frame)
    return ReadResult(frame=frame, sheet_name=target, available_sheets=sheets, truncated=truncated)


def _read_legacy_excel(path: Path, max_rows: int) -> ReadResult:
    try:
        frame = pd.read_excel(path, nrows=max_rows + 1, engine="xlrd")
    except Exception as exc:
        raise ValidationError(f"could not parse legacy workbook: {str(exc)[:200]}") from exc
    truncated = len(frame) > max_rows
    if truncated:
        frame = frame.head(max_rows)
    frame = _normalise_frame(frame)
    return ReadResult(frame=frame, sheet_name="Sheet1", truncated=truncated)


def _read_parquet(path: Path, max_rows: int) -> ReadResult:
    try:
        import pyarrow.parquet as pq

        parquet_file = pq.ParquetFile(path)
        total = parquet_file.metadata.num_rows
        table = parquet_file.read_row_groups(0) if parquet_file.num_row_groups else None
        if table is None:
            frame = pd.DataFrame()
        else:
            frame = table.to_pandas()
        if len(frame) > max_rows:
            frame = frame.head(max_rows)
        return ReadResult(
            frame=_normalise_frame(frame),
            truncated=total > max_rows,
            source_row_count=total,
        )
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError(f"could not parse Parquet file: {str(exc)[:200]}") from exc


def _normalise_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Make column names unique strings and drop fully empty columns."""
    if frame is None or (frame.empty and not len(frame.columns)):
        return frame
    seen: dict[str, int] = {}
    columns: list[str] = []
    for raw in frame.columns:
        name = str(raw).strip()
        if not name:
            name = "unnamed_column"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        columns.append(name)
    frame = frame.copy()
    frame.columns = columns
    # Drop columns that are entirely empty (e.g. trailing Excel formatting).
    keep = [c for c in frame.columns if not frame[c].isna().all()]
    if keep:
        frame = frame[keep]
    return frame


def write_parquet_artifact(frame: pd.DataFrame, destination: Path) -> str:
    """Write the normalised frame as a Parquet artifact and return its hash."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    destination.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(frame, preserve_index=False)
    pq.write_table(table, destination, compression="zstd")
    return _hash_file(destination)


def _hash_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dataframe_to_csv_bytes(frame: pd.DataFrame) -> bytes:
    buffer = io.StringIO()
    frame.to_csv(buffer, index=False)
    return buffer.getvalue().encode("utf-8")
