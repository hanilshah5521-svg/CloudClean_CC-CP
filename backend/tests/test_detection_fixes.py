"""Duplicate detection, savings attribution and Drive listing fixes."""
from app.analyzers.duplicates import find_duplicate_groups
from app.integrations.google_drive import FILE_FIELDS, LIST_QUERY
from app.recommendations.engine import RecommendationEngine
from app.services.drive_service import _normalize

MB = 1024 * 1024


def f(drive_id, name, size, *, content_hash=None, mime="application/pdf", days=10, category=None, ext=None):
    ext = ext if ext is not None else ("." + name.rsplit(".", 1)[-1].lower() if "." in name else "")
    return {
        "drive_id": drive_id, "name": name, "size_bytes": size, "modified_time": None,
        "content_hash": content_hash, "mime_type": mime, "extension": ext,
        "category": category or ("pdf" if ext == ".pdf" else "other"),
        "inactivity_days": days, "is_google_workspace_file": mime.startswith("application/vnd.google-apps."),
    }


def make_engine(**kw):
    return RecommendationEngine(large_mb=100, very_large_mb=500, huge_mb=1024, min_saving_percent=10.0, **kw)


def test_same_name_and_size_but_different_checksums_are_versions_not_copies():
    groups = find_duplicate_groups([
        f("a", "report.pdf", 1000, content_hash="h1"),
        f("b", "report (1).pdf", 1000, content_hash="h2"),
    ])
    assert len(groups) == 1
    assert groups[0].level == "name" and groups[0].review_only


def test_matching_checksums_are_exact_copies_even_with_unrelated_names():
    groups = find_duplicate_groups([
        f("a", "IMG_2041.jpg", 5000, content_hash="same"),
        f("b", "beach.jpg", 5000, content_hash="same"),
    ])
    assert [(g.level, g.review_only) for g in groups] == [("hash", False)]


def test_folders_and_shortcuts_are_never_grouped():
    folder = "application/vnd.google-apps.folder"
    groups = find_duplicate_groups([
        f("a", "Photos", 0, mime=folder), f("b", "Photos", 0, mime=folder),
        f("c", "Photos", 0, mime="application/vnd.google-apps.shortcut"),
    ])
    assert groups == []


def test_generic_names_and_different_extensions_are_not_grouped():
    groups = find_duplicate_groups([
        f("a", "scan.pdf", 1000), f("b", "scan (1).pdf", 2000),          # generic name
        f("c", "thesis.pdf", 1000), f("d", "thesis.docx", 3000, mime="x"),  # different format
    ])
    assert groups == []


def test_version_groups_count_zero_savings_and_no_score_penalty():
    engine = make_engine()
    files = [f("a", "thesis.pdf", 50 * MB, content_hash="h1"), f("b", "thesis_final.pdf", 60 * MB, content_hash="h2")]
    groups = find_duplicate_groups(files)
    recs = engine.generate_recommendations(files, groups)
    dup = [r for r in recs if r.type == "duplicate"]
    assert dup and dup[0].estimated_saving_bytes == 0 and dup[0].action == "review_versions"
    score = engine.calculate_optimization_score(files, groups, total_used_bytes=110 * MB)
    assert score["breakdown"]["duplicate_inefficiency"] == 0


def test_each_file_contributes_to_at_most_one_saving():
    engine = make_engine(inactive_days=365)
    files = [
        f("dup1", "data.csv", 10 * MB, content_hash="x", days=900, category="documents"),
        f("dup2", "data (1).csv", 10 * MB, content_hash="x", days=900, category="documents"),
        f("pdf", "big.pdf", 40 * MB, content_hash="p", days=900),                   # compressible
        f("log", "server.log", 20 * MB, content_hash="l", days=900),                # archivable
        f("jpg", "old.jpg", 8 * MB, content_hash="j", days=900, category="images", mime="image/jpeg"),
        f("mp4", "clip.mp4", 300 * MB, content_hash="v", days=900, category="video", mime="video/mp4"),
    ]
    recs = engine.generate_recommendations(files, find_duplicate_groups(files))
    archive = next(r for r in recs if r.type == "archive")
    # Duplicates and compressible files are already covered; JPEG/MP4 don't zip.
    assert archive.extra["file_ids"] == ["log"]
    covered = [r.file_id for r in recs if r.file_id and r.estimated_saving_bytes]
    covered += [i for r in recs if r.type == "duplicate" for i in r.group_ref.drive_ids]
    covered += archive.extra["file_ids"]
    assert len(covered) == len(set(covered))


def test_archive_uses_the_users_inactivity_threshold():
    files = [f("log", "server.log", 20 * MB, days=200)]
    assert make_engine(inactive_days=365).analyze_archive_candidates(files) is None
    assert make_engine(inactive_days=180).analyze_archive_candidates(files) is not None


def test_already_compressed_files_are_not_recommended_again():
    pdf = f("a", "big.pdf", 40 * MB)
    assert make_engine().analyze_compression(pdf) is not None
    assert make_engine(already_optimized_ids={"a"}).analyze_compression(pdf) is None


def test_drive_listing_is_owned_files_only_and_requests_checksums():
    assert "'me' in owners" in LIST_QUERY
    assert "application/vnd.google-apps.folder" in LIST_QUERY
    for field in ("sha256Checksum", "md5Checksum", "quotaBytesUsed", "headRevisionId"):
        assert field in FILE_FIELDS


def test_normalize_uses_drive_checksum_and_quota_size():
    binary = _normalize({"id": "1", "name": "a.pdf", "mimeType": "application/pdf", "size": "10", "sha256Checksum": "abc"})
    assert binary["content_hash"] == "abc" and binary["size_bytes"] == 10
    md5_only = _normalize({"id": "2", "name": "b.pdf", "mimeType": "application/pdf", "size": "10", "md5Checksum": "m"})
    assert md5_only["content_hash"] == "m"
    doc = _normalize({"id": "3", "name": "Doc", "mimeType": "application/vnd.google-apps.document", "quotaBytesUsed": "2048"})
    assert doc["size_bytes"] == 2048 and doc["content_hash"] is None
