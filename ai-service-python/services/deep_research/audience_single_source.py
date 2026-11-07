"""Source-first wording for a single answer point; no scientific approval."""


def enabled(record,report,protected_ids=()):
    return (type(record.get('audienceSingleSourceContractVersion')) is int
            and record['audienceSingleSourceContractVersion']==1
            and type(record.get('audienceRewriteContractVersion')) is int
            and record['audienceRewriteContractVersion']==9
            and isinstance(report.get('claims'),list) and len(report['claims'])==1
            and not protected_ids)


GUIDANCE = """There is one answer target, so the fixed requested points define its responsibility;
no draft topic hint is needed. Reconstruct the explanation from its own original sources.
For the stated reader, connect each necessary concept to a concrete meaning or action:
what it records, what changes, why, and how that affects the next operation, only where
requested. Naming a formula or statistical term is not its explanation. Use ordinary
words for a necessary quantity before naming it; preserve the source's distinctions
between different quantities or operations. Do not add unrelated definitions.
If a formula is explicitly requested, explain its symbols and operation in words; otherwise
use a verbal account of the requested relation when the supplied sources establish it.
Do not spend a short answer's space on optional algebra or abbreviations. Preserve the
actual source-version convention and conditional scope, without substituting textbook
memory. Explain the specific problem a correction addresses and its supported limits
when asked, without inventing examples, benefits, convergence guarantees or new facts.
Readability is a writing goal, not evidence of factual support. The normal independent
source, factual and completeness checks still apply to the complete replacement.
"""
