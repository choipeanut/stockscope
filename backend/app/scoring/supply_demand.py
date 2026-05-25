"""Supply/Demand sub-score (weight 0.15) per ANALYSIS_SPEC §Supply-Demand."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# KR weights / US proxy weights
_KR_WEIGHTS = {
    "foreign": 0.30,
    "institution": 0.20,
    "individual_contra": 0.10,
    "volume": 0.20,
    "short_contra": 0.20,
}


def _nav(val) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None


def _net_buy_score(net: float | None) -> float | None:
    if net is None:
        return None
    if net > 0:
        return min(100.0, 50.0 + abs(net) / 1e9 * 30)
    else:
        return max(0.0, 50.0 - abs(net) / 1e9 * 30)


def _volume_score(ratio: float | None) -> float | None:
    if ratio is None:
        return None
    if ratio >= 1.5:
        return 100.0
    elif ratio >= 1.2:
        return 75.0
    elif ratio >= 0.8:
        return 50.0
    else:
        return 20.0


def _short_contra_score(short_pct: float | None) -> float | None:
    """High short ratio = bearish signal → inverted."""
    if short_pct is None:
        return None
    if short_pct < 2:
        return 90.0
    elif short_pct < 5:
        return 70.0
    elif short_pct < 10:
        return 40.0
    else:
        return 10.0


@dataclass
class SupplyDemandResult:
    score: float
    components: dict[str, float]
    unavailable: list[str] = field(default_factory=list)
    proxy: bool = False


def compute_supply_demand(data: dict) -> SupplyDemandResult:
    if not data.get("available", False):
        return SupplyDemandResult(
            score=float("nan"), components={}, unavailable=list(_KR_WEIGHTS)
        )

    proxy = data.get("proxy", False)

    # Foreign net (use 5d; 20d as fallback)
    foreign = _net_buy_score(_nav(data.get("foreign_net_5d"))
                              or _nav(data.get("foreign_net_20d")))
    institution = _net_buy_score(_nav(data.get("institution_net_5d"))
                                  or _nav(data.get("institution_net_20d")))
    # Individual net as contra signal (heavy retail buying = bearish)
    indiv_raw = _nav(data.get("individual_net_5d"))
    individual_contra = (100.0 - _net_buy_score(indiv_raw)) \
        if indiv_raw is not None else None

    volume = _volume_score(_nav(data.get("volume_ratio")))
    short_contra = _short_contra_score(_nav(data.get("short_ratio")))

    # For US proxy, foreign/individual are unavailable
    if proxy:
        foreign = None
        individual_contra = None

    raw = {
        "foreign": foreign,
        "institution": institution,
        "individual_contra": individual_contra,
        "volume": volume,
        "short_contra": short_contra,
    }

    unavailable = [k for k, v in raw.items() if v is None]
    available = {k: v for k, v in raw.items() if v is not None}

    if not available:
        return SupplyDemandResult(
            score=float("nan"), components={}, unavailable=list(_KR_WEIGHTS), proxy=proxy
        )

    total_w = sum(_KR_WEIGHTS[k] for k in available)
    score = sum(_KR_WEIGHTS[k] / total_w * v for k, v in available.items())

    return SupplyDemandResult(
        score=round(score, 2),
        components={k: round(v, 2) for k, v in available.items()},
        unavailable=unavailable,
        proxy=proxy,
    )
