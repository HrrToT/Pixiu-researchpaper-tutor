"""Compact complete unverified repairs before the legacy per-row length filter."""
from copy import deepcopy

from services.deep_research.contracts import DeepResearchError, digest
from services.deep_research.scope_compaction import compact, enabled as scope_enabled


def enabled(record):
    return (type(record.get('repairCompactionContractVersion')) is int
            and record['repairCompactionContractVersion'] == 1 and scope_enabled(record)
            and record.get('state',{}).get('outputKind') in ('claim_verification','paper_comparison','direction_survey'))


def compact_repairs(report, revised, accepted, batch_state, question, invoke, parse, *,
                    evidence=(), output_kind='', presentation_version=0, saved=None, checkpoint=None,expression_version=2,
                    fixed_scope_first=False,invoke_fixed=None,explicit_edit_scope=False,compact_layout=False,joint_layout=False,authored_body=False,budget_guidance=False,selective_editing=False,prefer_fixed_scope=False,selective_fixed_edit=False,fixed_editor_profile=0):
    if (type(fixed_editor_profile) is not int or fixed_editor_profile not in (0,1)
            or fixed_editor_profile and not (selective_fixed_edit and prefer_fixed_scope and explicit_edit_scope)):
        raise ValueError('Invalid fixed editor reasoning profile')
    packet = {**deepcopy(report),'claims':deepcopy(revised)}
    ids = {c['claimId'] for c in revised}
    audits = []
    for rows in (batch_state or {}).get('scopeExpressionAudit',{}).values():
        audits.extend(deepcopy(a) for a in rows if a.get('claimId') in ids)
    if type(expression_version) is not int or expression_version not in (2,3,4,5):
        raise ValueError('Invalid repair compaction expression version')
    if type(authored_body) is not bool or authored_body and expression_version!=5:raise ValueError('Invalid authored repair compaction policy')
    if type(budget_guidance) is not bool:raise ValueError('Invalid repair compaction budget guidance policy')
    if type(selective_editing) is not bool:raise ValueError('Invalid selective repair compaction policy')
    if type(selective_fixed_edit) is not bool or selective_fixed_edit and not (selective_editing and prefer_fixed_scope and explicit_edit_scope):
        raise ValueError('Selective fixed editing requires explicit preferred scope policy')
    if type(prefer_fixed_scope) is not bool or prefer_fixed_scope and not selective_editing:
        raise ValueError('Fixed-scope repair preference requires selective editing')
    if type(joint_layout) is not bool:raise ValueError('Invalid joint repair layout policy')
    if type(compact_layout) is not bool:raise ValueError('Invalid compact repair layout policy')
    if type(explicit_edit_scope) is not bool:raise ValueError('Invalid explicit repair scope policy')
    if type(fixed_scope_first) is not bool:raise ValueError('Invalid fixed scope repair policy')
    identity = digest({**({'fixedScopeEditorReasoningContractVersion':fixed_editor_profile} if fixed_editor_profile else {}),**({'compactionEditingContractVersion':3 if selective_fixed_edit else 2 if prefer_fixed_scope else 1} if selective_editing else {}),**({'compactionBudgetContractVersion':1} if budget_guidance else {}),**({'authoredBodyContractVersion':1} if authored_body else {}),**({'jointLayoutVersion':1} if joint_layout else {}),**({'compactLayoutVersion':1} if compact_layout else {}),'report':packet,'accepted':accepted,'audits':audits,'question':question,
                       **({'scopeExpressionContractVersion':expression_version} if expression_version in (3,4,5) else {}),
                       **({'fixedScopeCompactionVersion':1} if fixed_scope_first else {}),
                       **({'explicitEditScopeVersion':1} if explicit_edit_scope else {}),
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
        **({'expression_version':expression_version} if expression_version in (3,4,5) else {}),
        **({'fixed_scope_first':True,'invoke_fixed':invoke_fixed} if fixed_scope_first else {}),
        explicit_edit_scope=explicit_edit_scope,compact_layout=compact_layout,joint_layout=joint_layout,
        **({'authored_body':True} if authored_body else {}),
        **({'budget_guidance':True} if budget_guidance else {}),
        **({'selective_editing':True} if selective_editing else {}),
        **({'prefer_fixed_scope':True} if prefer_fixed_scope else {}),
        **({'selective_fixed_edit':True} if selective_fixed_edit else {}))
    state.update(status='completed' if result is not None else 'invalid',
                 claims=result['claims'] if result is not None else [],
                 scopeExpressionAudit=new_audits if result is not None else [])
    if checkpoint:checkpoint(deepcopy(state))
    return deepcopy(state['claims'])
