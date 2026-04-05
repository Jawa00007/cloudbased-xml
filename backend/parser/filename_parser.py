"""
SII filename parser.

Filename format:
  <PIVAdist>_<PIVAutente>_<AAAAMM>_<CodFlusso>_<Timestamp>_<Progressivo><CodiceDP>__<SM>.xml

Example:
  01234567890_12345678901_201301_PDO2G_20130218060523_1DP0001_R.xml
  05779711000_04393470879_202501_PDO2G_20250127060012_1DP0042__R.xml

Note the double underscore before SM in many real filenames.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime


# Matches both single and double underscore before SM suffix
_FILENAME_RE = re.compile(
    r"""
    ^
    (?P<piva_distributore>\d{11})
    _
    (?P<piva_utente>\d{11})
    _
    (?P<aaaamm>\d{6})
    _
    (?P<cod_flusso>[A-Z0-9]+)
    _
    (?P<timestamp>\d{14})
    _
    (?P<progressivo_raw>[^_.]+)
    (?:__?(?P<sm_status>NR|R))?   # SM status is absent in older files
    \.xml$
    """,
    re.VERBOSE | re.IGNORECASE,
)

_TIMESTAMP_FMT = "%Y%m%d%H%M%S"


@dataclass
class FilenameMetadata:
    piva_distributore: str
    piva_utente: str
    mese_anno: str          # MM/YYYY  e.g. "01/2013"
    cod_flusso: str         # e.g. "PDO2G", "RFO", "F2G"
    file_timestamp: datetime
    progressivo: int
    sm_status: str | None   # "R", "NR", or None for older files
    raw_filename: str


def parse_filename(filename: str) -> FilenameMetadata:
    """
    Parse an SII XML filename into its metadata components.

    Raises ValueError if the filename does not match the expected pattern.
    """
    # Strip directory component if a full path was passed
    bare = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]

    m = _FILENAME_RE.match(bare)
    if m is None:
        raise ValueError(
            f"Filename does not match SII naming convention: {bare!r}"
        )

    aaaamm = m.group("aaaamm")          # e.g. "201301"
    mese_anno = f"{aaaamm[4:6]}/{aaaamm[:4]}"  # "01/2013"

    try:
        file_timestamp = datetime.strptime(m.group("timestamp"), _TIMESTAMP_FMT)
    except ValueError as exc:
        raise ValueError(
            f"Invalid timestamp in filename {bare!r}: {m.group('timestamp')!r}"
        ) from exc

    # progressivo_raw looks like "1DP0001" or "2" — extract leading digits
    progressivo_raw = m.group("progressivo_raw")
    digits = re.match(r"(\d+)", progressivo_raw)
    if digits is None:
        raise ValueError(
            f"Cannot extract progressivo from {progressivo_raw!r} in {bare!r}"
        )
    progressivo = int(digits.group(1))

    return FilenameMetadata(
        piva_distributore=m.group("piva_distributore"),
        piva_utente=m.group("piva_utente"),
        mese_anno=mese_anno,
        cod_flusso=m.group("cod_flusso").upper(),
        file_timestamp=file_timestamp,
        progressivo=progressivo,
        sm_status=(m.group("sm_status") or "").upper() or None,
        raw_filename=bare,
    )
