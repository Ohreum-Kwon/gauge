"""Display panel measurements: what end-of-line test measures and how raw readings
become the numbers that get charted.

A panel goes through two kinds of test:

- Optical, with a colorimeter on a white or gray pattern: luminance at nine zones (for
  brightness and uniformity), the white point's chromaticity (for color accuracy as
  CIEDE2000 delta E against D65), and a gray ramp (for gamma).
- Electrical, on the TFT backplane and the module: threshold voltage (Vth), on current,
  the on/off current ratio, supply current, power draw, and the refresh rate.

Spec limits live here in code, next to the metric definitions, so a reviewer can see
them in one place. Pure functions only, no database access.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

Lab = tuple[float, float, float]

# CIE 1931 chromaticity of the D65 white point, the sRGB / Rec. 709 target.
D65_XY = (0.3127, 0.3290)


class MetricGroup(StrEnum):
    optical = "optical"
    electrical = "electrical"


@dataclass(frozen=True)
class Metric:
    key: str
    name: str
    unit: str
    group: MetricGroup
    target: float
    lsl: float | None  # lower spec limit; None for a one-sided spec
    usl: float | None  # upper spec limit


METRICS: dict[str, Metric] = {
    m.key: m
    for m in (
        Metric(
            "white_luminance",
            "Center white luminance",
            "cd/m²",
            MetricGroup.optical,
            target=350,
            lsl=320,
            usl=380,
        ),
        Metric(
            "luminance_uniformity",
            "Luminance uniformity (9-zone min/max)",
            "%",
            MetricGroup.optical,
            target=90,
            lsl=80,
            usl=None,
        ),
        Metric(
            "white_delta_e",
            "White point error vs D65 (ΔE2000)",
            "ΔE",
            MetricGroup.optical,
            target=0.8,
            lsl=None,
            usl=3.0,
        ),
        Metric("gamma", "Gamma", "", MetricGroup.optical, target=2.2, lsl=2.1, usl=2.3),
        Metric(
            "tft_vth",
            "TFT threshold voltage",
            "V",
            MetricGroup.electrical,
            target=1.0,
            lsl=0.7,
            usl=1.3,
        ),
        Metric(
            "tft_ion", "TFT on current", "µA", MetricGroup.electrical, target=15, lsl=10, usl=None
        ),
        Metric(
            "tft_on_off",
            "TFT on/off ratio",
            "decades",
            MetricGroup.electrical,
            target=8,
            lsl=7,
            usl=None,
        ),
        Metric(
            "supply_current",
            "Supply current (full white)",
            "mA",
            MetricGroup.electrical,
            target=400,
            lsl=None,
            usl=480,
        ),
        Metric(
            "panel_power",
            "Panel power (full white)",
            "W",
            MetricGroup.electrical,
            target=5.0,
            lsl=None,
            usl=6.0,
        ),
        Metric(
            "refresh_rate",
            "Refresh rate",
            "Hz",
            MetricGroup.electrical,
            target=60.0,
            lsl=59.9,
            usl=60.1,
        ),
    )
}


def luminance_uniformity(zones: Sequence[float]) -> float:
    """Uniformity in percent: dimmest zone over brightest. A 9-zone (3x3) grid is the
    usual measurement; 100 means perfectly even."""
    if not zones or min(zones) < 0:
        raise ValueError("need non-negative zone luminances")
    brightest = max(zones)
    if brightest == 0:
        raise ValueError("panel is dark")
    return 100 * min(zones) / brightest


def fit_gamma(levels: Sequence[int], luminances: Sequence[float], max_level: int = 255) -> float:
    """Gamma from a gray ramp: the exponent g in L = L_black + (L_white - L_black) * v**g,
    where v is the drive level as a fraction of max_level.

    The ramp must include black (level 0) and white (max_level). The fit is least
    squares through the origin in log-log space, over the levels in between.
    """
    readings = dict(zip(levels, luminances, strict=True))
    if 0 not in readings or max_level not in readings:
        raise ValueError("ramp must include black and white")
    black, white = readings[0], readings[max_level]
    if white <= black:
        raise ValueError("white must be brighter than black")
    xs, ys = [], []
    for level, lum in readings.items():
        relative = (lum - black) / (white - black)
        if 0 < level < max_level and relative > 0:
            xs.append(math.log(level / max_level))
            ys.append(math.log(relative))
    if not xs:
        raise ValueError("need at least one gray level between black and white")
    return sum(x * y for x, y in zip(xs, ys, strict=True)) / sum(x * x for x in xs)


def xyy_to_xyz(x: float, y: float, big_y: float) -> tuple[float, float, float]:
    if y <= 0:
        raise ValueError("y must be positive")
    return x * big_y / y, big_y, (1 - x - y) * big_y / y


def xyz_to_lab(xyz: tuple[float, float, float], white: tuple[float, float, float]) -> Lab:
    """CIE 1976 L*a*b* relative to a reference white, both in XYZ."""

    def f(t: float) -> float:
        delta = 6 / 29
        return t ** (1 / 3) if t > delta**3 else t / (3 * delta**2) + 4 / 29

    fx, fy, fz = (f(v / w) for v, w in zip(xyz, white, strict=True))
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e_2000(lab1: Lab, lab2: Lab) -> float:
    """CIEDE2000 color difference (kL = kC = kH = 1), following Sharma, Wu and Dalal,
    "The CIEDE2000 Color-Difference Formula" (2005). Around 1 is just noticeable; panel
    specs commonly allow up to 2 or 3."""
    l1, a1, b1 = lab1
    l2, a2, b2 = lab2

    c_bar = (math.hypot(a1, b1) + math.hypot(a2, b2)) / 2
    g = 0.5 * (1 - math.sqrt(c_bar**7 / (c_bar**7 + 25**7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)

    def hue(b: float, ap: float) -> float:
        return 0.0 if b == 0 and ap == 0 else math.degrees(math.atan2(b, ap)) % 360

    h1p, h2p = hue(b1, a1p), hue(b2, a2p)

    dl = l2 - l1
    dc = c2p - c1p
    if c1p * c2p == 0:
        dh = 0.0
    else:
        dh = h2p - h1p
        if dh > 180:
            dh -= 360
        elif dh < -180:
            dh += 360
    big_dh = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(dh / 2))

    l_bar = (l1 + l2) / 2
    cp_bar = (c1p + c2p) / 2
    if c1p * c2p == 0:
        h_bar = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        h_bar = (h1p + h2p) / 2
    elif h1p + h2p < 360:
        h_bar = (h1p + h2p + 360) / 2
    else:
        h_bar = (h1p + h2p - 360) / 2

    t = (
        1
        - 0.17 * math.cos(math.radians(h_bar - 30))
        + 0.24 * math.cos(math.radians(2 * h_bar))
        + 0.32 * math.cos(math.radians(3 * h_bar + 6))
        - 0.20 * math.cos(math.radians(4 * h_bar - 63))
    )
    d_theta = 30 * math.exp(-(((h_bar - 275) / 25) ** 2))
    r_c = 2 * math.sqrt(cp_bar**7 / (cp_bar**7 + 25**7))
    s_l = 1 + 0.015 * (l_bar - 50) ** 2 / math.sqrt(20 + (l_bar - 50) ** 2)
    s_c = 1 + 0.045 * cp_bar
    s_h = 1 + 0.015 * cp_bar * t
    r_t = -math.sin(math.radians(2 * d_theta)) * r_c

    return math.sqrt(
        (dl / s_l) ** 2 + (dc / s_c) ** 2 + (big_dh / s_h) ** 2 + r_t * (dc / s_c) * (big_dh / s_h)
    )


def white_point_delta_e(x: float, y: float) -> float:
    """CIEDE2000 between a measured white point's chromaticity and D65.

    Only chromaticity is compared: both are scaled to the same luminance, so a panel
    that is dim but neutral scores 0 here (brightness is its own metric).
    """
    white = xyy_to_xyz(*D65_XY, 100)
    measured = xyz_to_lab(xyy_to_xyz(x, y, 100), white)
    return delta_e_2000((100.0, 0.0, 0.0), measured)
