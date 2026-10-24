"""Rule-based savings engine for AWS S3 — the S3 counterpart of
app/recommendations/engine.py. Pure functions over scan data, no AWS calls.

How CloudClean's Drive ideas map onto S3:
  Drive                      S3
  ------------------------   ------------------------------------------------
  inactive / archive (ZIP)   storage-class tiering via lifecycle rules
                             (Standard -> Standard-IA -> Glacier IR / Deep Archive)
  duplicates (checksum)      duplicates by ETag + size
  compression                same image/PDF compression, object rewritten in place
  Trash (30 days)            versioned bucket: delete marker; otherwise a
                             cloudclean-trash/ prefix that expires after 30 days
  (no Drive equivalent)      abandoned multipart uploads, piles of noncurrent versions

Savings are in dollars per month because in S3 the same bytes cost up to
23x less depending on their storage class. Every figure is computed from
backend/data/s3_pricing.json and every recommendation's reason shows its
numbers, including one-time transition costs and the break-even point.

Limits stated plainly: S3 listings give LastModified, not last-read time, so
"not modified in 90 days" is used as the inactivity signal. Real access
patterns need S3 Storage Lens or server access logs (or Intelligent-Tiering,
which measures them itself).
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache

from app.analyzers.compression_potential import estimate as estimate_compression
from app.core.config import DATA_DIR

GB = 1024 ** 3
MIN_TIER_BYTES = 128 * 1024  # S3 lifecycle doesn't transition smaller objects by default
TRASH_PREFIX = "cloudclean-trash/"
TRASH_RULE_ID = "cloudclean-trash-expiry"
TRASH_DAYS = 30

TIERABLE = {"STANDARD", "REDUCED_REDUNDANCY"}
INSTANT_ACCESS = {"STANDARD", "REDUCED_REDUNDANCY", "STANDARD_IA", "ONEZONE_IA", "INTELLIGENT_TIERING"}
NONCURRENT_TIERABLE = INSTANT_ACCESS

# Lifecycle plans: (days since last modified, target class). The S3 rule uses
# the same days, so the estimate covers exactly what the rule will move.
TIER_PLANS = {
    "standard": [(30, "STANDARD_IA"), (90, "GLACIER_IR")],
    # Backups/archives are rarely read and can wait hours for a restore.
    "archival": [(30, "GLACIER_IR"), (180, "DEEP_ARCHIVE")],
}
ARCHIVAL_PREFIX = re.compile(r"backup|archive|snapshot|dump|export|old", re.I)
NONCURRENT_DAYS = 30
NONCURRENT_TARGET = "GLACIER_IR"
ABORT_UPLOAD_DAYS = 7

_COMPRESS_EXT = {".jpg": "images", ".jpeg": "images", ".png": "images", ".webp": "images", ".pdf": "pdf"}
COMPRESS_MIN_BYTES = 1024 * 1024


@lru_cache
def load_pricing() -> dict:
    with open(DATA_DIR / "s3_pricing.json") as f:
        return json.load(f)


class Pricing:
    def __init__(self, data: dict | None = None):
        self.data = data or load_pricing()

    def storage(self, cls: str) -> float:
        prices = self.data["storage_per_gb_month"]
        return prices.get(cls, prices["STANDARD"])

    def transition(self, cls: str) -> float:
        return self.data["transition_per_1000_requests"].get(cls, 0.0) / 1000

    def retrieval(self, cls: str) -> float:
        return self.data["retrieval_per_gb"].get(cls, 0.0)

    def min_days(self, cls: str) -> int:
        return self.data["min_storage_days"].get(cls, 0)

    def monthly(self, size_bytes: int, cls: str) -> float:
        return size_bytes / GB * self.storage(cls)


@dataclass
class BucketScan:
    name: str
    region: str
    versioning: str  # "" | Enabled | Suspended
    rules: list[dict]
    objects: list[dict]  # current versions: key, size, storage_class, age_days, etag
    noncurrent: list[dict] = field(default_factory=list)  # key, size, storage_class, noncurrent_days
    uploads: list[dict] = field(default_factory=list)  # key, size, age_days
    truncated: bool = False

    @property
    def versioned(self) -> bool:
        return self.versioning in ("Enabled", "Suspended")


@dataclass
class S3Rec:
    type: str
    action: str
    title: str
    reason: str
    saving_bytes: int
    monthly_saving_usd: float
    one_time_cost_usd: float
    risk: str
    confidence: float
    payload: dict = field(default_factory=dict)


# ----------------------------------------------------------------- lifecycle helpers

def rule_prefix(rule: dict) -> str | None:
    """The key prefix a lifecycle rule applies to, or None when its filter
    can't be evaluated from a listing (tag / size filters)."""
    if "Filter" in rule:
        f = rule["Filter"] or {}
        if "Prefix" in f:
            return f["Prefix"]
        if "And" in f:
            return None if f["And"].get("Tags") else f["And"].get("Prefix", "")
        return "" if not f else None
    return rule.get("Prefix", "")


