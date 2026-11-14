"""Separate a source report from reasoning before authoring a factual point."""


def enabled(record, kind):
    from services.deep_research.synthesis_instructions import enabled as consolidated
    return (type(record.get('premiseDraftContractVersion')) is int
            and record['premiseDraftContractVersion'] in (1, 2) and consolidated(record, kind))


GUIDANCE = """Choose provenance before wording: reported is a source-reported proposition;
inference is a deduction from own cited premises. Do not append an inferred limit
as an author-reported fact. State the premises and logical connection. "These
premises do not imply P" is neither "the authors never proved P" nor "P is false";
never assert those stronger negatives or deny a supplied theorem without support.
For how/why, explain the actual change and precise problem addressed. Names/formulas
alone do not explain it. Ordinary source-grounded reasoning may use prose; do not
invent an empirical comparison for a mechanism explanation. An authored evidence-
comparison/generalization boundary still uses the existing boundary branch and checks.
Put a source condition BEFORE its consequence: "under C, X", not "X generally,
especially C". Neither the condition nor the inference label proves the consequence.
observedSettings may be empty: include only settings needed for the requested limit,
with each part of a compound value supported by THIS point's own evidenceRefs.
Another point's citations cannot verify them. Invent no baseline, result or subject
to populate boundary fields. Cover requested limits once, without repeating them as
an unsupported reported denial and a separate inventory. Keep distinct contributions
and necessary source distinctions, but omit optional algebra/settings/experiments.
Private metadata, kinds and templates grant no factual approval; all checks remain.
"""


PROVENANCE_UNITS = """Organize answer units by provenance BEFORE compressing them.
A source-reported mechanism and your deduction about its limits are different units.
Do not label a combined source report plus your deduction as reported. When both are
needed, use separate reported and inference claims within the existing claim limit;
keep each unit concise, with its OWN actual premises and obligationIds. Several
connected source-reported steps may share one reported unit. Do not split every
sentence, duplicate premises or create a second unit if no inference is requested.
A user prohibition constrains YOUR answer; it proves no paper-wide negative. Answer
an explicit scope question using the established mechanism's actual reach: what
particular source or calculation the correction changes, and what cannot be inferred
from those particular premises. Do not substitute an assertion about what the paper
never guarantees, never proves, never evaluates or never mentions.
For a deduction use kind=inference and explain its premises-to-conclusion connection.
Use the existing structured boundary branch for evidence-comparison/generalization
bounds where required; a direct mechanism explanation may use inference prose.
Choose type from the actual provenance, never to evade the existing branch, numerical,
scope or factual checks. An inference label does not make a deduction valid.
For a novice, first give a quantity's concrete meaning, then its necessary name.
Describe the actual operation that changes the quantity; list no optional notation.
All requested aspects, source-version conventions and conditional scope remain.
"""


def guidance(record):
    return GUIDANCE + ('\n' + PROVENANCE_UNITS
        if type(record.get('premiseDraftContractVersion')) is int
        and record['premiseDraftContractVersion'] == 2 else '')
