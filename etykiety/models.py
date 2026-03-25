"""
Data models for CNC Label Generator
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from PIL import Image


@dataclass
class EdgeBanding:
    """Edge banding info for a single part"""
    top: str = ""       # ˄ - krawędź wysokość 1
    bottom: str = ""    # ˅ - krawędź wysokość 2
    left: str = ""      # ˂ - krawędź szerokość 1
    right: str = ""     # ˃ - krawędź szerokość 2

    def has_any(self) -> bool:
        return any([self.top, self.bottom, self.left, self.right])

    def active_edges(self) -> List[str]:
        """Return list of edge directions that have banding"""
        edges = []
        if self.top:
            edges.append("top")
        if self.bottom:
            edges.append("bottom")
        if self.left:
            edges.append("left")
        if self.right:
            edges.append("right")
        return edges


@dataclass
class DxfPart:
    """A single part extracted from DXF cutting lines"""
    index: int                          # sequential index in DXF
    vertices: List[Tuple[float, float]] # polyline vertices
    min_x: float = 0.0
    min_y: float = 0.0
    max_x: float = 0.0
    max_y: float = 0.0
    width: float = 0.0                  # max_x - min_x (długość)
    height: float = 0.0                 # max_y - min_y (szerokość)
    edge_banding_directions: List[str] = field(default_factory=list)  # detected from DXF triangles

    def __post_init__(self):
        if self.vertices:
            xs = [v[0] for v in self.vertices]
            ys = [v[1] for v in self.vertices]
            self.min_x = min(xs)
            self.min_y = min(ys)
            self.max_x = max(xs)
            self.max_y = max(ys)
            self.width = self.max_x - self.min_x
            self.height = self.max_y - self.min_y


@dataclass
class CsvPart:
    """A part definition from MaxCut CSV export"""
    import_id: str = ""
    parent_id: str = ""
    name: str = ""
    length_mm: float = 0.0       # Długość
    width_mm: float = 0.0        # Szerokość
    quantity: int = 1
    material: str = ""
    can_rotate: str = ""
    edge_banding: EdgeBanding = field(default_factory=EdgeBanding)
    note1: str = ""
    note2: str = ""
    note3: str = ""
    note4: str = ""
    notes: str = ""
    group: str = ""
    include_edge_thickness: bool = False


@dataclass
class Sheet:
    """Represents a full nesting sheet from DXF"""
    width: float = 0.0       # sheet border width (mm)
    height: float = 0.0      # sheet border height (mm)
    parts: List[DxfPart] = field(default_factory=list)
    border_vertices: List[Tuple[float, float]] = field(default_factory=list)


@dataclass
class LabelData:
    """All data needed to generate one label"""
    part_number: int = 0            # numer części (128, 129...)
    quantity: int = 1               # ilość
    length_mm: float = 0.0          # długość (mm)
    width_mm: float = 0.0           # szerokość (mm)
    material_name: str = ""         # nazwa materiału (np. "ADAM - U963 SZARY DIAMENTOWY")
    project_name: str = ""          # nazwa projektu (np. "ARENA")
    operation_type: str = ""        # typ operacji (np. "FRONTY-CIECIE-OKLEJANIE")
    company_info: str = ""          # dane firmy (np. "PROJEKT@CNCMEBLE.PL 502963862")
    edge_banding: EdgeBanding = field(default_factory=EdgeBanding)
    nesting_image: Optional[Image.Image] = None  # miniaturka nestingu z podświetloną częścią
    dxf_part: Optional[DxfPart] = None           # reference to DXF geometry


@dataclass
class LabelConfig:
    """Configuration for label generation"""
    # Label dimensions (mm)
    label_width_mm: float = 150.0
    label_height_mm: float = 100.0

    # Starting part number
    start_part_number: int = 1

    # Default text fields
    operation_type: str = "FRONTY-CIECIE-OKLEJANIE"
    company_info: str = ""
    project_name: str = ""

    # Nesting miniature size (mm) on label
    miniature_width_mm: float = 45.0
    miniature_height_mm: float = 32.0

    # Dimension matching tolerance (mm)
    match_tolerance_mm: float = 5.0

    # ZPL settings
    zpl_dpi: int = 203
    zpl_label_width_mm: float = 100.0
    zpl_label_height_mm: float = 70.0

    # PDF settings
    pdf_font: str = "Helvetica"
