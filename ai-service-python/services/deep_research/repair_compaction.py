"""Compact complete unverified repairs before the legacy per-row length filter."""
from copy import deepcopy

from services.deep_research.contracts import DeepResearchError, digest
from services.deep_research.scope_compaction import compact, enabled as scope_enabled


def enabled(record):
    return (type(record.get('repairCompactionContractVersion')) is int
            and record['repairCompactionContractVersion'] == 1 and scope_enabled(record)
            and record.get('state',{}).get('outputKind') in ('claim_verification','paper_comparison','direction_survey'))


def compact_repairs(report, revised, accepted, batch_state, question, invoke, parse, *,
                    evidence=(), output_kind='', presentation_version=0, saved=None, checkpoint=None,expression_version=2):
    packet = {**deepcopy(report),'claims':deepcopy(revised)}
    ids = {c['claimId'] for c in revised}
    audits = []
    for rows in (batch_state or {}).get('scopeExpressionAudit',{}).values():
        audits.extend(deepcopy(a) for a in rows if a.get('claimId') in ids)
    if type(expression_version) is not int or expression_version not in (2,3):
        raise ValueError('Invalid repair compaction expression version')
    identity = digest({'report':packet,'accepted':accepted,'audits':audits,'question':question,
                       **({'scopeExpressionContractVersion':3} if expression_version==3 else {}),
                       'evidence':evidence,'outputKind':output_kind,'presentationVersion':presentation_version})
    if saved is not None:
        if not isinstance(saved,dict) or saved.get('inputDigest') != identity:
            raise DeepResearchError('invalid_repair_compaction','保存的修订压缩输入不一致。')
        if saved.get('status') in ('completed','invalid'):
            return deepcopy(saved['claims'])
        if saved.get('status') != 'pending':
            raise DeepResearchError('invalid_repair_compaction','保存的修订压缩状态无效。')
    state = {'inputDigest':identity,'status':'pending'}
    if checkpoint:checkpoint(deepcopy(state))
    # Invoke is the normal tracked, budgeted dispatcher. Unknown responses
    # propagate; a confirmed invalid reply is checkpointed and never resent.
    result,new_audits = compact(packet,audits,question,invoke,parse,evidence=evidence,
        output_kind=output_kind,presentation_version=presentation_version,fixed_claims=accepted,
        **({'expression_version':3} if expression_version==3 else {}))
    state.update(status='completed' if result is not None else 'invalid',
                 claims=result['claims'] if result is not None else [],
                 scopeExpressionAudit=new_audits if result is not None else [])
    if checkpoint:checkpoint(deepcopy(state))
    return deepcopy(state['claims'])
