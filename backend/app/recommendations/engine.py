"""Rule-based, fully explainable recommendation engine. No LLM, no paid API —
every number here is a deterministic function of file metadata, documented
inline so a recommendation's "why" can always be traced back to a rule.

Each file's bytes are attributed to at most ONE saving, in priority order
duplicate removal > compression > archiving, so the recommendations'
estimated savings can be summed without double counting.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.analyzers.compression_potential import archive_ratio, estimate as estimate_compression
from app.analyzers.large_files import size_tier

MB = 1024 * 1024
ARCHIVE_MIN_FILE_BYTES = 512 * 1024


@dataclass
class Recommendation:
    scope: str  # "file" | "duplicate_group" | "batch"
    type: str  # compress | duplicate | archive | review
    action: str
    reason: str
    estimated_saving_bytes: int
    confidence: float
    risk: str
    file_id: str | None = None
    duplicate_group_id: int | None = None
    group_ref: object = None  # the analyzer DupGroup instance, for duplicate-type recs
    extra: dict = field(default_factory=dict)


DUPLICATE_CONFIDENCE = {"hash": 0.97, "size_name": 0.8, "name": 0.45}


class RecommendationEngine:
    def __init__(self, large_mb: int, very_large_mb: int, huge_mb: int, min_saving_percent: float,
                 inactive_days: int = 365, already_optimized_ids: set[str] | None = None):
        self.large_mb = large_mb
        self.very_large_mb = very_large_mb
        self.huge_mb = huge_mb
        self.min_saving_ratio = min_saving_percent / 100.0
        self.inactive_days = inactive_days
        # Files CloudClean already compressed. Re-compressing a JPEG again and
        # again compounds quality loss, so these are never suggested twice.
        self.already_optimized_ids = already_optimized_ids or set()

    def analyze_compression(self, f: dict) -> Recommendation | None:
        if f.get("is_google_workspace_file") or f["drive_id"] in self.already_optimized_ids:
            return None
        est = estimate_compression(f["category"], f["extension"], f["size_bytes"], **video_metadata(f))
        if not est.compressible:
            return None
        saving = int(f["size_bytes"] * est.estimated_ratio)
        if f["size_bytes"] == 0 or saving / f["size_bytes"] < self.min_saving_ratio:
            return None
        months_inactive = f.get("inactivity_days", 0) // 30
        reason = (
            f"Compression recommended because:\n"
            f"- File type: {f['extension'].lstrip('.').upper() or f['category']}\n"
            f"- Current size: {_fmt_mb(f['size_bytes'])}\n"
            f"- Estimated optimized size: {_fmt_mb(f['size_bytes'] - saving)}\n"
            f"- Estimated saving: {_fmt_mb(saving)}\n"
            f"- File has not been modified for {months_inactive} month(s)\n"
            f"- Compression confidence: {_confidence_label(est.confidence)}\n"
            f"- Method: {est.method} — {est.reason}"
        )
        return Recommendation(
            scope="file", type="compress", action="compress", reason=reason,
            estimated_saving_bytes=saving, confidence=est.confidence,
            risk="low", file_id=f["drive_id"], extra={"method": est.method},
        )

    def analyze_large_file(self, f: dict) -> Recommendation | None:
        tier = size_tier(f["size_bytes"], self.large_mb, self.very_large_mb, self.huge_mb)
        if tier is None:
            return None
        months = f.get("inactivity_days", 0) // 30
        reason = f"{tier.replace('_', ' ').title()} file ({_fmt_mb(f['size_bytes'])}), last modified {months} month(s) ago. Review whether it's still needed at this size."
        return Recommendation(
            scope="file", type="review", action="review", reason=reason,
            estimated_saving_bytes=0, confidence=0.3, risk="low", file_id=f["drive_id"],
            extra={"tier": tier},
        )

    def analyze_duplicate(self, group, files_by_id: dict[str, dict]) -> Recommendation:
        members = [files_by_id[i] for i in group.drive_ids if i in files_by_id]
        keep = files_by_id.get(group.recommended_keep_drive_id)
        confidence = DUPLICATE_CONFIDENCE.get(group.level, 0.5)
        names = ", ".join(m["name"] for m in members[:4])

        if group.review_only:
            reason = (
                f"{len(members)} files share a name but have different sizes, so their contents differ: {names}. "
                f"They look like versions of one document rather than copies. Review them before removing any — "
                f"CloudClean does not count them as recoverable space."
            )
            return Recommendation(
                scope="duplicate_group", type="duplicate", action="review_versions", reason=reason,
                estimated_saving_bytes=0, confidence=confidence, risk="high", group_ref=group,
            )

        removable = duplicate_removable_bytes(group, files_by_id)
        match = "identical content" if group.level == "hash" else "same size and name"
        reason = (
            f"{len(members)} files appear to be duplicates ({match}): {names}. "
            f"Recommended keep: {keep['name'] if keep else 'most recently modified copy'}. "
            f"Moving the rest to Trash would recover {_fmt_mb(removable)} once Drive's Trash is emptied."
        )
        return Recommendation(
            scope="duplicate_group", type="duplicate", action="review_duplicates", reason=reason,
            estimated_saving_bytes=removable, confidence=confidence, risk="medium", group_ref=group,
        )

    def analyze_archive_candidates(self, files: list[dict], exclude_ids: set[str] | None = None) -> Recommendation | None:
        exclude_ids = exclude_ids or set()
        candidates = [
            f for f in files
            if f["drive_id"] not in exclude_ids
            and not f.get("is_google_workspace_file")
            and f.get("inactivity_days", 0) >= self.inactive_days
            and f["size_bytes"] > ARCHIVE_MIN_FILE_BYTES
            and archive_ratio(f["category"], f["extension"]) > 0
        ]
        if not candidates:
            return None
        total = sum(f["size_bytes"] for f in candidates)
        saving = sum(int(f["size_bytes"] * archive_ratio(f["category"], f["extension"])) for f in candidates)
        if saving <= 0:
            return None
        reason = (
            f"{len(candidates)} files have not been modified in over {_fmt_days(self.inactive_days)} (potentially inactive) "
            f"and are in formats ZIP can still shrink. Bundling them into an archive could recover roughly "
            f"{_fmt_mb(saving)} of {_fmt_mb(total)} (estimated per file type; JPEG, video, audio and existing "
            f"archives are left out because zipping them saves next to nothing)."
        )
        return Recommendation(
            scope="batch", type="archive", action="archive", reason=reason,
            estimated_saving_bytes=saving, confidence=0.5, risk="low",
            extra={"file_ids": [f["drive_id"] for f in candidates], "total_bytes": total},
        )

    def analyze_gmail(self, messages: list[dict]) -> Recommendation | None:
        """Old, large emails. Review-only (no estimated saving): unlike a
        duplicate, an email is usually the only copy of its content."""
        old = [m for m in messages if m.get("inactivity_days", 0) >= self.inactive_days]
        if not old:
            return None
        total = sum(m["size_bytes"] for m in old)
        with_attachments = sum(1 for m in old if m.get("has_attachment"))
        reason = (
            f"{len(old)} large emails ({with_attachments} with attachments) received over "
            f"{_fmt_days(self.inactive_days)} ago take up {_fmt_mb(total)}. Gmail shares your 15 GB with Drive "
            f"and Photos. Review them on the Gmail page — save any attachment you still need to Drive first. "
            f"Trashed emails free their space once Gmail's Trash empties (automatically after 30 days)."
        )
        return Recommendation(
            scope="batch", type="gmail", action="review_gmail", reason=reason,
            estimated_saving_bytes=0, confidence=0.4, risk="medium",
            extra={"message_ids": [m["message_id"] for m in old], "total_bytes": total},
        )

    def generate_recommendations(self, files: list[dict], duplicate_groups: list) -> list[Recommendation]:
        files_by_id = {f["drive_id"]: f for f in files}
        recs: list[Recommendation] = []

        grouped_ids = {i for g in duplicate_groups for i in g.drive_ids}
        for group in duplicate_groups:
            recs.append(self.analyze_duplicate(group, files_by_id))

        covered = set(grouped_ids)
        for f in files:
            if f["drive_id"] in grouped_ids:
                continue  # already covered by a duplicate recommendation
            comp = self.analyze_compression(f)
            if comp:
                recs.append(comp)
                covered.add(f["drive_id"])
                continue
            large = self.analyze_large_file(f)
            if large:
                recs.append(large)

        archive = self.analyze_archive_candidates(files, exclude_ids=covered)
        if archive:
            recs.append(archive)

        recs.sort(key=lambda r: r.estimated_saving_bytes, reverse=True)
        return recs

    def calculate_optimization_score(self, files: list[dict], duplicate_groups: list, total_used_bytes: int) -> dict:
        """Transparent, rule-based score out of 100. Each factor is a
        documented weight applied to that factor's share of total storage —
        no ML, no black box. Uses the same one-saving-per-file attribution as
        generate_recommendations, so the score and the savings agree."""
        if total_used_bytes == 0:
            return {"score": 100, "summary": "No files analyzed yet.", "breakdown": {}}

        files_by_id = {f["drive_id"]: f for f in files}
        grouped_ids = {i for g in duplicate_groups for i in g.drive_ids}
        dup_bytes = sum(duplicate_removable_bytes(g, files_by_id) for g in duplicate_groups)

        compressible_bytes = 0
        for f in files:
            if f["drive_id"] in grouped_ids:
                continue
            rec = self.analyze_compression(f)
            if rec:
                compressible_bytes += rec.estimated_saving_bytes

        inactive_bytes = sum(f["size_bytes"] for f in files if f.get("inactivity_days", 0) >= self.inactive_days)
        large_bytes = sum(
            f["size_bytes"] for f in files
            if size_tier(f["size_bytes"], self.large_mb, self.very_large_mb, self.huge_mb)
        )

        def penalty(bytes_amount: int, weight: float, cap: float) -> float:
            share = min(1.0, bytes_amount / total_used_bytes)
            return round(min(cap, share * 100 * weight), 1)

        breakdown = {
            "duplicate_inefficiency": penalty(dup_bytes, 0.6, 30),
            "compression_opportunity": penalty(compressible_bytes, 0.5, 25),
            "inactive_data": penalty(inactive_bytes, 0.25, 20),
            "large_file_concentration": penalty(large_bytes, 0.2, 15),
        }
        score = max(0, round(100 - sum(breakdown.values())))
        if score >= 85:
            summary = "Your Drive is well optimized."
        elif score >= 60:
            summary = "Your Drive has some optimization opportunities."
        else:
            summary = "Your Drive has significant optimization opportunities."
        return {"score": score, "summary": summary, "breakdown": breakdown}


def video_metadata(f: dict) -> dict:
    """The estimate() keyword arguments for a file dict (zeros for non-video)."""
    return {"duration_ms": f.get("video_duration_ms") or 0, "width": f.get("video_width") or 0,
            "height": f.get("video_height") or 0}


def duplicate_removable_bytes(group, files_by_id: dict[str, dict]) -> int:
    """Bytes freed by trashing every member except the kept one. Zero for
    review-only (different-content) groups — those aren't redundant copies."""
    if group.review_only:
        return 0
    members = [files_by_id[i] for i in group.drive_ids if i in files_by_id]
    keep = files_by_id.get(group.recommended_keep_drive_id)
    return sum(m["size_bytes"] for m in members) - (keep["size_bytes"] if keep else 0)


def _fmt_mb(size_bytes: int) -> str:
    if size_bytes >= 1024 * MB:
        return f"{size_bytes / (1024 * MB):.2f} GB"
    return f"{size_bytes / MB:.1f} MB"


def _fmt_days(days: int) -> str:
    if days % 365 == 0:
        years = days // 365
        return f"{years} year" + ("s" if years > 1 else "")
    return f"{days} days"


def _confidence_label(c: float) -> str:
    if c >= 0.75:
        return "High"
    if c >= 0.45:
        return "Medium"
    return "Low"
