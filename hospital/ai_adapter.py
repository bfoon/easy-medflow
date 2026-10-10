"""Disabled-by-default extension boundary for future authorized AI decision support.

A deployment should build a permissioned backend adapter that retrieves only relevant
patient context, records access, obtains required consent/legal basis, and sends only
minimum-necessary data to an approved configured service. Never send live PHI from
browser JavaScript. Outputs are unverified suggestions requiring licensed clinician review.
"""
from dataclasses import dataclass
@dataclass(frozen=True)
class ClinicalAISuggestion:
    summary: str
    evidence: list
    safety_flags: list
    requires_clinician_review: bool = True

class DisabledClinicalAI:
    def suggest(self, *, authorized_user, encounter_id):
        raise RuntimeError('Clinical AI adapter is not enabled or configured')

clinical_ai = DisabledClinicalAI()
