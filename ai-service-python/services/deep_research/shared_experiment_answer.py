"""Reuse fixed-request coverage/coherence on the actual compiled answer."""
from copy import deepcopy
import json

from services.deep_research.contracts import BudgetExhaustedError,DeepResearchError,digest
from services.deep_research.shared_experiment_result import compile_candidate


def slot(record):
    return 'sharedExperimentRevisionAnswerAudit' if 'sharedExperimentRevision' in record.get('state',{}) else 'sharedExperimentAnswerAudit'


def claim_for(candidate):
    return {'claimId':'shared_experiment_answer','kind':'proposal','text':candidate['markdown'],
            'conditions':{},'evidenceRefs':[c['evidenceId'] for c in candidate['citations']],
            'verification':'proposal'}


def _checked(record,candidate,audit):
    from services.deep_research.completion_criteria import revalidate_completion_audit
    from services.deep_research.display_metadata import answer_display_metadata,revalidate_display_metadata
    from services.deep_research.answer_coherence import revalidate
    claims=[claim_for(candidate)]; evidence=record['state'].get('evidence',[])
    metadata=answer_display_metadata(claims,evidence,task_sources=True,request_semantics=2,identification_locators=True)
    audit=revalidate_completion_audit(record['state'].get('plan',[]),claims,audit,display_metadata=metadata)
    audit=revalidate_display_metadata(audit,claims,evidence,task_sources=True,request_semantics=2,identification_locators=True)
    from services.deep_research.request_context import effective_question
    return revalidate(audit,effective_question(record),claims)


def validated_saved(record,input_data,aliases):
    candidate=compile_candidate(record,input_data,aliases)
    saved=record['state'].get(slot(record))
    if (not isinstance(saved,dict) or saved.get('status')!='checked'
            or saved.get('candidateDigest')!=candidate['candidateDigest']
            or digest(saved.get('audit'))!=saved.get('auditDigest')
            or not isinstance(saved.get('calls'),dict) or (saved.get('audit',{}).get('status')=='checked' and not saved['calls'])
            or any(key!=digest(c.get('request')) or c.get('status')!='received'
                or digest(c.get('response'))!=c.get('responseDigest') for key,c in saved.get('calls',{}).items())):
        raise DeepResearchError('invalid_shared_answer_audit','最终正文审核未完成或绑定已改变。')
    audit=_checked(record,candidate,deepcopy(saved['audit']))
    complete=audit.get('status')=='checked' and not audit.get('gaps') and audit.get('answerCoherence',{}).get('coherent') is True
    eligible=(audit.get('status')=='checked' and bool(audit.get('gaps'))
              and audit.get('answerCoherence',{}).get('status')=='checked'
              and not audit.get('invalidAspectObligations') and not audit.get('diagnosticErrors')
              and not any(g.get('auditStatus')=='binding_unresolved' for g in audit.get('gaps',[]) if isinstance(g,dict)))
    return {'candidate':candidate,'audit':audit,'complete':complete,
            'repairEligible':eligible,
            'certificateDigest':digest({'candidate':candidate['candidateDigest'],'audit':audit})}


def prepare(record,input_data,aliases,*,invoke,checkpoint):
    from services.deep_research.final_coverage import audit_final_answer
    from services.deep_research.experiment_planning import request_identity
    candidate=compile_candidate(record,input_data,aliases)
    saved=deepcopy(record['state'].get(slot(record)))
    if saved is None:
        saved={'version':1,'status':'pending','candidateDigest':candidate['candidateDigest'],
               'budgetAtPreparation':deepcopy(record['budget']),'calls':{}}
        checkpoint(deepcopy(saved))
    elif (type(saved.get('version')) is not int or saved['version']!=1 or saved.get('candidateDigest')!=candidate['candidateDigest']):
        raise DeepResearchError('invalid_shared_answer_audit','最终审核对象已改变，不能复用旧结果。')
    if saved['status']=='checked':
        view=deepcopy(record);view['state'][slot(record)]=saved
        return validated_saved(view,input_data,aliases)
    if saved['status']!='pending':raise DeepResearchError('invalid_shared_answer_audit','最终审核状态无效。')
    def tracked(rid,node,prompt,opts,**kwargs):
        req=request_identity(record,node,prompt,opts)
        if kwargs.get('counted_audit') is True:
            req={**req,'countedExperimentAnswerContractVersion':1}
        key=digest(req)
        call=saved['calls'].get(key)
        if call is None:
            call={'request':req,'status':'pending'};saved['calls'][key]=call;checkpoint(deepcopy(saved))
        elif call.get('request')!=req:raise DeepResearchError('invalid_shared_answer_audit','最终审核请求已改变。')
        if call['status']=='received':
            if digest(call.get('response'))!=call.get('responseDigest'):raise DeepResearchError('invalid_shared_answer_audit','最终审核原始响应已改变。')
            return deepcopy(call['response'])
        if call['status']!='pending':raise DeepResearchError('shared_answer_audit_stopped','未确认的审核调用不能自动重发。')
        try: response=invoke(rid,node,prompt,opts,**kwargs)
        except BudgetExhaustedError:
            # Reservation failed before generation. Keep the explicit budget
            # result without recording an unknown provider response.
            del saved['calls'][key]
            checkpoint(deepcopy(saved))
            raise
        except Exception:
            call['status']='invocation_failed';checkpoint(deepcopy(saved));raise
        call.update(status='received',response=deepcopy(response),responseDigest=digest(response));checkpoint(deepcopy(saved))
        return response
    from services.deep_research.request_context import effective_question
    from services.deep_research import shared_experiment_answer_packet as packet
    packet_options = {}
    if packet.enabled(record):
        from services.deep_research.shared_experiment_review import _generation
        from services.deep_research.tools import TrackedLLMInvoker
        proposal = _generation(record)['boundProposal']['proposal']
        packet_options['shared_experiment_phrases'] = packet.repeated_fields(proposal)
        if isinstance(invoke, TrackedLLMInvoker) and invoke.supports_counted_experiment_answer(record):
            packet_options['counted_experiment_audit'] = True
    audit=audit_final_answer(record['runId'],effective_question(record),record['state'].get('plan',[]),
        [claim_for(candidate)],record['state'].get('evidence',[]),tracked,json.loads,
        budget=saved['budgetAtPreparation'],request_contract=5,diagnostics=True,coherence=True,
        literal_dimensions=True,task_sources=True,request_semantics=2,identification_locators=True,
        shared_evidence_context=True,shared_decision_inputs=True,consolidated_instructions=True,
        literal_limits=True,binding_catalog=True,scoped_catalog=True,**packet_options)
    if any(c['status']=='invocation_failed' for c in saved['calls'].values()):
        raise DeepResearchError('shared_answer_audit_stopped','最终审核调用未确认，不能自动重发。')
    saved.update(status='checked',audit=audit,auditDigest=digest(audit));checkpoint(deepcopy(saved))
    view=deepcopy(record);view['state'][slot(record)]=saved
    return validated_saved(view,input_data,aliases)
