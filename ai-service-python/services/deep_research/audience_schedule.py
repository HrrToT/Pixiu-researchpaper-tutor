"""Schedule reader wording against the existing publication budget."""


DIRECT_READER_GUIDANCE = """
Write the final beginner explanation directly from the cited text. For each requested
mechanism, explain the operation and what it acts on before naming it. When the source
describes distinct operations with different inputs or roles, keep the distinction in
plain words; a generic umbrella term or a list of names cannot replace their roles.
Keep source conditions next to the relevant operation. Omit repetition and optional
notation so the answer fits the visible limit, including headings and citation labels.
"""

READER_EVIDENCE_GAP_GUIDANCE = """
Write each supported mechanism directly. If a requested operation lacks support,
leave that aspect for the final coverage check. Do not append an assertion that
the paper or supplied excerpts omit an operation to a supported factual claim.
"""


def reader_first(record, report, output_kind):
    from services.deep_research.audience_rewrite import eligible
    from services.deep_research.answer_constraints import requested_character_limit
    from services.deep_research.request_context import effective_question
    limit=requested_character_limit(effective_question(record))
    return (type(record.get('audienceFirstContractVersion')) is int
            and record['audienceFirstContractVersion'] in (1, 2, 3)
            and type(record.get('audienceRewriteContractVersion')) is int
            and record['audienceRewriteContractVersion']==9
            and type(limit) is int and 0<limit<=700
            and eligible(record,report,output_kind))


def direct_reader_candidate(record, output_kind):
    from services.deep_research.audience_publication_budget import enabled as publication_budget
    from services.deep_research.audience_rewrite import beginner_requested
    from services.deep_research.request_context import effective_question

    return (type(record.get('audienceFirstContractVersion')) is int
            and record['audienceFirstContractVersion'] in (2, 3)
            and output_kind == 'claim_verification'
            and record.get('sourcePolicy') == {'mode': 'task_only'}
            and len(record.get('materials') or []) == 1
            and publication_budget(record, effective_question(record))
            and beginner_requested(record))


def keep_fitting_direct_draft(record, report, evidence, question, output_kind):
    from services.deep_research.audience_publication_budget import fits

    fulltext_ids = {row['evidenceId'] for row in evidence
                    if row.get('accessLevel') == 'fulltext'
                    and row.get('verification', {}).get('literal') == 'passed'}
    if not all(claim.get('detailLevel') == 'fulltext' and claim.get('evidenceRefs')
               and set(claim['evidenceRefs']) <= fulltext_ids for claim in report['claims']):
        return False
    return fits(report, evidence, question, {'outputKind': output_kind,
                'presentationVersion': record['reportPresentationContractVersion']})
