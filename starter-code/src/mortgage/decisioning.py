from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


Recommendation = Literal["automated_offer", "underwriter_review", "validated_decline"]


@dataclass(frozen=True)
class PolicyAssessment:
    recommendation: Recommendation
    policy_version: str
    rule_results: dict[str, bool]
    reason_codes: tuple[str, ...] = ()
    explanation: str = ""


@dataclass(frozen=True)
class ValidationEvidence:
    policy_version: str
    authoritative_rule_results: dict[str, bool]
    approved_policy_rules: dict[str, str] = field(default_factory=dict)
    hard_rule_ids: frozenset[str] = frozenset()
    dual_control_reviewers: tuple[str, ...] = ()
    fair_lending_passed: bool = False
    fair_lending_audit_id: str | None = None
    approved_reason_descriptions: dict[str, str] = field(default_factory=dict)
    reason_code_rule_ids: dict[str, str] = field(default_factory=dict)
    approved_offer_conditions: tuple[str, ...] = ()


class DeterministicValidationGate:
    def validate(
        self, assessment: PolicyAssessment, evidence: ValidationEvidence
    ) -> dict[str, object]:
        issues: list[str] = []
        if not evidence.policy_version or assessment.policy_version != evidence.policy_version:
            issues.append("Policy version is missing or does not match the approved version")
        if assessment.rule_results != evidence.authoritative_rule_results:
            issues.append("Policy rule results do not match deterministic verification")
        if len(set(evidence.dual_control_reviewers)) < 2:
            issues.append("Two distinct reviewers must verify the rule results")
        if not evidence.fair_lending_passed or not evidence.fair_lending_audit_id:
            issues.append("A passed fair-lending check with an audit reference is required")
        if any(
            code not in evidence.approved_reason_descriptions
            for code in assessment.reason_codes
        ):
            issues.append("Policy assessment contains an unapproved reason code")

        if issues:
            return self._review(issues)

        if assessment.recommendation == "automated_offer":
            if not evidence.authoritative_rule_results or not all(
                evidence.authoritative_rule_results.values()
            ):
                return self._review(["Every verified offer threshold must pass"])
            return {
                "status": "automated_offer",
                "offer": {
                    "status": "draft",
                    "policy_version": evidence.policy_version,
                    "conditions": list(evidence.approved_offer_conditions),
                },
                "auto_explainer": "All configured thresholds passed deterministic validation; offer is a draft pending authorized release.",
            }

        if assessment.recommendation == "validated_decline":
            verified_breaches = {
                rule_id
                for rule_id in evidence.hard_rule_ids
                if evidence.authoritative_rule_results.get(rule_id) is False
            }
            decline_codes = [
                code
                for code in assessment.reason_codes
                if evidence.reason_code_rule_ids.get(code) in verified_breaches
            ]
            mapped_breaches = {
                evidence.reason_code_rule_ids[code]
                for code in assessment.reason_codes
                if code in evidence.reason_code_rule_ids
            }
            if not verified_breaches or not verified_breaches.issubset(mapped_breaches):
                return self._review(
                    ["Every verified hard-rule breach requires an approved reason code"]
                )
            descriptions = [
                evidence.approved_reason_descriptions[code] for code in decline_codes
            ]
            return {
                "status": "validated_decline",
                "validated_rule_breaches": sorted(verified_breaches),
                "adverse_action_notice": {
                    "status": "draft_requires_compliance_review",
                    "template": "adverse_action_notice_draft",
                    "reason_codes": decline_codes,
                    "reason_descriptions": descriptions,
                },
                "auto_explainer": "Verified hard-rule breach: " + "; ".join(descriptions),
            }

        descriptions = [
            evidence.approved_reason_descriptions.get(code, "Policy review required")
            for code in assessment.reason_codes
        ]
        return self._review(descriptions or [assessment.explanation or "Underwriter review required"])

    @staticmethod
    def _review(reasons: list[str]) -> dict[str, object]:
        return {
            "status": "underwriter_review",
            "auto_explainer": "; ".join(reasons),
            "outstanding_conditions": reasons,
        }