def _enabled(rule: dict) -> bool:
    return rule.get("Status") == "Enabled"


def has_abort_rule(rules: list[dict]) -> bool:
    return any(_enabled(r) and "AbortIncompleteMultipartUpload" in r and rule_prefix(r) == "" for r in rules)


def has_noncurrent_rule(rules: list[dict]) -> bool:
    return any(_enabled(r) and (r.get("NoncurrentVersionTransitions") or r.get("NoncurrentVersionTransition")
                                or r.get("NoncurrentVersionExpiration")) for r in rules)


def covered_by_transition(rules: list[dict], key: str) -> bool:
    for r in rules:
        prefix = rule_prefix(r)
        if _enabled(r) and prefix is not None and key.startswith(prefix) and (r.get("Transitions") or r.get("Expiration")):
            return True
    return False


def merge_rule(rules: list[dict], new_rule: dict) -> tuple[list[dict], dict | None]:
    """Existing rules plus new_rule (replacing a rule with the same ID).
    PutBucketLifecycleConfiguration replaces the WHOLE configuration, so
    CloudClean always writes back every rule it didn't create untouched.
    Returns (merged rules, the rule it replaced or None)."""
    replaced = next((r for r in rules if r.get("ID") == new_rule["ID"]), None)
    return [r for r in rules if r.get("ID") != new_rule["ID"]] + [new_rule], replaced


