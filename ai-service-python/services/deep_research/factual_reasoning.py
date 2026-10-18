"""Server-owned reasoning profile for bounded, short factual answers only."""

OPTION = '_short_factual_reasoning'
DIRECT_REPAIR_OPTION = '_short_factual_direct_repair'
HIGH_SYNTHESIS_OPTION = '_short_factual_high_synthesis'


def request_options(record, question, output_kind):
    from services.deep_research.answer_constraints import requested_character_limit
    limit = requested_character_limit(question)
    enabled = (type(record.get('factualReasoningContractVersion')) is int
               and record['factualReasoningContractVersion'] in (1,2,3)
               and output_kind in {'claim_verification', 'paper_comparison'}
               and type(limit) is int and 0 < limit <= 300)
    if not enabled:
        return {}
    version=record['factualReasoningContractVersion']
    return {OPTION:True,**({DIRECT_REPAIR_OPTION:True} if version in (2,3) else {}),
            **({HIGH_SYNTHESIS_OPTION:True} if version==3 else {})}
