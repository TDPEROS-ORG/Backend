from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional

from src.dominio.entities.telemetry import Telemetry


class TelemetryRepository(ABC):
    @abstractmethod
    def save(self, telemetry: Telemetry) -> Telemetry:
        raise NotImplementedError

    @abstractmethod
    def find_latest(self) -> Optional[Telemetry]:
        raise NotImplementedError

    @abstractmethod
    def find_recent(self, limit: int = 50) -> List[Telemetry]:
        raise NotImplementedError

    @abstractmethod
    def find_since(self, start_date: datetime, limit: int = 500) -> List[Telemetry]:
        raise NotImplementedError