def _slug(prefix: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", prefix.lower()).strip("-")[:60] or "all"


def top_prefix(key: str) -> str:
    return key.split("/", 1)[0] + "/" if "/" in key else ""


# ----------------------------------------------------------------- engine

class S3Engine:
    def __init__(self, pricing: Pricing | None = None, min_saving_percent: float = 10.0):
        self.p = pricing or Pricing()
        self.min_saving_ratio = min_saving_percent / 100.0

    # -- cost
    def monthly_cost(self, scan: BucketScan) -> float:
        d = self.p.data
        cost = sum(self.p.monthly(o["size"], o["storage_class"]) for o in scan.objects)
        cost += sum(self.p.monthly(v["size"], v["storage_class"]) for v in scan.noncurrent)
        cost += sum(self.p.monthly(u["size"], "STANDARD") for u in scan.uploads)
        everything = scan.objects + scan.noncurrent
        glacier_objects = sum(1 for o in everything if o["storage_class"] in ("GLACIER", "DEEP_ARCHIVE"))
        # Each archived object also bills ~40 KB of index metadata.
        cost += glacier_objects * d["glacier_overhead_kb_per_object"] * 1024 / GB * self.p.storage("GLACIER")
        it_objects = sum(1 for o in everything if o["storage_class"] == "INTELLIGENT_TIERING" and o["size"] >= MIN_TIER_BYTES)
        cost += it_objects / 1000 * d["intelligent_tiering_monitoring_per_1000_objects"]
        return round(cost, 4)

    # -- recommendations
    def analyze(self, scan: BucketScan) -> tuple[list[S3Rec], dict[str, int], dict[str, int]]:
        """Returns (recommendations, duplicate group id by key, compression
        saving estimate by key)."""
        objects = [o for o in scan.objects if not o["key"].startswith(TRASH_PREFIX)]
        recs: list[S3Rec] = []
        for rec in (self._abort_uploads(scan), self._noncurrent(scan)):
            if rec:
                recs.append(rec)

        # Each object's bytes count toward at most one saving, in the order
        # duplicate removal > compression > tiering, so savings can be summed.
        groups = self.duplicate_groups(objects)
        dup_rec = self._duplicates(scan, objects, groups)
        if dup_rec:
            recs.append(dup_rec)

        compress = self.compression_candidates(objects, groups)
        comp_rec = self._compression(scan, objects, compress)
        if comp_rec:
            recs.append(comp_rec)

        counted = set(compress) | removable_duplicate_keys(objects, groups)
        recs.extend(self._tiering(scan, objects, exclude=counted))

        recs.sort(key=lambda r: r.monthly_saving_usd, reverse=True)
        return recs, groups, compress

    def _abort_uploads(self, scan: BucketScan) -> S3Rec | None:
        if not scan.uploads or has_abort_rule(scan.rules):
            return None
        size = sum(u["size"] for u in scan.uploads)
        stale = sum(1 for u in scan.uploads if u["age_days"] >= ABORT_UPLOAD_DAYS)
        monthly = self.p.monthly(size, "STANDARD")
        rule = {"ID": "cloudclean-abort-incomplete-uploads", "Status": "Enabled", "Filter": {"Prefix": ""},
                "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": ABORT_UPLOAD_DAYS}}
        return S3Rec(
            type="abort_uploads", action="apply_lifecycle",
            title=f"Clean up {len(scan.uploads)} unfinished uploads in {scan.name}",
            reason=(
                f"{len(scan.uploads)} multipart uploads were started but never completed ({stale} are older than "
                f"{ABORT_UPLOAD_DAYS} days). Their parts take {_gb(size)} and are billed ({_usd(monthly)}/month), "
                f"but they don't appear as objects in the console. A lifecycle rule tells S3 to cancel uploads "
                f"still unfinished {ABORT_UPLOAD_DAYS} days after they start. No completed object is affected."
            ),
            saving_bytes=size, monthly_saving_usd=round(monthly, 6), one_time_cost_usd=0.0,
            risk="low", confidence=0.95, payload={"rule": rule},
        )

    def _noncurrent(self, scan: BucketScan) -> S3Rec | None:
        if not scan.versioned or not scan.noncurrent or has_noncurrent_rule(scan.rules):
            return None
        movable = [v for v in scan.noncurrent if v["storage_class"] in NONCURRENT_TIERABLE and v["size"] >= MIN_TIER_BYTES]
        due = [v for v in movable if v["noncurrent_days"] >= NONCURRENT_DAYS]
        monthly = sum(self.p.monthly(v["size"], v["storage_class"]) - self.p.monthly(v["size"], NONCURRENT_TARGET) for v in due)
        if monthly <= 0:
            return None
        total = sum(v["size"] for v in scan.noncurrent)
        one_time = len(due) * self.p.transition(NONCURRENT_TARGET)
        rule = {"ID": "cloudclean-noncurrent-versions", "Status": "Enabled", "Filter": {"Prefix": ""},
                "NoncurrentVersionTransitions": [{"NoncurrentDays": NONCURRENT_DAYS, "StorageClass": NONCURRENT_TARGET}]}
        return S3Rec(
            type="noncurrent", action="apply_lifecycle",
            title=f"Move {len(scan.noncurrent)} old versions in {scan.name} to Glacier Instant Retrieval",
            reason=(
                f"Versioning keeps every overwritten or deleted object as a noncurrent version: "
                f"{len(scan.noncurrent)} of them take {_gb(total)} here, all billed at their original class. "
                f"Moving versions that have been noncurrent for {NONCURRENT_DAYS}+ days to Glacier Instant Retrieval "
                f"keeps them restorable in milliseconds and saves {_usd(monthly)}/month now "
                f"(one-time transition cost {_usd(one_time)}). Expiring them instead would save everything, but that "
                f"permanently deletes old versions, so CloudClean leaves that choice to you in the S3 console."
            ),
            saving_bytes=0, monthly_saving_usd=round(monthly, 6), one_time_cost_usd=round(one_time, 6),
            risk="low", confidence=0.85,
            payload={"rule": rule, "objects_moved": len(due), "bytes_moved": sum(v["size"] for v in due)},
        )

    def _tiering(self, scan: BucketScan, objects: list[dict], exclude: set[str] = frozenset()) -> list[S3Rec]:
        by_prefix: dict[str, list[dict]] = defaultdict(list)
        has_prefixes = any("/" in o["key"] for o in objects)
        for o in objects:
            prefix = top_prefix(o["key"])
            if prefix == "" and has_prefixes:
                continue  # a bucket-wide rule would also hit every folder; root files are left alone
            by_prefix[prefix].append(o)

        recs = []
        for prefix, objs in sorted(by_prefix.items()):
            eligible = [o for o in objs if o["storage_class"] in TIERABLE and o["size"] >= MIN_TIER_BYTES
                        and o["key"] not in exclude and not covered_by_transition(scan.rules, o["key"])]
            if not eligible:
                continue
            plan_name = "archival" if ARCHIVAL_PREFIX.search(prefix or scan.name) else "standard"
            plan = TIER_PLANS[plan_name]
            moved_bytes: dict[str, int] = defaultdict(int)
            monthly = one_time = 0.0
            moved = 0
            for o in eligible:
                target = next((cls for days, cls in reversed(plan) if o["age_days"] >= days), None)
                if target is None:
                    continue
                moved += 1
                moved_bytes[target] += o["size"]
                monthly += self.p.monthly(o["size"], o["storage_class"]) - self.p.monthly(o["size"], target)
                one_time += self.p.transition(target)
            if monthly < 0.001:
                continue
            where = f"{scan.name}/{prefix}" if prefix else scan.name
            rule = {"ID": f"cloudclean-tier-{_slug(prefix)}", "Status": "Enabled", "Filter": {"Prefix": prefix},
                    "Transitions": [{"Days": d, "StorageClass": c} for d, c in plan]}
            steps = ", then ".join(f"{_class_name(c)} after {d} days" for d, c in plan)
            breakdown = "; ".join(f"{_gb(b)} to {_class_name(c)}" for c, b in moved_bytes.items())
            last_class = plan[-1][1]
            retrieval = (
                "Deep Archive objects need a restore request that takes up to 12 hours before they can be read"
                if last_class == "DEEP_ARCHIVE" else
                f"reading moved data costs ${self.p.retrieval(plan[0][1]):.2f}-${self.p.retrieval(last_class):.2f}/GB"
            )
            breakeven = one_time / monthly if monthly else 0
            recs.append(S3Rec(
                type="tiering", action="apply_lifecycle",
                title=f"Tier {where} by age ({plan_name} plan)",
                reason=(
                    f"{moved} of {len(objs)} objects in {where} haven't been modified for 30+ days but are still in "
                    f"S3 Standard. A lifecycle rule ({steps}) would move {breakdown} now, saving "
                    f"{_usd(monthly)}/month, and keeps tiering new objects as they age. One-time transition cost "
                    f"{_usd(one_time)} (pays for itself in {_months(breakeven)}). Trade-offs: {retrieval}, and data "
                    f"deleted early is billed for the class minimum ({self.p.min_days(plan[0][1])}-"
                    f"{self.p.min_days(last_class)} days). 'Not modified' isn't 'not read' — if this data is read "
                    f"often, use Intelligent-Tiering instead."
                ),
                saving_bytes=0, monthly_saving_usd=round(monthly, 6), one_time_cost_usd=round(one_time, 6),
                risk="medium", confidence=0.6,
                payload={"rule": rule, "prefix": prefix, "plan": plan_name, "objects_moved": moved,
                         "bytes_moved": sum(moved_bytes.values()), "bytes_by_target": dict(moved_bytes)},
            ))
        return recs

    @staticmethod
    def duplicate_groups(objects: list[dict]) -> dict[str, int]:
        """key -> group number for objects with identical ETag and size.
        Objects in Glacier/Deep Archive are skipped: they're cheap already and
        can't be copied without a restore."""
        by_sig: dict[tuple[str, int], list[str]] = defaultdict(list)
        for o in objects:
            if o["size"] > 0 and o.get("etag") and o["storage_class"] not in ("GLACIER", "DEEP_ARCHIVE"):
                by_sig[(o["etag"], o["size"])].append(o["key"])
        groups: dict[str, int] = {}
        for n, keys in enumerate(k for k in by_sig.values() if len(k) > 1):
            for key in keys:
                groups[key] = n + 1
        return groups

    def removal_saving(self, scan: BucketScan, size: int, cls: str) -> float:
        """Monthly saving from removing (or shrinking by) `size` bytes. In a
        versioned bucket the old data stays as a noncurrent version, so the
        saving is only the gap to Glacier IR (where CloudClean's noncurrent
        rule puts it), not the full price."""
        if scan.versioned:
            return self.p.monthly(size, cls) - self.p.monthly(size, NONCURRENT_TARGET)
        return self.p.monthly(size, cls)

    def _duplicates(self, scan: BucketScan, objects: list[dict], groups: dict[str, int]) -> S3Rec | None:
        if not groups:
            return None
        members: dict[int, list[dict]] = defaultdict(list)
        by_key = {o["key"]: o for o in objects}
        for key, g in groups.items():
            members[g].append(by_key[key])
        removable_bytes, monthly = 0, 0.0
        for objs in members.values():
            keep = default_keep(objs)
            for o in objs:
                if o is not keep:
                    removable_bytes += o["size"]
                    monthly += self.removal_saving(scan, o["size"], o["storage_class"])
        how = ("Removing a copy adds a delete marker (S3 keeps the data as a noncurrent version, so it stays "
               "restorable)" if scan.versioning == "Enabled" else
               f"Removing a copy moves it to {TRASH_PREFIX}, which S3 empties after {TRASH_DAYS} days — restore "
               f"it from History until then")
        return S3Rec(
            type="duplicates", action="review_duplicates",
            title=f"{len(members)} groups of duplicate objects in {scan.name}",
            reason=(
                f"{len(groups)} objects in {len(members)} groups have identical content (same ETag and size). "
                f"Keeping one per group frees {_gb(removable_bytes)}, {_usd(monthly)}/month. {how}. Check that no "
                f"application or link still uses the copies' keys before removing them."
            ),
            saving_bytes=removable_bytes, monthly_saving_usd=round(monthly, 6), one_time_cost_usd=0.0,
            risk="medium", confidence=0.9, payload={"groups": len(members)},
        )

    def compression_candidates(self, objects: list[dict], groups: dict[str, int]) -> dict[str, int]:
        out = {}
        for o in objects:
            ext = "." + o["key"].rsplit(".", 1)[-1].lower() if "." in o["key"].rsplit("/", 1)[-1] else ""
            category = _COMPRESS_EXT.get(ext)
            if (category is None or o["key"] in groups or o["size"] < COMPRESS_MIN_BYTES
                    or o["storage_class"] not in INSTANT_ACCESS):
                continue
            est = estimate_compression(category, ext, o["size"])
            if est.compressible and est.estimated_ratio >= self.min_saving_ratio:
                out[o["key"]] = int(o["size"] * est.estimated_ratio)
        return out

    def _compression(self, scan: BucketScan, objects: list[dict], candidates: dict[str, int]) -> S3Rec | None:
        if not candidates:
            return None
        by_key = {o["key"]: o for o in objects}
        saving = sum(candidates.values())
        monthly = sum(self.removal_saving(scan, s, by_key[k]["storage_class"]) for k, s in candidates.items())
        return S3Rec(
            type="compress", action="review_compression",
            title=f"Compress {len(candidates)} images/PDFs in {scan.name}",
            reason=(
                f"{len(candidates)} JPEG/PNG/WebP/PDF objects of 1 MB or more could shrink by about {_gb(saving)} "
                f"({_usd(monthly)}/month) by re-encoding them in the same format, the same way CloudClean "
                f"compresses Drive files. Each is rewritten under the same key; "
                + ("the original stays as a noncurrent version." if scan.versioning == "Enabled"
                   else f"the original is kept in {TRASH_PREFIX} for {TRASH_DAYS} days so it can be restored.")
            ),
            saving_bytes=saving, monthly_saving_usd=round(monthly, 6), one_time_cost_usd=0.0,
            risk="medium", confidence=0.6, payload={"objects": len(candidates)},
        )


