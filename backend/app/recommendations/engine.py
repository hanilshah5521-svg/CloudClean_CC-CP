"""Rule-based, fully explainable recommendation engine. No LLM, no paid API —
every number here is a deterministic function of file metadata, documented
inline so a recommendation's "why" can always be traced back to a rule.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.analyzers.compression_potential import estimate as estimate_compression
from app.analyzers.inactive import inactivity_bucket
from app.analyzers.large_files import size_tier

MB = 1024 * 1024


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
    def __init__(self, large_mb: int, very_large_mb: int, huge_mb: int, min_saving_percent: float):
        self.large_mb = large_mb
        self.very_large_mb = very_large_mb
        self.huge_mb = huge_mb
        self.min_saving_ratio = min_saving_percent / 100.0

    def analyze_compression(self, f: dict) -> Recommendation | None:
        if f.get("is_google_workspace_file"):
            return None
        est = estimate_compression(f["category"], f["extension"], f["size_bytes"])
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
        total = sum(m["size_bytes"] for m in members)
        keep = files_by_id.get(group.recommended_keep_drive_id)
        removable = total - (keep["size_bytes"] if keep else 0)
        confidence = DUPLICATE_CONFIDENCE.get(group.level, 0.5)
        names = ", ".join(m["name"] for m in members[:4])
        reason = (
            f"{len(members)} files appear to be duplicates ({group.level.replace('_', ' ')} match): {names}. "
            f"Recommended keep: {keep['name'] if keep else 'most recently modified copy'}. "
            f"Moving the rest to Trash would recover {_fmt_mb(removable)}."
        )
        return Recommendation(
            scope="duplicate_group", type="duplicate", action="review_duplicates", reason=reason,
            estimated_saving_bytes=removable, confidence=confidence, risk="medium", group_ref=group,
        )

    def analyze_archive_candidates(self, files: list[dict]) -> Recommendation | None:
        candidates = [
            f for f in files
            if not f.get("is_google_workspace_file")
            and f.get("inactivity_days", 0) >= 365
            and f["size_bytes"] > 512 * 1024
        ]
        if not candidates:
            return None
        total = sum(f["size_bytes"] for f in candidates)
        reason = (
            f"{len(candidates)} files have not been modified in over 1 year (potentially inactive). "
            f"Bundling them into a ZIP archive could recover roughly {_fmt_mb(int(total * 0.3))} "
            f"(assuming ~30% archive compression) while keeping the data intact."
        )
        return Recommendation(
            scope="batch", type="archive", action="archive", reason=reason,
            estimated_saving_bytes=int(total * 0.3), confidence=0.5, risk="low",
            extra={"file_ids": [f["drive_id"] for f in candidates], "total_bytes": total},
        )

    def generate_recommendations(self, files: list[dict], duplicate_groups: list) -> list[Recommendation]:
        files_by_id = {f["drive_id"]: f for f in files}
        recs: list[Recommendation] = []

        grouped_ids = {i for g in duplicate_groups for i in g.drive_ids}
        for group in duplicate_groups:
            recs.append(self.analyze_duplicate(group, files_by_id))

        for f in files:
            if f["drive_id"] in grouped_ids:
                continue  # already covered by a duplicate recommendation
            comp = self.analyze_compression(f)
            if comp:
                recs.append(comp)
                continue
            large = self.analyze_large_file(f)
            if large:
                recs.append(large)

        archive = self.analyze_archive_candidates(files)
        if archive:
            recs.append(archive)

        recs.sort(key=lambda r: r.estimated_saving_bytes, reverse=True)
        return recs

    def calculate_optimization_score(self, files: list[dict], duplicate_groups: list, total_used_bytes: int) -> dict:
        """Transparent, rule-based score out of 100. Each factor is a
        documented weight applied to that factor's share of total storage —
        no ML, no black box."""
        if total_used_bytes == 0:
            return {"score": 100, "summary": "No files analyzed yet.", "breakdown": {}}

        files_by_id = {f["drive_id"]: f for f in files}
        dup_bytes = 0
        for g in duplicate_groups:
            members = [files_by_id[i] for i in g.drive_ids if i in files_by_id]
            keep = files_by_id.get(g.recommended_keep_drive_id)
            dup_bytes += sum(m["size_bytes"] for m in members) - (keep["size_bytes"] if keep else 0)

        compressible_bytes = 0
        for f in files:
            est = estimate_compression(f["category"], f["extension"], f["size_bytes"])
            if est.compressible:
                compressible_bytes += int(f["size_bytes"] * est.estimated_ratio)

        inactive_bytes = sum(f["size_bytes"] for f in files if f.get("inactivity_days", 0) >= 365)
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


def _fmt_mb(size_bytes: int) -> str:
    if size_bytes >= 1024 * MB:
        return f"{size_bytes / (1024 * MB):.2f} GB"
    return f"{size_bytes / MB:.1f} MB"


def _confidence_label(c: float) -> str:
    if c >= 0.75:
        return "High"
    if c >= 0.45:
        return "Medium"
    return "Low"
