from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SourceCategory(Enum):
    VIN_DECODE = "vin_decode"
    REGISTRY = "registry"
    DAMAGE = "damage"
    PHOTO_OSINT = "photo_osint"
    ADS_ARCHIVE = "ads_archive"
    LOCAL_KNOWLEDGE = "local_knowledge"


class SourceStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    CAPTCHA_REQUIRED = "captcha_required"
    DONE = "done"
    ERROR = "error"
    NO_DATA = "no_data"
    CAPTCHA_TIMEOUT = "captcha_timeout"


@dataclass
class PluginResult:
    source_name: str
    category: SourceCategory
    status: SourceStatus
    data: dict = field(default_factory=dict)
    raw_html: Optional[str] = None
    screenshots: list[str] = field(default_factory=list)
    error_message: Optional[str] = None
    execution_time_ms: int = 0


class SourcePlugin(ABC):
    """Bazowa klasa dla każdego źródła danych."""

    name: str
    display_name: str
    category: SourceCategory
    country: str                   # ISO kod kraju, np. "GB", "PL", "DE"
    requires_captcha: bool = False
    requires_login: bool = False   # Jeśli True — plugin jest pomijany
    enabled: bool = True

    @abstractmethod
    async def search_by_vin(self, vin: str, **kwargs) -> PluginResult:
        """Szukaj danych po numerze VIN.

        kwargs may include:
            context (dict): decoded VIN data from phase 1 (make, model, year, etc.)
        """
        ...

    async def search_by_plate(self, plate: str, country: str) -> PluginResult:
        """Opcjonalnie: szukaj po tablicy rejestracyjnej."""
        raise NotImplementedError(f"{self.name} nie obsługuje wyszukiwania po tablicy")

    async def submit_captcha(self, vin: str, captcha_answer: str) -> PluginResult:
        """Wywoływane po rozwiązaniu CAPTCHA przez użytkownika."""
        raise NotImplementedError(f"{self.name} nie obsługuje submit_captcha")

    def _make_error(self, message: str, execution_time_ms: int = 0) -> PluginResult:
        return PluginResult(
            source_name=self.name,
            category=self.category,
            status=SourceStatus.ERROR,
            error_message=message,
            execution_time_ms=execution_time_ms,
        )

    def _make_no_data(self, execution_time_ms: int = 0) -> PluginResult:
        return PluginResult(
            source_name=self.name,
            category=self.category,
            status=SourceStatus.NO_DATA,
            execution_time_ms=execution_time_ms,
        )
