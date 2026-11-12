"""Separate a source report from reasoning before authoring a factual point."""


def enabled(record, kind):
    from services.deep_research.synthesis_instructions import enabled as consolidated
    return (type(record.get('premiseDraftContractVersion')) is int
            and record['premiseDraftContractVersion'] == 1 and consolidated(record, kind))


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
