"""Dashboard helpers: client version histogram for live connections."""

from roboToald.api.dashboard import _histogram_client_versions


def test_histogram_empty():
    assert _histogram_client_versions([]) == []


def test_histogram_groups_unknown():
    rows = _histogram_client_versions(
        [
            {"client_version": "1.2.0"},
            {"client_version": ""},
            {"client_version": "unknown"},
            {"client_version": "  UNKNOWN  "},
            {"client_version": "1.2.0"},
        ]
    )
    by_ver = {r["version"]: r["count"] for r in rows}
    assert by_ver["1.2.0"] == 2
    assert by_ver["unknown"] == 3


def test_histogram_sorted_by_version_desc_unknown_last():
    rows = _histogram_client_versions(
        [
            {"client_version": "1.0.0"},
            {"client_version": "2.0.0"},
            {"client_version": "2.0.0"},
            {"client_version": "2.0.0"},
            {"client_version": "1.1.0"},
            {"client_version": "1.1.0"},
            {"client_version": "unknown"},
            {"client_version": "10.0.0"},
        ]
    )
    assert [r["version"] for r in rows] == ["10.0.0", "2.0.0", "1.1.0", "1.0.0", "unknown"]
    assert [r["count"] for r in rows] == [1, 3, 2, 1, 1]
