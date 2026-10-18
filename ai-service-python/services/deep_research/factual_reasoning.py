"""Server-owned reasoning profile for bounded factual answers/comparisons."""

OPTION = '_short_factual_reasoning'
DIRECT_REPAIR_OPTION = '_short_factual_direct_repair'
HIGH_SYNTHESIS_OPTION = '_short_factual_high_synthesis'


def request_options(record, question, output_kind):
    from services.deep_research.answer_constraints import requested_character_limit
    limit = requested_character_limit(question)
    version = record.get('factualReasoningContractVersion')
    if type(version) is not int or version not in (1,2,3,4):
        return {}
    multi_source = False
    if version == 4:
        snapshot = record.get('materialSnapshot') or {}
        state = record.get('state') or {}
        refs = snapshot.get('materialRefs', []) if isinstance(snapshot, dict) else []
        evidence = state.get('evidence', []) if isinstance(state, dict) else []
        works = {e.get('sourceWorkId') for e in evidence or []
                 if isinstance(e, dict) and isinstance(e.get('sourceWorkId'), str)}
        multi_source = len({r for r in refs or [] if isinstance(r, str) and r}) >= 2 or len(works) >= 2
    extended = (version == 4 and output_kind == 'paper_comparison' and multi_source)
    enabled = (type(version) is int and version in (1,2,3,4)
               and output_kind in {'claim_verification', 'paper_comparison'}
               and type(limit) is int and 0 < limit <= (700 if extended else 300))
    if not enabled:
        return {}
    return {OPTION:True,**({DIRECT_REPAIR_OPTION:True} if version in (2,3,4) else {}),
            **({HIGH_SYNTHESIS_OPTION:True} if version in (3,4) else {})}
