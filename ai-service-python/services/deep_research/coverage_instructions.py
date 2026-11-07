"""One fixed-check instruction set; input values and acceptance validators stay exact."""
import json


CORE = '''Factual support was checked separately. Audit ONLY completeness of the complete
accepted answer against the original question and EVERY fixed check. Related source
quotes, citations, obligationIds, field existence or keywords do not establish coverage.
Read points jointly; bind all relevant accepted fields. Never rewrite claims, reverse
factual verdicts, use rejected claims, or invent requirements from source detail.
Keep the planned responseType. Respect brevity while retaining requested parameters,
assumptions, applicability/activation, comparisons and limits. No unrequested experiments,
paper survey, implementation inventory or numerical threshold. Proposed protocols need
no measured results or reproduction of author settings unless actually requested/claimed;
existing data counts/splits/membership still need grounding where relevant.
For proposals, executionSpec retains every value in the exact app-generated trailing
rendering omitted from text; judge both plus unchanged prose/conditions for consistency.
Explanation needs actual inputs, operation and consequence, not names, purpose, benefits,
"X then Y" or equation restatement. For novices explain essential unfamiliar concepts
through ordinary actions. For feedback connect error/signal, updated parameter/state,
and later predictions when that path is established; "gradients flow" alone is partial.
Measurements must map EACH value to its entity, subgroup/aggregate, metric/direction and
relevant conditions in the answer itself. Address each requested paper and dimension.
A numerical series alone is not a qualified judgement. Explicit supported/partly supported/
not supported/cannot establish assessment needs no synonymous verdict label, but still
needs the assessed proposition, adequate reasoning and relevant evidence-bounded limits.
Distinguish reported results, applicable conditions and what remains unestablished;
one ablation failure or another experiment's settings cannot replace that distinction.
A relevant scoped uncertainty answer may suffice without universal guarantees or an
exhaustive setting inventory. Never demand author-wide absence, invent condition
differences or contradict a clear answer sentence by calling it absent. One field may
cover several checks only if its wording actually answers each. Sources may reveal
necessary missing conditions but cannot fill absent answer prose or add fixed check IDs.
Supporting research is auxiliary, not automatically required narration. Exemption cannot
waive requested facts, dependencies, controls/interventions, assumptions or evidence;
necessary unanswered work remains partial/missing. No rule here grants factual approval.
'''

OUTPUT = '''Return ONLY a JSON array, exactly one row per fixed obligationId, with every
fixed checkId exactly once. Ordinary row: {"obligationId":"ID","checks":[
{"checkId":"ID","status":"covered|partial|missing","bindings":[{"claimId":"accepted ID","field":"text"}],"reason":"actual coverage or specific unanswered part"}]}.
These are the exact keys. reason is 1-800 characters, not a paper-absence assertion
or repair command. covered needs sufficient content with valid bindings; partial binds
relevant existing content when present; missing has []. Bind text or nonempty conditions,
never source sentences. An absent/empty conditions object cannot be bound. Read the full
accepted answer before deciding its own relevant content is absent.
Only supporting_research may instead return exactly obligationId and notRequired:
{"reason":"specific reason >=12 characters","requestExcerpt":"exact original-question substring >=8 characters","bindings":[{"claimId":"ID","field":"text"}]}.
Independently justify why the actual deliverable already suffices. This never exempts
the original question or an answer_requirement, nor means a source fact was checked.
Output ordinary schema values/IDs, never input sharing references or catalog indices.
'''

ACCESS = '''Source access is server-rendered acquisition metadata, not methods/results or
proof of whole-paper reading. Only an explicit access-only obligation/check may bind
{"claimId":"accepted citing ID","field":"sourceAccessSummary"}. Its actual cited access
records and label must exist. Scientific/mixed checks still bind actual text/conditions;
an original question requesting BOTH science and access may jointly bind prose and the
label when both are needed. A response character limit is formatting, not a number to
repeat; requested measurements, object counts and table/equation IDs remain content.
Never invent access or put duplicate access declarations into scientific prose.
'''

CATALOG = '''The binding catalog lists ONLY existing available claim fields, not evidence
of completeness. Choose the minimum sufficient actual fields. For a scoped catalog,
each obligationId/checkId selects catalogs[catalogIndex] (zero-based); restore its exact
claim/field list. Sharing a list shares no access permission or scientific support.
Never invent, repair or expand field permissions. Output claimId/field, not catalogIndex.
'''

PROCESS = '''For processRequired=true checks, also return processLinks (other checks omit it).
covered needs at least one link: {"input":{"request":"short input-role substring"},
"operation":{"id":"bound accepted ID","field":"text","excerpt":"exact actual operation"},
"output":{"request":"different output-role substring"}}. This is a binding schema,
not source facts or a default answer. Each role may instead use {id,field,excerpt};
answer fields are text/conditions and IDs must be among THAT check's bound accepted
claims. Operation must bind actual answer prose, never the request. Input/output may
bind unambiguous literal requirement spans. All excerpts are exact contiguous strings.
Use short specific, semantically connected roles; input/output and same-field role spans
must not overlap. Never copy the whole question into both. Several own fields may jointly
explain the process; no need for one field to contain everything. Names, bare 'used for',
purpose or achieved benchmarks are not operations. A source quotation cannot fill an
omitted answer step. Unknown roles/operations stay partial/missing, processLinks=[];
do not invent steps, extra results or unrequested parameters. Matching excerpts do not
prove coverage: judge the actual semantic connection and EVERY requested part.
'''


def prompt(question,requirements,claims,metadata,evidence_marker, *, shared_inputs=False,
           task_sources=False,binding_catalog=None,scoped_catalog=False,coherence=False,
           process_explanations=False,distinct_roles=False,request_semantics=0,literal_limits=False):
    if type(literal_limits) is not bool:raise ValueError("Invalid literal limit policy")
    from services.deep_research.request_coverage import decision_inputs
    if not distinct_roles and process_explanations:
        # v4 permits overlapping request roles; only v5 requires disjoint spans.
        process=PROCESS.replace('input/output and same-field role spans\nmust not overlap. Never copy the whole question into both.',
            'same answer-field role spans must not overlap. Input/output request roles follow the active contract.')
    else:process=PROCESS
    result=('Audit the FINAL ACCEPTED ANSWER against the FIXED REQUEST CHECKLIST.\n'
        +decision_inputs(question,requirements,claims,metadata,shared_inputs=shared_inputs)
        +'Available evidence for detecting omissions, NOT inventing requirements: '+evidence_marker+'\n'
        +CORE+(OUTPUT.replace('These are the exact keys.',
            'These are the ordinary keys; limitation checks additionally require limitSpans as specified below.')
            if literal_limits else OUTPUT))
    if literal_limits:
        from services.deep_research.coverage_limits import GUIDANCE
        result+='\n'+GUIDANCE
    if task_sources or request_semantics==2:result+=ACCESS
    if binding_catalog is not None:
        result+=CATALOG+'\nAvailable answer bindings'+(' by check' if scoped_catalog else '')+': '+json.dumps(binding_catalog,ensure_ascii=False,separators=(',',':'))+'\n'
    if process_explanations and any(c.get('processRequired') for r in requirements for c in r['checks']):
        result+=process
    if coherence:
        from services.deep_research.answer_coherence import GUIDANCE
        result+=GUIDANCE
    return result
