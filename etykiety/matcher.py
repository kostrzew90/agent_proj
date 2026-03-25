"""
Matcher: links DXF cutting lines to CSV part metadata by dimensions.

Strategy:
1. For each DXF part, compute (width, height) from bounding box
2. For each CSV part, expand quantity into individual instances
3. Match DXF parts to CSV instances by closest dimension match
4. Handle rotation: if can_rotate, try both (w,h) and (h,w) orientations
"""
from typing import List, Tuple, Optional
from models import DxfPart, CsvPart, LabelData, EdgeBanding, Sheet, LabelConfig


def _dimensions_match(
    dxf_w: float, dxf_h: float,
    csv_l: float, csv_w: float,
    tolerance: float = 5.0,
    can_rotate: bool = True
) -> bool:
    """Check if DXF part dimensions match CSV part dimensions within tolerance."""
    # Direct match
    if abs(dxf_w - csv_l) <= tolerance and abs(dxf_h - csv_w) <= tolerance:
        return True
    # Rotated match
    if can_rotate:
        if abs(dxf_w - csv_w) <= tolerance and abs(dxf_h - csv_l) <= tolerance:
            return True
    return False


def _is_rotated(
    dxf_w: float, dxf_h: float,
    csv_l: float, csv_w: float,
    tolerance: float = 5.0
) -> bool:
    """Check if the part was placed rotated on the sheet."""
    direct = abs(dxf_w - csv_l) + abs(dxf_h - csv_w)
    rotated = abs(dxf_w - csv_w) + abs(dxf_h - csv_l)
    return rotated < direct and direct > tolerance


def match_parts(
    sheet: Sheet,
    csv_parts: List[CsvPart],
    config: LabelConfig
) -> List[LabelData]:
    """
    Match DXF parts to CSV metadata and generate LabelData list.

    Args:
        sheet: Parsed DXF sheet with parts
        csv_parts: Parsed CSV part definitions
        config: Label configuration

    Returns:
        List of LabelData, one per DXF part on the sheet
    """
    tolerance = config.match_tolerance_mm

    # Expand CSV parts by quantity: each CSV row may represent multiple instances
    # Track how many instances of each CSV part have been matched
    csv_match_counts = {i: 0 for i in range(len(csv_parts))}

    labels = []
    part_number = config.start_part_number

    for dxf_part in sheet.parts:
        dxf_w = dxf_part.width
        dxf_h = dxf_part.height

        # Find best matching CSV part
        best_csv_idx: Optional[int] = None
        best_score = float('inf')

        for csv_idx, csv_part in enumerate(csv_parts):
            # Skip if all instances already matched
            if csv_match_counts[csv_idx] >= csv_part.quantity:
                continue

            can_rotate = csv_part.can_rotate != "DontAllow"

            if _dimensions_match(dxf_w, dxf_h, csv_part.length_mm, csv_part.width_mm,
                                 tolerance, can_rotate):
                # Score: prefer closer dimensional match
                score = min(
                    abs(dxf_w - csv_part.length_mm) + abs(dxf_h - csv_part.width_mm),
                    abs(dxf_w - csv_part.width_mm) + abs(dxf_h - csv_part.length_mm)
                    if can_rotate else float('inf')
                )
                if score < best_score:
                    best_score = score
                    best_csv_idx = csv_idx

        # Build label data
        label = LabelData()
        label.part_number = part_number
        label.dxf_part = dxf_part

        if best_csv_idx is not None:
            csv_part = csv_parts[best_csv_idx]
            csv_match_counts[best_csv_idx] += 1

            label.quantity = 1  # each DXF instance is 1
            label.material_name = csv_part.name
            label.project_name = config.project_name
            label.operation_type = config.operation_type
            label.company_info = config.company_info

            # Determine if part is rotated on sheet
            rotated = _is_rotated(dxf_w, dxf_h,
                                  csv_part.length_mm, csv_part.width_mm, tolerance)

            if rotated:
                label.length_mm = csv_part.width_mm
                label.width_mm = csv_part.length_mm
                # Rotate edge banding accordingly
                eb = csv_part.edge_banding
                label.edge_banding = EdgeBanding(
                    top=eb.left, bottom=eb.right,
                    left=eb.bottom, right=eb.top
                )
            else:
                label.length_mm = csv_part.length_mm
                label.width_mm = csv_part.width_mm
                label.edge_banding = EdgeBanding(
                    top=csv_part.edge_banding.top,
                    bottom=csv_part.edge_banding.bottom,
                    left=csv_part.edge_banding.left,
                    right=csv_part.edge_banding.right
                )
        else:
            # No CSV match - use DXF dimensions directly
            label.length_mm = round(dxf_w, 0)
            label.width_mm = round(dxf_h, 0)
            label.material_name = config.project_name or "Unknown"
            label.operation_type = config.operation_type
            label.company_info = config.company_info
            label.project_name = config.project_name

            # Use edge banding from DXF triangle detection
            eb = EdgeBanding()
            for direction in dxf_part.edge_banding_directions:
                if direction == "top":
                    eb.top = "TAK"
                elif direction == "bottom":
                    eb.bottom = "TAK"
                elif direction == "left":
                    eb.left = "TAK"
                elif direction == "right":
                    eb.right = "TAK"
            label.edge_banding = eb

        labels.append(label)
        part_number += 1

    return labels


if __name__ == "__main__":
    print("Use main.py to run the full pipeline.")
