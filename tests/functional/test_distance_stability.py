"""The distance sensor should give consistent readings for a static
object - repeated single measurements should not swing wildly from
sample to sample.

The board actually wired up for this test run is a US-100 (in
TRIG/ECHO mode, jumper removed - see PRD 13), one of the three sensors
the firmware supports alongside HC-SR04/US-025. On real hardware a
static object gave identical readings sample to sample (zero jitter),
so the tolerance below is tight on purpose - it still allows for
minor real-world noise but will catch an actual instability
regression rather than let one hide behind a "generous" margin."""

import logging
import time

import pytest

log = logging.getLogger(__name__)

SAMPLE_COUNT = 8
STABILITY_TOLERANCE_CM = 1.0  # US-100 gave 0 cm jitter in practice; 1 cm still has headroom


@pytest.mark.functional
@pytest.mark.slow
def test_distance_readings_are_stable(logged_device):
    dev = logged_device
    readings = []
    log.info("Taking %d distance readings, 0.3s apart", SAMPLE_COUNT)
    for i in range(SAMPLE_COUNT):
        value = dev.get_distance_cm()
        log.info("Reading #%d: %s cm", i + 1, value if value is not None else "timeout")
        if value is not None:
            readings.append(value)
        time.sleep(0.3)

    log.info("Collected %d/%d valid readings: %s", len(readings), SAMPLE_COUNT, readings)
    assert len(readings) >= SAMPLE_COUNT // 2, (
        f"too many sensor timeouts: only {len(readings)}/{SAMPLE_COUNT} valid readings "
        f"- check that an object is in range of the US-100"
    )

    spread = max(readings) - min(readings)
    log.info("Spread across readings: %.1f cm (tolerance %.1f cm)", spread, STABILITY_TOLERANCE_CM)
    assert spread <= STABILITY_TOLERANCE_CM, (
        f"distance readings vary by {spread:.1f} cm across {len(readings)} samples "
        f"(tolerance {STABILITY_TOLERANCE_CM} cm): {readings}"
    )
