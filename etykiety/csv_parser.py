"""
CSV Parser for MaxCut export files.

MaxCut exports CSV with separator ';' and fields like:
Typ, Nazwa, Długość, Szerokość, Ilość, Materiał, Okleina edges, etc.
"""
import csv
import re
from pathlib import Path
from typing import List
from models import CsvPart, EdgeBanding


def _parse_dimension(value: str) -> float:
    """Parse dimension string like '1441 mm' to float mm value."""
    if not value:
        return 0.0
    match = re.search(r'([\d.]+)', value.strip())
    if match:
        return float(match.group(1))
    return 0.0


def parse_csv(filepath: str) -> List[CsvPart]:
    """
    Parse MaxCut CSV export file.

    Args:
        filepath: Path to CSV file

    Returns:
        List of CsvPart objects with part metadata
    """
    parts = []
    path = Path(filepath)

    with open(path, 'r', encoding='utf-8-sig') as f:
        # First line might be separator declaration
        first_line = f.readline().strip()
        if first_line.startswith('Sep='):
            separator = first_line.split('=')[1]
        else:
            separator = ';'
            f.seek(0)

        reader = csv.DictReader(f, delimiter=separator)

        for row in reader:
            part = CsvPart()
            part.import_id = row.get('ID importu', '').strip('"')
            part.parent_id = row.get('ID rodzica', '').strip('"')
            part.name = row.get('Nazwa', '').strip('"')
            part.length_mm = _parse_dimension(row.get('Długość', ''))
            part.width_mm = _parse_dimension(row.get('Szerokość', ''))
            part.quantity = int(row.get('Ilość', '1').strip('"') or '1')
            part.material = row.get('Materiał', '').strip('"')
            part.can_rotate = row.get(
                'Można obrócić (https://feature-panel-rotation.maxcutsoftware.com)', ''
            ).strip('"')

            # Edge banding - 4 edges
            eb = EdgeBanding()
            eb.top = row.get('Okleina — krawędź wysokość 1', '').strip('"')
            eb.bottom = row.get('Okleina — krawędź wysokość 2', '').strip('"')
            eb.left = row.get('Okleina — krawędź szerokość 1', '').strip('"')
            eb.right = row.get('Okleina — krawędź szerokość 2', '').strip('"')
            part.edge_banding = eb

            part.include_edge_thickness = (
                row.get('Uwzględnij grubość okleiny', 'False').strip('"').lower() == 'true'
            )

            part.note1 = row.get('Notatka 1', '').strip('"')
            part.note2 = row.get('Notatka 2', '').strip('"')
            part.note3 = row.get('Notatka 3', '').strip('"')
            part.note4 = row.get('Notatka 4', '').strip('"')
            part.notes = row.get('Notatki', '').strip('"')
            part.group = row.get('Grupuj', '').strip('"')

            parts.append(part)

    return parts


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python csv_parser.py <file.csv>")
        sys.exit(1)

    parts = parse_csv(sys.argv[1])
    print(f"Parts found: {len(parts)}")
    for p in parts:
        edges = []
        if p.edge_banding.top:
            edges.append(f"T: {p.edge_banding.top}")
        if p.edge_banding.bottom:
            edges.append(f"B: {p.edge_banding.bottom}")
        if p.edge_banding.left:
            edges.append(f"L: {p.edge_banding.left}")
        if p.edge_banding.right:
            edges.append(f"R: {p.edge_banding.right}")
        eb_str = " | ".join(edges) if edges else "brak"
        print(f"  ID:{p.import_id} '{p.name}' {p.length_mm:.0f}x{p.width_mm:.0f}mm "
              f"qty:{p.quantity} mat:{p.material} edges:[{eb_str}]")
