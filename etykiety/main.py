#!/usr/bin/env python3
"""
CNC Label Generator - Main CLI Entry Point

Generates labels for CNC-cut parts from MaxCut DXF nesting files.
Supports PDF output (for regular printers) and ZPL (for Zebra thermal printers).

Usage:
    python main.py --dxf FILE.dxf [--csv FILE.csv] [--output-dir ./output]
    python main.py --dxf FILE.dxf --csv FILE.csv --project "ARENA" --format both
"""
import argparse
import os
import sys
from pathlib import Path

from models import LabelConfig
from dxf_parser import parse_dxf
from csv_parser import parse_csv
from matcher import match_parts
from nesting_renderer import render_nesting_miniature
from label_pdf import generate_pdf
from label_zpl import generate_zpl_file


def main():
    parser = argparse.ArgumentParser(
        description='CNC Label Generator - etykiety do elementów z nestingu MaxCut',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Przykłady użycia:
  python main.py --dxf nesting.dxf --csv parts.csv --project "ARENA"
  python main.py --dxf nesting.dxf --csv parts.csv --format zpl --start-number 128
  python main.py --dxf nesting.dxf  (bez CSV - wymiary z DXF, brak metadanych)
        """
    )

    # Input files
    parser.add_argument('--dxf', required=True, help='Plik DXF z nestingu MaxCut')
    parser.add_argument('--csv', help='Plik CSV z eksportu MaxCut (opcjonalny)')

    # Output
    parser.add_argument('--output-dir', '-o', default='./output',
                        help='Katalog wyjsciowy (domyślnie: ./output)')
    parser.add_argument('--format', '-f', choices=['pdf', 'zpl', 'both'],
                        default='both', help='Format wyjściowy (domyślnie: both)')

    # Label content
    parser.add_argument('--project', default='',
                        help='Nazwa projektu (np. "ARENA")')
    parser.add_argument('--operation', default='FRONTY-CIECIE-OKLEJANIE',
                        help='Typ operacji')
    parser.add_argument('--company', default='',
                        help='Dane firmy (np. "PROJEKT@CNCMEBLE.PL 502963862")')
    parser.add_argument('--start-number', type=int, default=1,
                        help='Numer startowy części (domyślnie: 1)')

    # Label dimensions
    parser.add_argument('--label-width', type=float, default=150.0,
                        help='Szerokość etykiety PDF w mm (domyślnie: 150)')
    parser.add_argument('--label-height', type=float, default=100.0,
                        help='Wysokość etykiety PDF w mm (domyślnie: 100)')
    parser.add_argument('--tolerance', type=float, default=5.0,
                        help='Tolerancja dopasowania wymiarów CSV↔DXF w mm (domyślnie: 5)')

    args = parser.parse_args()

    # Validate inputs
    dxf_path = Path(args.dxf)
    if not dxf_path.exists():
        print(f"BŁĄD: Plik DXF nie istnieje: {dxf_path}")
        sys.exit(1)

    csv_parts = []
    if args.csv:
        csv_path = Path(args.csv)
        if not csv_path.exists():
            print(f"BŁĄD: Plik CSV nie istnieje: {csv_path}")
            sys.exit(1)

    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build config
    config = LabelConfig(
        label_width_mm=args.label_width,
        label_height_mm=args.label_height,
        start_part_number=args.start_number,
        operation_type=args.operation,
        company_info=args.company,
        project_name=args.project,
        match_tolerance_mm=args.tolerance,
    )

    # ======================================
    # STEP 1: Parse DXF
    # ======================================
    print(f"\n[1/5] Parsing DXF: {dxf_path.name}")
    sheet = parse_dxf(str(dxf_path))
    print(f"      Arkusz: {sheet.width:.0f} x {sheet.height:.0f} mm")
    print(f"      Znaleziono czesci: {len(sheet.parts)}")

    if not sheet.parts:
        print("BŁĄD: Nie znaleziono zadnych czesci w pliku DXF.")
        sys.exit(1)

    for part in sheet.parts:
        eb = ", ".join(part.edge_banding_directions) if part.edge_banding_directions else "-"
        print(f"      #{part.index}: {part.width:.0f} x {part.height:.0f} mm  oklejanie: {eb}")

    # ======================================
    # STEP 2: Parse CSV (optional)
    # ======================================
    if args.csv:
        print(f"\n[2/5] Parsing CSV: {Path(args.csv).name}")
        csv_parts = parse_csv(str(args.csv))
        print(f"      Pozycje w CSV: {len(csv_parts)}")
        total_qty = sum(p.quantity for p in csv_parts)
        print(f"      Laczna ilosc elementow: {total_qty}")
    else:
        print(f"\n[2/5] CSV pominiety - etykiety z samymi wymiarami z DXF")

    # ======================================
    # STEP 3: Match parts
    # ======================================
    print(f"\n[3/5] Dopasowywanie czesci CSV -> DXF...")
    labels = match_parts(sheet, csv_parts, config)
    matched = sum(1 for l in labels if l.material_name and l.material_name != "Unknown")
    print(f"      Dopasowano: {matched}/{len(labels)}")

    # ======================================
    # STEP 4: Render nesting miniatures
    # ======================================
    print(f"\n[4/5] Renderowanie miniaturek nestingu...")
    for label in labels:
        if label.dxf_part:
            label.nesting_image = render_nesting_miniature(
                sheet,
                highlight_part=label.dxf_part,
                image_width_px=300,
                image_height_px=220
            )
    print(f"      Wygenerowano {len(labels)} miniaturek")

    # ======================================
    # STEP 5: Generate output
    # ======================================
    base_name = dxf_path.stem

    if args.format in ('pdf', 'both'):
        pdf_path = output_dir / f"{base_name}_labels.pdf"
        print(f"\n[5/5] Generowanie PDF: {pdf_path}")
        generate_pdf(labels, config, str(pdf_path))

    if args.format in ('zpl', 'both'):
        zpl_path = output_dir / f"{base_name}_labels.zpl"
        print(f"\n[5/5] Generowanie ZPL: {zpl_path}")
        generate_zpl_file(labels, config, str(zpl_path))

    # Summary
    print(f"\n{'='*50}")
    print(f"GOTOWE! Wygenerowano {len(labels)} etykiet")
    print(f"Katalog wyjsciowy: {output_dir.absolute()}")
    print(f"{'='*50}")

    # Print label summary
    print(f"\nPodsumowanie etykiet:")
    for label in labels:
        eb_dirs = []
        if label.edge_banding.top:
            eb_dirs.append("T")
        if label.edge_banding.bottom:
            eb_dirs.append("B")
        if label.edge_banding.left:
            eb_dirs.append("L")
        if label.edge_banding.right:
            eb_dirs.append("R")
        eb_str = "".join(eb_dirs) if eb_dirs else "-"
        print(f"  #{label.part_number:03d}  {label.length_mm:>6.0f} x {label.width_mm:<6.0f}  "
              f"{label.material_name:<30s}  okl: {eb_str}")


if __name__ == "__main__":
    main()