def removable_duplicate_keys(objects: list[dict], groups: dict[str, int]) -> set[str]:
    """Keys of the copies that would be removed (every group member but the default keep)."""
    members: dict[int, list[dict]] = defaultdict(list)
    for o in objects:
        if o["key"] in groups:
            members[groups[o["key"]]].append(o)
    return {o["key"] for objs in members.values() for o in objs if o is not default_keep(objs)}


def default_keep(objs: list[dict]) -> dict:
    """The copy to keep by default: shortest key (usually the original
    path), then the oldest. The user can pick another."""
    return min(objs, key=lambda o: (len(o["key"]), -o.get("age_days", 0), o["key"]))


def _gb(size: int) -> str:
    if size >= GB:
        return f"{size / GB:.1f} GB"
    return f"{size / 1024 ** 2:.0f} MB"


def _usd(amount: float) -> str:
    return "under $0.01" if 0 < amount < 0.01 else f"~${amount:.2f}"


def _months(m: float) -> str:
    if m < 1 / 30:
        return "under a day"
    if m < 1:
        return f"about {max(1, round(m * 30))} days"
    return f"about {m:.1f} months"


_CLASS_NAMES = {
    "STANDARD": "Standard", "STANDARD_IA": "Standard-IA", "ONEZONE_IA": "One Zone-IA",
    "INTELLIGENT_TIERING": "Intelligent-Tiering", "GLACIER_IR": "Glacier Instant Retrieval",
    "GLACIER": "Glacier Flexible Retrieval", "DEEP_ARCHIVE": "Glacier Deep Archive",
    "REDUCED_REDUNDANCY": "Reduced Redundancy",
}


def _class_name(cls: str) -> str:
    return _CLASS_NAMES.get(cls, cls)
