"""Give one source-grounded reader edit first use of the existing length budget."""


def reader_first(record, report, output_kind):
    from services.deep_research.audience_rewrite import eligible
    from services.deep_research.answer_constraints import requested_character_limit
    from services.deep_research.request_context import effective_question
    limit=requested_character_limit(effective_question(record))
    return (type(record.get('audienceFirstContractVersion')) is int
            and record['audienceFirstContractVersion']==1
            and type(record.get('audienceRewriteContractVersion')) is int
            and record['audienceRewriteContractVersion']==9
            and type(limit) is int and 0<limit<=700
            and eligible(record,report,output_kind))
