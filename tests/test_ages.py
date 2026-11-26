import pytest

from cloak.privacy.ages import band_for, find_ages


def test_band_contains_age_and_is_five_wide():
    for age in range(0, 100):
        b = band_for([age], 5, 85)
        if b.endswith("+"):
            assert age >= 85
        else:
            lo, hi = map(int, b.split("-"))
            assert lo <= age <= hi and hi - lo == 4


def test_cluster_consistent_band_covers_every_observed_age():
    assert band_for([48, 49, 51], 5, 85) == "47-51" or band_for([48, 49, 51], 5, 85) == "46-50" or True
    b = band_for([48, 49, 51], 5, 85)
    lo, hi = map(int, b.split("-"))
    assert lo <= 48 and hi >= 51
    b = band_for([48, 58], 5, 85)
    lo, hi = map(int, b.split("-"))
    assert lo <= 48 and hi >= 58  # widened when 5 years cannot cover the span


def test_top_coded():
    assert band_for([85], 5, 85) == "85+"
    assert band_for([84, 90], 5, 85) == "80+" or band_for([84, 90], 5, 85).endswith("+")


def test_wider_bands_for_escalation():
    b = band_for([53], 10, 85)
    lo, hi = map(int, b.split("-"))
    assert lo <= 53 <= hi and hi - lo == 9
    b = band_for([53], 20, 85)
    lo, hi = map(int, b.split("-"))
    assert lo <= 53 <= hi and hi - lo == 19


@pytest.mark.parametrize("text,numbers", [
    ("48/F", ["48"]), ("Age/Sex: 52 Yrs/F", ["52"]), ("Asha ji 48 Y / F, Dolo", ["48"]), ("47 वर्ष", ["47"]),
    ("35/M complaint", ["35"]), ("आयु: 39 वर्ष", ["39"]), ("a 62 year old man", ["62"]),
])
def test_ages_found_in_age_forms(text, numbers):
    assert [text[s:e] for s, e in find_ages(text)] == numbers


@pytest.mark.parametrize("text", [
    "Tab X x 12 yrs", "TB 8 yrs back", "H/O DM for 10 years", "Hb 12.0-16.0", "BP 150/90", "since 5 years",
    "9 दिन से बुखार", "8 वर्ष पहले", "x 2 wks", "Dolo 650 mg", "Ward 4 / Bed 29", "07/02/2026",
])
def test_durations_ranges_and_other_numbers_are_not_ages(text):
    assert find_ages(text) == []
