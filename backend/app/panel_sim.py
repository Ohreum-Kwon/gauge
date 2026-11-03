"""Simulate a week of end-of-line display panel testing on two production lines, so the
Panel Line dashboard has a real story to show. Safe to run more than once.

    uv run python -m app.panel_sim            # simulate if there's no complete week yet
    uv run python -m app.panel_sim --reset    # delete every measurement and simulate again

Every three hours, five panels from each line are tested: a subgroup. Each panel gets
raw readings the way a test station takes them (nine luminance zones, white point
chromaticity, a gray ramp, TFT and module electricals), and `app.panel` turns those
into the charted metrics. The first three days are the baseline the control limits come
from. Then two things go wrong, both starting while every panel is inside spec:

- L2's backlight ages from day 4: luminance falls about 0.15% per subgroup, and the
  edge and corner zones fade faster than the center, so uniformity drops too.
- L1 builds from TFT lot T-2406 on day 6. That lot's threshold voltage runs about
  0.06 V high and its on current about 8% low.

Expected result with the default seed: L2 luminance and uniformity warn on day 4 and
alarm on day 5, L1 Vth and Ion alarm at the first subgroup of day 6, and the other
sixteen charts stay quiet. Healthy charts aren't always quiet: across seeds, about one
in four gets a false Shewhart alarm in a week, the price of watching twenty charts at a
0.3% to 0.7% false alarm rate per point each. The default seed is one where they don't,
so the demo shows the two real problems; tests pin it.
"""

import argparse
import math
import random
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import delete, insert
from sqlmodel import Session, func, select

from app.db import get_engine
from app.models import PanelMeasurement
from app.panel import D65_XY, fit_gamma, luminance_uniformity, white_point_delta_e

LINES = ("L1", "L2")
DAYS = 7
PERIODS_PER_DAY = 8  # one subgroup every three hours
PANELS_PER_SUBGROUP = 5
SUBGROUPS = DAYS * PERIODS_PER_DAY

AGING_LINE = "L2"
AGING_STARTS = 3 * PERIODS_PER_DAY  # day 4
AGING_PER_SUBGROUP = 0.0015  # fraction of luminance lost per subgroup, at the center
EDGE_AGING_PER_SUBGROUP = 0.001  # extra loss at the corners

SHIFTED_LINE = "L1"
SHIFTED_LOT = "T-2406"  # L1's lot on day 6
VTH_SHIFT = 0.06  # volts
ION_FACTOR = 0.92

# Relative luminance of each zone on a 3x3 grid (row by row) for an edge-lit panel:
# brightest in the center, dimmest in the corners.
ZONE_PROFILE = (0.90, 0.94, 0.90, 0.94, 1.00, 0.94, 0.90, 0.94, 0.90)
GRAY_LEVELS = (0, 32, 64, 96, 128, 160, 192, 224, 255)
SUPPLY_VOLTAGE = 12.0


def lot_for(line: str, day: int) -> str:
    """Each line builds from a new TFT lot every day; day is 1-based."""
    return f"T-24{day:02d}" if line == SHIFTED_LINE else f"T-25{day:02d}"


def expected_rows() -> int:
    return len(LINES) * SUBGROUPS * PANELS_PER_SUBGROUP * 10


def simulate(session: Session, reset: bool = False, seed: int = 1611) -> int:
    """Write a week of measurements and return how many rows exist afterwards."""
    existing = session.exec(select(func.count()).select_from(PanelMeasurement)).one()
    if existing == expected_rows() and not reset:
        print("A full week of panel measurements already exists; pass --reset to redo it")
        return existing
    # A partial week (a run cut short) or a reset starts over.
    session.execute(delete(PanelMeasurement))

    rng = random.Random(seed)
    start = datetime.combine(datetime.now(UTC).date() - timedelta(days=DAYS), time(0), UTC)
    rows = []
    for line in LINES:
        for subgroup in range(SUBGROUPS):
            day = subgroup // PERIODS_PER_DAY + 1
            lot = lot_for(line, day)
            for panel in range(PANELS_PER_SUBGROUP):
                serial = f"{line}-{subgroup:03d}-{panel}"
                at = start + timedelta(hours=3 * subgroup, minutes=4 * panel)
                for metric, value in measure_panel(line, lot, subgroup, rng).items():
                    rows.append(
                        {
                            "line": line,
                            "lot": lot,
                            "panel_serial": serial,
                            "subgroup": subgroup,
                            "metric": metric,
                            "value": value,
                            "measured_at": at,
                        }
                    )
    session.execute(insert(PanelMeasurement), rows)
    session.commit()
    print(f"Simulated {len(rows)} measurements: {DAYS} days on lines {', '.join(LINES)}")
    return len(rows)


def measure_panel(line: str, lot: str, subgroup: int, rng: random.Random) -> dict[str, float]:
    """One panel's test results, from simulated raw readings."""
    # Optical. Each panel's backlight differs a little; each zone reading adds meter noise.
    aged = max(0, subgroup - AGING_STARTS) if line == AGING_LINE else 0
    brightness = 350 * rng.gauss(1, 0.012) * (1 - AGING_PER_SUBGROUP * aged)
    zones = []
    for profile in ZONE_PROFILE:
        # Zones further from the center (lower profile) fade faster as the LEDs age.
        edge = (1 - profile) / (1 - min(ZONE_PROFILE))
        fade = 1 - EDGE_AGING_PER_SUBGROUP * aged * edge
        zones.append(brightness * profile * fade * rng.gauss(1, 0.008))

    # The white point sits a little warm of D65, as a tuned panel typically does.
    x = D65_XY[0] + 0.0025 + rng.gauss(0, 0.0005)
    y = D65_XY[1] + 0.0020 + rng.gauss(0, 0.0005)

    gamma = rng.gauss(2.2, 0.015)
    white, black = zones[4], 0.3
    ramp = [black + (white - black) * (v / 255) ** gamma * rng.gauss(1, 0.004) for v in GRAY_LEVELS]
    ramp[0], ramp[-1] = black, white

    # Electrical. A shifted lot's TFTs switch on later and conduct less.
    shifted = line == SHIFTED_LINE and lot == SHIFTED_LOT
    vth = rng.gauss(1.0, 0.03) + (VTH_SHIFT if shifted else 0)
    ion = rng.gauss(15, 0.6) * (ION_FACTOR if shifted else 1)  # µA
    ioff = rng.lognormvariate(math.log(0.08), 0.25)  # pA
    current = rng.gauss(400, 8)  # mA at full white
    power = SUPPLY_VOLTAGE * current / 1000 + rng.gauss(0, 0.03)  # W

    return {
        "white_luminance": zones[4],
        "luminance_uniformity": luminance_uniformity(zones),
        "white_delta_e": white_point_delta_e(x, y),
        "gamma": fit_gamma(GRAY_LEVELS, ramp),
        "tft_vth": vth,
        "tft_ion": ion,
        "tft_on_off": math.log10(ion * 1e-6 / (ioff * 1e-12)),
        "supply_current": current,
        "panel_power": power,
        "refresh_rate": rng.gauss(60.0, 0.008),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--reset", action="store_true", help="delete and re-simulate")
    args = parser.parse_args()
    with Session(get_engine()) as session:
        simulate(session, reset=args.reset)


if __name__ == "__main__":
    main()
