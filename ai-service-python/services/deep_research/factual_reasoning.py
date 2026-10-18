"""Server-owned reasoning profile for bounded, short factual answers only."""

OPTION = '_short_factual_reasoning'


def request_options(record, question, output_kind):
    from services.deep_research.answer_constraints import requested_character_limit
    limit = requested_character_limit(question)
    enabled = (type(record.get('factualReasoningContractVersion')) is int
               and record['factualReasoningContractVersion'] == 1
               and output_kind in {'claim_verification', 'paper_comparison'}
               and type(limit) is int and 0 < limit <= 300)
    return {OPTION: True} if enabled else {}
