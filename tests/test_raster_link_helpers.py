from nasa_opera.dialogs.opera_dock import (
    _filename_from_url,
    _georef_from_coordinate_values,
    _is_metadata_subdataset,
    _link_matches_layer_filter,
    _parse_hdf5_subdataset_source,
)


def test_filename_from_url_removes_query_string():
    assert (
        _filename_from_url("https://example.com/path/OPERA_TEST.h5?token=abc")
        == "OPERA_TEST.h5"
    )


def test_link_matches_hdf5_full_filename_filter():
    link = "https://example.com/data/OPERA_L2_RTC-S1_TEST_v1.0.h5"

    assert _link_matches_layer_filter(link, "OPERA_L2_RTC-S1_TEST_v1.0.h5")


def test_link_matches_geotiff_band_filter():
    link = "https://example.com/data/OPERA_L3_DSWx-HLS_TEST_B01_WTR.tif"

    assert _link_matches_layer_filter(link, "B01_WTR")


def test_metadata_subdatasets_are_filtered():
    assert _is_metadata_subdataset(
        'HDF5:"/tmp/test.h5"://metadata/orbit/position',
        "[12x3] //metadata/orbit/position",
    )
    assert not _is_metadata_subdataset(
        'HDF5:"/tmp/test.h5"://data/VV',
        "[1500x3435] //data/VV",
    )


def test_parse_hdf5_subdataset_source():
    assert _parse_hdf5_subdataset_source('HDF5:"/tmp/test.h5"://data/VV') == (
        "/tmp/test.h5",
        "data/VV",
    )


def test_georef_from_coordinate_values_uses_pixel_edges():
    georef = _georef_from_coordinate_values(
        [708872.5, 708877.5],
        [4129315.0, 4129305.0],
        2,
        2,
        "EPSG:32611",
    )

    assert georef["output_srs"] == "EPSG:32611"
    assert georef["output_bounds"] == [708870.0, 4129320.0, 708880.0, 4129300.0]
