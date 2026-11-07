"""Source-local notation and quantifiers for new factual review requests."""


def enabled(record):
    return (type(record.get('sourceVersionReviewContractVersion')) is int
            and record['sourceVersionReviewContractVersion']==1)


def eligible(claims):
    return bool(claims) and all(c.get('kind') in {'reported','inference'}
        and not c.get('executionSpec') and not c.get('designRole') for c in claims)


GUIDANCE = '''Source-local version and notation audit:
Use each cited source registry's exact workId/versionId/publicationIdentity and its
OWN quoted definitions, signs and parameter meanings. Familiar textbook or later
revision notation is not evidence. Algebraically different-looking expressions can
be equivalent under different local definitions; establish the source's definitions
before calling a formula wrong. Do not supply a replacement formula from memory.
If extracted mathematical glyphs or definitions are unreadable/missing, identify
that precise unresolved part; do not treat the familiar convention as the source.
Every positive source fact asserted in your reason (including a proposed correction
or existence of a theorem/experiment) needs own supplied evidence. Reasons are audit
diagnostics, not an extra channel for uncited paper facts or stronger conclusions.
Read exact quantifiers and assumptions: a theorem under stated conditions is not a
guarantee for every training/problem. Conversely, an evidence-bounded inference that
the cited premises do not establish a universal guarantee is not the assertion that
the authors never proved a theorem. Check the actual proposition and its kind;
do not invent an author-wide negative assertion or require a verbatim denial for
every valid bounded inference. Still reject unsupported premises, wrong signs,
unqualified bounds and invalid deductions. Never repair the claim and approve the
weaker replacement. All existing own-source, literal, scope and factual gates remain.
'''
