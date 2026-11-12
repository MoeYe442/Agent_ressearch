"""Citation checks are deterministic; semantic verdicts remain labelled model opinions."""
import hashlib
import json
from repolens.models import Claim
from repolens.agent import markdown_text


def result_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def collect_claims(results):
    claims, seen = [], set()
    for result in sorted(results, key=lambda value: value["id"]):
        for index, raw in enumerate(result.get("claims", [])):
            item = Claim.model_validate(raw)
            key = (item.text, tuple(sorted(item.evidence_ids)))
            if key in seen:
                continue
            seen.add(key)
            item.claim_id = f"{result['id']}:claim:{index}"
            item.review_status = "not_reviewed"
            claims.append(item)
    return claims


def validate_review(decision, claims, observed, evidence, snapshot_id):
    known = {claim.claim_id for claim in claims}
    seen = set()
    for item in decision.items:
        if item.claim_id not in known or item.claim_id in seen or not item.evidence_ids:
            raise ValueError("invalid_review_reference")
        if any(ref not in observed or not evidence.validate_evidence(ref, snapshot_id) for ref in item.evidence_ids):
            raise ValueError("invalid_review_reference")
        seen.add(item.claim_id)


def render_report(claims, limitations):
    lines = ["# RepoLens collaborative investigation", ""]
    for claim in claims:
        label = {"model_supported": "模型评审：支持", "model_contradicted": "模型评审：冲突", "model_insufficient": "模型评审：证据不足"}.get(claim.review_status, "尚未完成模型评审")
        citations = " ".join(f"[evidence:{ref}]" for ref in claim.evidence_ids)
        lines.append(f"- {markdown_text(label)} · {markdown_text(claim.text)} {citations}")
    lines.extend(["", "## Limitations", *[f"- {markdown_text(text)}" for text in limitations], "- Model review is not independent semantic proof."])
    return "\n".join(lines)
