"""
Smoke test — samples a handful of real BAT files across different flow types.
Runs quickly; validates parser correctness without processing all 20k files.

Run from the project root:
  py test_parser.py
"""

import sys
import zipfile
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))

from backend.ingestion.file_walker import walk_account
from backend.parser.router import route_file

DATA_ROOT = Path(__file__).parent / "data"
ACCOUNT_ROOT = DATA_ROOT / "BAT"

# ── Collect one file per unique CodFlusso (from filename, before parsing) ──
def sniff_cod_flusso(zip_path: Path) -> str:
    """Extract CodFlusso from the filename without parsing XML."""
    parts = zip_path.name.split("_")
    return parts[3] if len(parts) > 3 else "UNKNOWN"

print("Scanning file index (no extraction yet)...")
seen_flusso: dict[str, Path] = {}

for subfolder in sorted(ACCOUNT_ROOT.iterdir()):
    if not subfolder.is_dir() or not subfolder.name.startswith(("2G_", "TME_")):
        continue
    for year_dir in sorted(subfolder.iterdir()):
        if not year_dir.is_dir():
            continue
        for date_dir in sorted(year_dir.iterdir()):
            if not date_dir.is_dir():
                continue
            for f in sorted(date_dir.iterdir()):
                if f.name.lower().endswith(".xml.zip"):
                    cod = sniff_cod_flusso(f)
                    if cod not in seen_flusso:
                        seen_flusso[cod] = f

print(f"Unique CodFlusso types found: {sorted(seen_flusso.keys())}\n")
print(f"Will parse {len(seen_flusso)} sample files (one per flow type)\n")

# ── Parse each sample ──
stats = defaultdict(int)
errors = []

SEP = "-" * 70
print(SEP)
print(f"{'FILE':<52} {'SHAPE':<10} {'CURVES':>7} {'TOTALS':>7}")
print(SEP)

for cod_flusso in sorted(seen_flusso):
    zip_path = seen_flusso[cod_flusso]

    # Extract XML temporarily
    extract_dir = zip_path.parent / "_extracted"
    extract_dir.mkdir(exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        xml_name = [e for e in zf.namelist() if e.lower().endswith(".xml")][0]
        xml_path = extract_dir / Path(xml_name).name
        if not xml_path.exists():
            xml_path.write_bytes(zf.read(xml_name))

    try:
        result = route_file(xml_path)
        shape = result.shape
        n_curve = len(result.curve_records)
        n_total = len(result.totalizer_records)
        n_annul = len(result.annullamento_pods)

        stats["ok"] += 1
        stats[f"shape_{shape}"] += 1

        label = f"{cod_flusso:<8} {xml_path.name[:40]}"
        print(f"{label:<52} {shape:<10} {n_curve:>7} {n_total:>7}")

        # Show first curve record detail
        if result.curve_records:
            r = result.curve_records[0]
            print(f"  ↳ POD={r.pod}  date={r.data_misura}  p1 ea={r.ea_kwh}  er={r.er_kvarh}  tipo={r.tipo_dato}  dst={r.dst}")
        if result.totalizer_records:
            t = result.totalizer_records[0]
            print(f"  ↳ POD={t.pod}  date={t.data_misura}  EaF1={t.ea_f1}  EaF2={t.ea_f2}  tipo={t.tipo_dato}")
        if n_annul:
            print(f"  ↳ ANNULLAMENTO pods: {result.annullamento_pods}")

    except Exception as exc:
        stats["errors"] += 1
        errors.append((xml_path.name, exc))
        print(f"{'ERROR':<52} {'':10} {'':>7} {'':>7}  ← {exc}")

print(SEP)
print(f"\nOK: {stats['ok']}  Errors: {stats['errors']}")
print(f"Shapes → curve:{stats['shape_curve']}  flusso2:{stats['shape_flusso2']}  "
      f"totalizer:{stats['shape_totalizer']}  f2g:{stats['shape_f2g']}")

if errors:
    print("\nERRORS:")
    for name, exc in errors:
        import traceback
        print(f"  {name}: {exc}")
        traceback.print_exc()
