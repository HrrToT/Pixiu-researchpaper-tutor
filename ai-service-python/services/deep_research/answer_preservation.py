"""New answers retain every generated point through a wording-only edit."""


def enabled(record):
    return (type(record.get('answerPreservationContractVersion')) is int
        and record['answerPreservationContractVersion']==1)


GUIDANCE='''For a short answer, reserve space for EVERY requested deliverable, including
reading/learning advice. Avoid a separate overview that repeats the full mechanism
inventory: explain the mechanisms once, then give the requested advice separately.
Keep optional bibliography identifiers (arXiv IDs, filenames, routing labels) out of
scientific prose; the application renders source identities and citations. This does
not permit changing a scientific number, dropping an essential condition or inventing
a reference. If compaction is necessary, shorten wording and repeated background,
not the requested answer scope. Each existing point keeps its ID, kind and own refs;
the normal factual and completeness reviewers still check the shortened answer.'''
