"""Macro sub-score (weight 0.10) per ANALYSIS_SPEC §Macro."""
from __future__ import annotations

import math
from dataclasses import dataclass, field


def _nav(val) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None


def _regime_base_score(regime: str) -> float:
    return {"확장": 80.0, "회복": 65.0, "둔화": 35.0, "침체": 20.0}.get(regime, 50.0)


def _modulate(base: float, macro: dict, sector: str = "", beta: float = 1.0) -> float:
    """Adjust base regime score for per-stock sensitivity."""
    score = base

    # Rate sensitivity (성장주/기술주 penalized when rates rising)
    fed = _nav(macro.get("fed_rate"))
    us_10y = _nav(macro.get("us_10y"))
    if fed is not None and us_10y is not None:
        rate_level = (fed + us_10y) / 2
        if sector in ("기술", "성장", "tech", "growth"):
            if rate_level > 4:
                score -= 10
            elif rate_level < 2:
                score += 8

    # FX sensitivity (수출주 rewarded on KRW weakness)
    usdkrw = _nav(macro.get("usdkrw"))
    if usdkrw is not None:
        if sector in ("반도체", "자동차", "조선", "방산", "export"):
            score += (usdkrw - 1300) / 100 * 5  # +5 per 100 KRW depreciation
        elif sector in ("항공", "수입", "import"):
            score -= (usdkrw - 1300) / 100 * 5

    # VIX (high VIX = risk-off)
    vix = _nav(macro.get("vix"))
    if vix is not None:
        if vix > 30:
            score -= 15
        elif vix < 15:
            score += 5

    # Market momentum
    idx_ret = _nav(macro.get("nasdaq_60d") or macro.get("sp500_60d"))
    if idx_ret is not None:
        score += min(10.0, max(-10.0, idx_ret * 0.3))

    return float(max(0.0, min(100.0, score)))


@dataclass
class MacroResult:
    score: float
    regime: str
    sector_hints: list[str]
    key_required: list[str] = field(default_factory=list)
    components: dict = field(default_factory=dict)


def compute_macro(macro_data: dict, sector: str = "", beta: float = 1.0) -> MacroResult:
    regime = macro_data.get("regime", "둔화")
    base = _regime_base_score(regime)
    score = _modulate(base, macro_data, sector=sector, beta=beta)

    return MacroResult(
        score=round(score, 2),
        regime=regime,
        sector_hints=macro_data.get("sector_hints", []),
        key_required=macro_data.get("key_required", []),
        components={
            "vix": _nav(macro_data.get("vix")),
            "fed_rate": _nav(macro_data.get("fed_rate")),
            "us_10y": _nav(macro_data.get("us_10y")),
            "usdkrw": _nav(macro_data.get("usdkrw")),
            "nasdaq_60d": _nav(macro_data.get("nasdaq_60d")),
            "yield_curve": _nav(macro_data.get("yield_curve")),
        },
    )
