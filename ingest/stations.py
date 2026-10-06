"""Station registry (ingest/stations.json)."""

import json
import math
from dataclasses import dataclass
from pathlib import Path

REGISTRY = Path(__file__).with_name("stations.json")
VENUE_LAT_LON = (28.7499, 77.1183)  # Delhi Technological University, Bawana Road


@dataclass(frozen=True)
class StationConfig:
    station_id: str
    name: str
    lat: float
    lon: float
    cpcb_name: str | None
    openaq_location_id: int | None
    is_venue_default: bool

    def distance_to(self, lat: float, lon: float) -> float:
        """Great-circle distance in km."""
        p1, p2 = math.radians(self.lat), math.radians(lat)
        dp, dl = p2 - p1, math.radians(lon - self.lon)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * 6371.0 * math.asin(math.sqrt(a))


def load_stations(path: Path = REGISTRY) -> list[StationConfig]:
    return [StationConfig(**entry) for entry in json.loads(path.read_text(encoding="utf-8"))]
