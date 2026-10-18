"""Server-owned reasoning profile for bounded, short factual answers only."""

OPTION = '_short_factual_reasoning'
DIRECT_REPAIR_OPTION = '_short_factual_direct_repair'


def request_options(record, question, output_kind):
    from services.deep_research.answer_constraints import requested_character_limit
    limit = requested_character_limit(question)
    enabled = (type(record.get('factualReasoningContractVersion')) is int
               and record['factualReasoningContractVersion'] in (1,2)
               and output_kind in {'claim_verification', 'paper_comparison'}
               and type(limit) is int and 0 < limit <= 300)
    if not enabled:
        return {}
    return {OPTION:True,**({DIRECT_REPAIR_OPTION:True} if record['factualReasoningContractVersion']==2 else {})}
