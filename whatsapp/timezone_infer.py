"""Infer a sensible IANA timezone from an E.164 phone number.

We don't need pinpoint accuracy — we need a Saturday-morning broadcast hour
that lands in the user's daylight. Country code → primary timezone covers
~95% of cases. Ambiguous countries (US, CA, AU, BR, RU) fall back to the
most populous zone; users can override with `TIMEZONE <iana>` later.
"""

from __future__ import annotations

# Country dial code → IANA zone. Picked for fantasy-relevant markets and the
# most populous zone in multi-zone countries.
_CC_TO_TZ: dict[str, str] = {
    "1": "America/New_York",      # US/Canada — most populous zone
    "7": "Europe/Moscow",
    "20": "Africa/Cairo",
    "27": "Africa/Johannesburg",
    "30": "Europe/Athens",
    "31": "Europe/Amsterdam",
    "32": "Europe/Brussels",
    "33": "Europe/Paris",
    "34": "Europe/Madrid",
    "36": "Europe/Budapest",
    "39": "Europe/Rome",
    "40": "Europe/Bucharest",
    "41": "Europe/Zurich",
    "43": "Europe/Vienna",
    "44": "Europe/London",
    "45": "Europe/Copenhagen",
    "46": "Europe/Stockholm",
    "47": "Europe/Oslo",
    "48": "Europe/Warsaw",
    "49": "Europe/Berlin",
    "51": "America/Lima",
    "52": "America/Mexico_City",
    "54": "America/Argentina/Buenos_Aires",
    "55": "America/Sao_Paulo",
    "56": "America/Santiago",
    "57": "America/Bogota",
    "58": "America/Caracas",
    "60": "Asia/Kuala_Lumpur",
    "61": "Australia/Sydney",
    "62": "Asia/Jakarta",
    "63": "Asia/Manila",
    "64": "Pacific/Auckland",
    "65": "Asia/Singapore",
    "66": "Asia/Bangkok",
    "81": "Asia/Tokyo",
    "82": "Asia/Seoul",
    "84": "Asia/Ho_Chi_Minh",
    "86": "Asia/Shanghai",
    "90": "Europe/Istanbul",
    "91": "Asia/Kolkata",
    "92": "Asia/Karachi",
    "93": "Asia/Kabul",
    "94": "Asia/Colombo",
    "95": "Asia/Yangon",
    "98": "Asia/Tehran",
    "212": "Africa/Casablanca",
    "213": "Africa/Algiers",
    "216": "Africa/Tunis",
    "218": "Africa/Tripoli",
    "234": "Africa/Lagos",
    "254": "Africa/Nairobi",
    "351": "Europe/Lisbon",
    "352": "Europe/Luxembourg",
    "353": "Europe/Dublin",
    "354": "Atlantic/Reykjavik",
    "358": "Europe/Helsinki",
    "359": "Europe/Sofia",
    "370": "Europe/Vilnius",
    "371": "Europe/Riga",
    "372": "Europe/Tallinn",
    "385": "Europe/Zagreb",
    "386": "Europe/Ljubljana",
    "420": "Europe/Prague",
    "421": "Europe/Bratislava",
    "852": "Asia/Hong_Kong",
    "853": "Asia/Macau",
    "886": "Asia/Taipei",
    "962": "Asia/Amman",
    "965": "Asia/Kuwait",
    "966": "Asia/Riyadh",
    "971": "Asia/Dubai",
    "972": "Asia/Jerusalem",
    "974": "Asia/Qatar",
}

_DEFAULT_TZ = "Europe/London"  # F1 broadcasts default — sensible fallback


def _digits_only(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def _match_country_code(digits: str) -> str | None:
    """Match the longest country-code prefix present in the map."""
    for length in (3, 2, 1):
        prefix = digits[:length]
        if prefix in _CC_TO_TZ:
            return prefix
    return None


def needs_manual_timezone(phone: str) -> bool:
    """True when the country code is unknown — caller should ask for IANA tz."""
    digits = _digits_only(phone)
    if not digits:
        return True
    return _match_country_code(digits) is None


def infer_timezone(phone: str) -> str:
    """Best-guess IANA timezone from an E.164 phone number.

    Always returns a valid IANA zone. Caller may still ask the user to
    confirm if they want pinpoint accuracy (e.g. US west-coast users).
    """
    digits = _digits_only(phone)
    if not digits:
        return _DEFAULT_TZ
    cc = _match_country_code(digits)
    if cc is None:
        return _DEFAULT_TZ
    return _CC_TO_TZ[cc]
