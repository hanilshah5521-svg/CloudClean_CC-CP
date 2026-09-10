from app.analyzers.duplicates import find_duplicate_groups
from app.recommendations.engine import RecommendationEngine

MB = 1024 * 1024


def make_engine():
    return RecommendationEngine(large_mb=100, very_large_mb=500, huge_mb=1024, min_saving_percent=10.0)


def test_compression_recommendation_reason_is_explainable():
    engine = make_engine()
    f = {"drive_id": "a", "name": "photo.jpg", "extension": ".jpg", "category": "images",
         "size_bytes": 10 * MB, "inactivity_days": 240, "is_google_workspace_file": False}
    rec = engine.analyze_compression(f)
    assert rec is not None
    assert rec.type == "compress"
    assert "File type: JPG" in rec.reason
    assert "Estimated saving" in rec.reason
    assert rec.estimated_saving_bytes > 0


def test_google_workspace_files_are_never_recommended_for_compression():
    engine = make_engine()
    f = {"drive_id": "a", "name": "Doc", "extension": "", "category": "documents",
         "size_bytes": 0, "inactivity_days": 10, "is_google_workspace_file": True}
    assert engine.analyze_compression(f) is None


def test_generate_recommendations_deduplicates_against_duplicate_groups():
    engine = make_engine()
    files = [
        {"drive_id": "a", "name": "report.jpg", "extension": ".jpg", "category": "images",
         "size_bytes": 5 * MB, "modified_time": None, "inactivity_days": 100, "is_google_workspace_file": False},
        {"drive_id": "b", "name": "report (1).jpg", "extension": ".jpg", "category": "images",
         "size_bytes": 5 * MB, "modified_time": None, "inactivity_days": 100, "is_google_workspace_file": False},
    ]
    groups = find_duplicate_groups(files)
    recs = engine.generate_recommendations(files, groups)
    # Only the duplicate-group recommendation should appear — not a separate
    # per-file compression rec for the same bytes (would double-count savings).
    assert len(recs) == 1
    assert recs[0].type == "duplicate"


def test_optimization_score_penalizes_duplicates_and_is_bounded():
    engine = make_engine()
    files = [
        {"drive_id": "a", "name": "x.jpg", "extension": ".jpg", "category": "images", "size_bytes": 50 * MB,
         "modified_time": None, "inactivity_days": 10, "is_google_workspace_file": False},
        {"drive_id": "b", "name": "x (1).jpg", "extension": ".jpg", "category": "images", "size_bytes": 50 * MB,
         "modified_time": None, "inactivity_days": 10, "is_google_workspace_file": False},
    ]
    groups = find_duplicate_groups(files)
    score = engine.calculate_optimization_score(files, groups, total_used_bytes=100 * MB)
    assert 0 <= score["score"] <= 100
    assert score["breakdown"]["duplicate_inefficiency"] > 0


def test_optimization_score_perfect_when_no_files():
    engine = make_engine()
    score = engine.calculate_optimization_score([], [], total_used_bytes=0)
    assert score["score"] == 100
