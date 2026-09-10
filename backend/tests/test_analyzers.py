from datetime import datetime, timedelta, timezone

from app.analyzers.duplicates import find_duplicate_groups, normalize_name
from app.analyzers.inactive import inactivity_bucket, inactivity_days
from app.analyzers.large_files import size_tier
from app.analyzers.compression_potential import estimate
from app.utils.classify import classify, extension_of


def test_normalize_name_strips_copy_markers():
    assert normalize_name("report (1).pdf") == "report"
    assert normalize_name("report_final.pdf") == "report"
    assert normalize_name("Copy of report.pdf") == "report"
    assert normalize_name("report.pdf") == "report"


def test_duplicate_detection_size_and_name():
    files = [
        {"drive_id": "a", "name": "report.pdf", "size_bytes": 1000, "modified_time": None},
        {"drive_id": "b", "name": "report (1).pdf", "size_bytes": 1000, "modified_time": None},
        {"drive_id": "c", "name": "unrelated.pdf", "size_bytes": 500, "modified_time": None},
    ]
    groups = find_duplicate_groups(files)
    assert len(groups) == 1
    assert set(groups[0].drive_ids) == {"a", "b"}
    assert groups[0].level == "size_name"


def test_duplicate_detection_prefers_hash_over_name():
    files = [
        {"drive_id": "a", "name": "x.pdf", "size_bytes": 100, "modified_time": None, "content_hash": "h1"},
        {"drive_id": "b", "name": "y.pdf", "size_bytes": 100, "modified_time": None, "content_hash": "h1"},
    ]
    groups = find_duplicate_groups(files)
    assert len(groups) == 1
    assert groups[0].level == "hash"


def test_duplicate_recommends_most_recent_as_keep():
    now = datetime.now(timezone.utc)
    files = [
        {"drive_id": "old", "name": "report.pdf", "size_bytes": 1000, "modified_time": now - timedelta(days=10)},
        {"drive_id": "new", "name": "report_final.pdf", "size_bytes": 1000, "modified_time": now},
    ]
    groups = find_duplicate_groups(files)
    assert groups[0].recommended_keep_drive_id == "new"


def test_no_false_positive_for_distinct_files():
    files = [
        {"drive_id": "a", "name": "budget_q1.xlsx", "size_bytes": 5000, "modified_time": None},
        {"drive_id": "b", "name": "budget_q2.xlsx", "size_bytes": 6000, "modified_time": None},
    ]
    assert find_duplicate_groups(files) == []


def test_inactivity_days_and_buckets():
    now = datetime.now(timezone.utc)
    d = inactivity_days(now - timedelta(days=400))
    assert 399 <= d <= 401
    assert inactivity_bucket(400) == "1+ year"
    assert inactivity_bucket(40) == "30+ days"
    assert inactivity_bucket(5) is None


def test_size_tier_thresholds():
    mb = 1024 * 1024
    assert size_tier(50 * mb, 100, 500, 1024) is None
    assert size_tier(150 * mb, 100, 500, 1024) == "large"
    assert size_tier(600 * mb, 100, 500, 1024) == "very_large"
    assert size_tier(2 * 1024 * mb, 100, 500, 1024) == "huge"


def test_compression_estimate_excludes_already_compressed():
    est = estimate("video", ".mp4", 500 * 1024 * 1024)
    assert est.compressible is False
    est_zip = estimate("archives", ".zip", 50 * 1024 * 1024)
    assert est_zip.compressible is False


def test_compression_estimate_jpeg_scales_with_size():
    small = estimate("images", ".jpg", 500 * 1024)
    big = estimate("images", ".jpg", 10 * 1024 * 1024)
    assert big.estimated_ratio > small.estimated_ratio
    assert big.compressible and small.compressible


def test_classify_uses_mime_first():
    assert classify("image/jpeg", ".txt") == "images"  # mime wins even with a misleading extension
    assert classify("application/pdf", "") == "pdf"
    assert extension_of("archive.tar.gz") == ".gz"
