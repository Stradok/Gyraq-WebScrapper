from dataclasses import dataclass, field, asdict


@dataclass
class Review:
    author: str | None = None
    rating: float | None = None
    relative_time: str | None = None
    text: str | None = None


@dataclass
class Business:
    name: str | None = None
    category: str | None = None
    rating: float | None = None
    review_count: int | None = None
    price_level: str | None = None
    address: str | None = None
    phone: str | None = None
    website: str | None = None
    hours: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    google_maps_url: str | None = None
    reviews: list[Review] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d
