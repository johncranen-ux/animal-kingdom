"""geo_range.py: shared rules for geographic ranges from GBIF wild records."""

from app import geo_range


def test_percentile_interpolates_like_percentile_cont():
    assert geo_range.percentile([1, 2, 3, 4, 5], 0.5) == 3
    assert geo_range.percentile([0, 10], 0.25) == 2.5
    assert geo_range.percentile([7], 0.995) == 7


def test_percentile_ignores_input_order():
    assert geo_range.percentile([5, 1, 3], 0.0) == 1


def test_make_range_rounds_and_keeps_counts():
    assert geo_range.make_range(-38.512, -26.4049, 138.6, 153.6, 350798, 1) == {
        "lat_min": -38.51, "lat_max": -26.4, "lon_min": 138.6, "lon_max": 153.6,
        "records": 350798, "countries": 1}


def test_make_range_drops_longitude_across_the_180_line():
    r = geo_range.make_range(51.6, 83.0, -179.7, 179.4, 4892)
    assert r == {"lat_min": 51.6, "lat_max": 83.0, "records": 4892}


def test_make_range_keeps_a_340_degree_span():
    assert "lon_min" in geo_range.make_range(0, 1, -170, 170, 10)


def test_constants():
    assert (geo_range.MIN_RECORDS, geo_range.WRAP_SPAN, geo_range.Q_LOW, geo_range.Q_HIGH) == \
        (10, 340.0, 0.005, 0.995)
