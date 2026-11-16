"""Reference 24-hour PM2.5 thresholds used for exceedance counting.

Each entry names its source. These are DAILY-mean comparison levels for
screening historical archive data, not regulatory determinations; the legal
standards have statistical forms (e.g. the US level is evaluated as a 98th
percentile over 3 years) that this tool does not compute.
"""
from __future__ import annotations

STANDARDS: dict[str, dict] = {
    "us_24h": {
        "label": "US EPA 24h PM2.5 (35 µg/m³)",
        "parameter": "pm25",
        "threshold": 35.0,
        "units": "µg/m³",
        "source": "US EPA PM NAAQS (24-hour level; unchanged by the 2024 revision)",
        "source_url": "https://www.epa.gov/pm-pollution/timeline-particulate-matter-pm-national-ambient-air-quality-standards-naaqs",
    },
    "who_2021_24h": {
        "label": "WHO 2021 guideline 24h PM2.5 (15 µg/m³)",
        "parameter": "pm25",
        "threshold": 15.0,
        "units": "µg/m³",
        "source": "WHO global air quality guidelines 2021, 24-hour PM2.5 guideline level",
        "source_url": "https://www.who.int/publications/i/item/9789240034228",
    },
    "india_24h": {
        "label": "India NAAQS 24h PM2.5 (60 µg/m³)",
        "parameter": "pm25",
        "threshold": 60.0,
        "units": "µg/m³",
        "source": "CPCB National Ambient Air Quality Standards (2009), 24-hour PM2.5",
        "source_url": "https://cpcb.nic.in/uploads/National_Ambient_Air_Quality_Standards.pdf",
    },
    "india_24h_pm10": {
        "label": "India NAAQS 24h PM10 (100 µg/m³)",
        "parameter": "pm10",
        "threshold": 100.0,
        "units": "µg/m³",
        "source": "CPCB National Ambient Air Quality Standards (2009), 24-hour PM10",
        "source_url": "https://cpcb.nic.in/uploads/National_Ambient_Air_Quality_Standards.pdf",
    },
    "us_24h_pm10": {
        "label": "US EPA 24h PM10 (150 µg/m³)",
        "parameter": "pm10",
        "threshold": 150.0,
        "units": "µg/m³",
        "source": "US EPA PM NAAQS (24-hour PM10 level)",
        "source_url": "https://www.epa.gov/pm-pollution/national-ambient-air-quality-standards-naaqs-pm",
    },
}


def get(key: str) -> dict:
    if key not in STANDARDS:
        raise KeyError(f"unknown standard {key!r}; choices: {sorted(STANDARDS)}")
    return STANDARDS[key]
