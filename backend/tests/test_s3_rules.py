"""S3 savings engine: pure rules over scan data."""
from app.analyzers.s3_rules import (
    TRASH_PREFIX, BucketScan, S3Engine, covered_by_transition, has_abort_rule, merge_rule, rule_prefix,
)

MB = 1024 * 1024
GB = 1024 * MB


def obj(key, size=50 * MB, age=200, cls="STANDARD", etag=None):
    return {"key": key, "size": size, "age_days": age, "storage_class": cls, "etag": etag or f'"{key}"'}


def scan(objects=(), versioning="", rules=(), noncurrent=(), uploads=()):
    return BucketScan("b", "us-east-1", versioning, list(rules), list(objects), list(noncurrent), list(uploads))


def recs_of(s, kind):
    return [r for r in S3Engine().analyze(s)[0] if r.type == kind]


def test_tiering_rule_matches_what_it_estimates():
    s = scan([obj("logs/a.log", age=10), obj("logs/b.log", age=45), obj("logs/c.log", age=400)])
    [rec] = recs_of(s, "tiering")
    rule = rec.payload["rule"]
    assert rule["Filter"] == {"Prefix": "logs/"}
    assert rule["Transitions"] == [{"Days": 30, "StorageClass": "STANDARD_IA"}, {"Days": 90, "StorageClass": "GLACIER_IR"}]
    assert rec.payload["objects_moved"] == 2  # the 10-day-old object isn't due yet
    expected = (50 * MB / GB) * ((0.023 - 0.0125) + (0.023 - 0.004))
    assert abs(rec.monthly_saving_usd - expected) < 1e-3
    assert rec.one_time_cost_usd > 0 and "Trade-offs" in rec.reason


def test_backup_prefixes_get_the_archival_plan():
    [rec] = recs_of(scan([obj("backups/db.sql.gz", age=400)]), "tiering")
    assert rec.payload["plan"] == "archival"
    assert rec.payload["rule"]["Transitions"][-1]["StorageClass"] == "DEEP_ARCHIVE"
    assert "12 hours" in rec.reason


def test_small_objects_and_already_tiered_prefixes_are_skipped():
    existing = {"ID": "mine", "Status": "Enabled", "Filter": {"Prefix": "logs/"},
                "Transitions": [{"Days": 60, "StorageClass": "GLACIER"}]}
    s = scan([obj("logs/a.log", age=400), obj("tiny/x.css", size=10 * 1024, age=400)], rules=[existing])
    assert recs_of(s, "tiering") == []


def test_abort_uploads_rule_only_when_missing():
    s = scan(uploads=[{"key": "x", "size": 2 * GB, "age_days": 40}])
    [rec] = recs_of(s, "abort_uploads")
    assert rec.payload["rule"]["AbortIncompleteMultipartUpload"] == {"DaysAfterInitiation": 7}
    assert rec.saving_bytes == 2 * GB
    covered = scan(uploads=s.uploads, rules=[rec.payload["rule"]])
    assert has_abort_rule(covered.rules) and recs_of(covered, "abort_uploads") == []


def test_noncurrent_versions_move_to_glacier_ir_never_expire():
    nc = [{"key": "db", "size": 2 * GB, "storage_class": "STANDARD", "noncurrent_days": d} for d in (5, 40, 90)]
    [rec] = recs_of(scan(versioning="Enabled", noncurrent=nc), "noncurrent")
    rule = rec.payload["rule"]
    assert "NoncurrentVersionExpiration" not in rule
    assert rule["NoncurrentVersionTransitions"] == [{"NoncurrentDays": 30, "StorageClass": "GLACIER_IR"}]
    assert rec.payload["objects_moved"] == 2
    assert recs_of(scan(versioning="", noncurrent=nc), "noncurrent") == []  # unversioned: nothing to do


def test_duplicates_by_etag_and_size_with_versioning_aware_saving():
    objects = [obj("a/1.bin", etag='"x"'), obj("a/copy/1.bin", etag='"x"'), obj("a/2.bin", etag='"y"')]
    plain = recs_of(scan(objects), "duplicates")[0]
    versioned = recs_of(scan(objects, versioning="Enabled"), "duplicates")[0]
    assert plain.saving_bytes == 50 * MB
    # In a versioned bucket the removed copy lingers as a noncurrent version.
    assert versioned.monthly_saving_usd < plain.monthly_saving_usd
    assert "delete marker" in versioned.reason and TRASH_PREFIX in plain.reason


def test_each_object_counted_once_across_recommendations():
    objects = [
        obj("media/a.jpg", size=10 * MB, age=300, etag='"same"'),
        obj("media/b.jpg", size=10 * MB, age=300, etag='"same"'),   # duplicate copy
        obj("media/photo.jpg", size=8 * MB, age=300),               # compression candidate
        obj("media/video.mp4", size=500 * MB, age=300),             # only tiering applies
    ]
    recs, groups, compress = S3Engine().analyze(scan(objects))
    tier = next(r for r in recs if r.type == "tiering")
    assert tier.payload["objects_moved"] == 2  # a.jpg (kept copy) + video; not b.jpg or photo.jpg
    assert set(compress) == {"media/photo.jpg"} and set(groups) == {"media/a.jpg", "media/b.jpg"}


def test_trash_prefix_is_ignored_and_glacier_objects_not_deduplicated():
    objects = [obj(f"{TRASH_PREFIX}x/a.bin", etag='"t"'), obj("a.bin", etag='"t"'),
               obj("g1", cls="GLACIER", etag='"g"'), obj("g2", cls="GLACIER", etag='"g"')]
    _, groups, _ = S3Engine().analyze(scan(objects))
    assert groups == {}


def test_monthly_cost_uses_class_prices():
    s = scan([obj("a", size=GB, cls="STANDARD"), obj("b", size=GB, cls="DEEP_ARCHIVE")])
    assert abs(S3Engine().monthly_cost(s) - (0.023 + 0.00099)) < 1e-3


def test_merge_rule_keeps_other_rules_and_replaces_same_id():
    mine = {"ID": "user-rule", "Status": "Enabled", "Filter": {"Prefix": "tmp/"}, "Expiration": {"Days": 1}}
    old = {"ID": "cloudclean-x", "Status": "Enabled", "Filter": {"Prefix": ""}}
    new = {"ID": "cloudclean-x", "Status": "Enabled", "Filter": {"Prefix": "logs/"}}
    merged, replaced = merge_rule([mine, old], new)
    assert merged == [mine, new] and replaced == old


def test_rule_prefix_formats():
    assert rule_prefix({"Filter": {"Prefix": "a/"}}) == "a/"
    assert rule_prefix({"Prefix": "legacy/"}) == "legacy/"
    assert rule_prefix({"Filter": {}}) == ""
    assert rule_prefix({"Filter": {"Tag": {"Key": "k", "Value": "v"}}}) is None
    tagged = {"ID": "t", "Status": "Enabled", "Filter": {"Tag": {"Key": "k", "Value": "v"}}, "Transitions": [{}]}
    assert not covered_by_transition([tagged], "anything")
