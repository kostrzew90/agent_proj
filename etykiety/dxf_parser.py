"""
DXF Parser for MaxCut ABF format nesting files.

Extracts:
- Sheet border (_ABF_SHEET_BORDER)
- Cutting lines (_ABF_CUTTING_LINES) - individual parts
- Edge banding markers (_ABF_EDGE_BANDING) - triangles indicating banded edges
- Label markers (_ABF_LABEL) - position markers
"""
import ezdxf
from typing import List, Tuple
from models import DxfPart, Sheet


# ABF layer names used by MaxCut
LAYER_SHEET_BORDER = "_ABF_SHEET_BORDER"
LAYER_CUTTING_LINES = "_ABF_CUTTING_LINES"
LAYER_EDGE_BANDING = "_ABF_EDGE_BANDING"
LAYER_LABEL = "_ABF_LABEL"
LAYER_SHEET_ID = "_ABF_SHEET_ID"
LAYER_SHEET_MATERIAL = "_ABF_SHEET_MATERIAL"


def _get_polyline_vertices(entity) -> List[Tuple[float, float]]:
    """Extract 2D vertices from LWPOLYLINE entity."""
    if entity.dxftype() == "LWPOLYLINE":
        return [(p[0], p[1]) for p in entity.get_points(format="xy")]
    return []


def _is_closed_polyline(entity) -> bool:
    """Check if polyline is closed."""
    if entity.dxftype() == "LWPOLYLINE":
        return entity.closed
    return False


def _classify_triangle_direction(vertices: List[Tuple[float, float]]) -> str:
    """
    Determine which direction a small triangle (edge banding marker) points.
    The triangle has 3 unique vertices (4th closes the shape).
    The 'peak' vertex (furthest from centroid) indicates direction.

    Returns: 'top', 'bottom', 'left', 'right'
    """
    if len(vertices) < 3:
        return ""

    # Use first 3 unique vertices
    unique = []
    for v in vertices:
        is_dup = False
        for u in unique:
            if abs(v[0] - u[0]) < 0.01 and abs(v[1] - u[1]) < 0.01:
                is_dup = True
                break
        if not is_dup:
            unique.append(v)
        if len(unique) == 3:
            break

    if len(unique) < 3:
        return ""

    # Find the peak: the vertex that is alone on one axis
    # For a triangle pointing LEFT: peak has smallest X, other two share similar X
    # For a triangle pointing RIGHT: peak has largest X
    # For a triangle pointing UP: peak has largest Y
    # For a triangle pointing DOWN: peak has smallest Y
    xs = [v[0] for v in unique]
    ys = [v[1] for v in unique]

    x_range = max(xs) - min(xs)
    y_range = max(ys) - min(ys)

    if x_range > y_range:
        # Triangle is wider than tall → points left or right
        # Find which vertex is alone (the peak)
        # Sort by X
        sorted_by_x = sorted(unique, key=lambda v: v[0])
        # Check if peak is on left (min X) or right (max X)
        # The two base vertices should have similar X values
        dist_left = abs(sorted_by_x[1][0] - sorted_by_x[2][0])
        dist_right = abs(sorted_by_x[0][0] - sorted_by_x[1][0])
        if dist_left < dist_right:
            # vertices[1] and [2] are close → peak is vertices[0] (leftmost)
            return "left"
        else:
            return "right"
    else:
        # Triangle is taller than wide → points up or down
        sorted_by_y = sorted(unique, key=lambda v: v[1])
        dist_bottom = abs(sorted_by_y[1][1] - sorted_by_y[2][1])
        dist_top = abs(sorted_by_y[0][1] - sorted_by_y[1][1])
        if dist_bottom < dist_top:
            # vertices[1] and [2] are close → peak is vertices[0] (bottom)
            return "bottom"
        else:
            return "top"


def _assign_edge_banding_to_parts(
    parts: List[DxfPart],
    triangles: List[Tuple[List[Tuple[float, float]], str]],
    tolerance: float = 50.0
):
    """
    Assign edge banding triangles to the nearest part.
    Each triangle is a (vertices, direction) tuple.
    """
    for tri_verts, direction in triangles:
        # Find triangle centroid
        cx = sum(v[0] for v in tri_verts) / len(tri_verts)
        cy = sum(v[1] for v in tri_verts) / len(tri_verts)

        # Find which part this triangle belongs to
        best_part = None
        best_dist = float('inf')

        for part in parts:
            # Check if triangle centroid is near the part's edges
            # A triangle should be just outside or on the edge of a part
            dx = max(part.min_x - cx, 0, cx - part.max_x)
            dy = max(part.min_y - cy, 0, cy - part.max_y)
            dist = (dx * dx + dy * dy) ** 0.5

            if dist < best_dist:
                best_dist = dist
                best_part = part

        if best_part is not None and best_dist < tolerance:
            if direction and direction not in best_part.edge_banding_directions:
                best_part.edge_banding_directions.append(direction)


def parse_dxf(filepath: str) -> Sheet:
    """
    Parse a MaxCut ABF-format DXF file.

    Args:
        filepath: Path to the DXF file

    Returns:
        Sheet object with border, parts, and edge banding info
    """
    doc = ezdxf.readfile(filepath)
    msp = doc.modelspace()

    sheet = Sheet()
    cutting_parts = []
    edge_banding_triangles = []
    part_index = 0

    for entity in msp:
        layer = entity.dxf.layer
        vertices = _get_polyline_vertices(entity)

        if not vertices:
            continue

        if layer == LAYER_SHEET_BORDER:
            sheet.border_vertices = vertices
            xs = [v[0] for v in vertices]
            ys = [v[1] for v in vertices]
            sheet.width = max(xs) - min(xs)
            sheet.height = max(ys) - min(ys)

        elif layer == LAYER_CUTTING_LINES:
            if _is_closed_polyline(entity) and len(vertices) >= 4:
                part_index += 1
                part = DxfPart(index=part_index, vertices=vertices)
                cutting_parts.append(part)

        elif layer == LAYER_EDGE_BANDING:
            if len(vertices) >= 3:
                direction = _classify_triangle_direction(vertices)
                if direction:
                    edge_banding_triangles.append((vertices, direction))

    # Assign edge banding markers to nearest parts
    _assign_edge_banding_to_parts(cutting_parts, edge_banding_triangles)

    # Sort parts by position: top-to-bottom, then left-to-right
    cutting_parts.sort(key=lambda p: (round(p.min_y / 50) * 50, p.min_x))

    # Re-index after sorting
    for i, part in enumerate(cutting_parts, 1):
        part.index = i

    sheet.parts = cutting_parts
    return sheet


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python dxf_parser.py <file.dxf>")
        sys.exit(1)

    sheet = parse_dxf(sys.argv[1])
    print(f"Sheet: {sheet.width:.0f} x {sheet.height:.0f} mm")
    print(f"Parts found: {len(sheet.parts)}")
    for part in sheet.parts:
        eb = ", ".join(part.edge_banding_directions) if part.edge_banding_directions else "none"
        print(f"  #{part.index}: {part.width:.0f} x {part.height:.0f} mm "
              f"at ({part.min_x:.0f}, {part.min_y:.0f}) edges: {eb}")
