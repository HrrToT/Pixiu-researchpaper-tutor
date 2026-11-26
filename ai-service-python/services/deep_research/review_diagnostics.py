"""Ground reviewer-added facts without approving either a claim or a reason."""
from copy import deepcopy
import hashlib
import json


class DiagnosticAudit(dict):
    """Server-created marker; a JSON model response cannot instantiate this type."""


def invalid(audit):
    return isinstance(audit, DiagnosticAudit) and bool(audit.get('errors'))


def enabled(record):
    return (type(record.get('reviewDiagnosticContractVersion')) is int
            and record['reviewDiagnosticContractVersion'] in (1, 2))


GUIDANCE = '''Reviewer diagnostic provenance:
Every returned row additionally requires diagnosticFacts (a list, [] when no source
fact is added to reason). Bind each positive source fact you add in reason, especially
replacement/default parameters, numerical corrections, version conventions and theorems:
{"statement":"exact contiguous words in reason","evidenceId":"own E ID",
 "path":["quote"],"excerpt":"exact contiguous original source words"}.
Use only that target's own actually supplied source fields: quote, sourceContext,
sourceContext.before or sourceContext.after. Source metadata, another target's sources,
memory and the questioned claim itself cannot prove a correction. Bind the actual
statement and its necessary context; numerical coincidence is not semantic support.
Each new number not merely repeated from the target must occur in both the bound
statement and its own original excerpt. Do not invent a correction when extraction
is unreadable. State the precise unresolved part instead. These bindings cannot
override a failed decision or any other audit; the server checks them independently.
'''


def bind(verdict, claim, evidence, reverse=None, *, source_parameter_ids=False,target_structure=False,
         revision_row_counts=False):
    if type(target_structure) is not bool:raise ValueError('Invalid target structure diagnostic policy')
    if type(source_parameter_ids) is not bool:raise ValueError('Invalid diagnostic parameter identity policy')
    if type(revision_row_counts) is not bool:raise ValueError('Invalid revision row count policy')
    from services.deep_research.audit_source_fields import resolve
    from services.deep_research.verification import _measurement_numbers, normalize_quote
    result = deepcopy(verdict)
    reason = result.get('reason', '')
    facts = result.get('diagnosticFacts')
    errors = []
    if not isinstance(reason,str) or not reason.strip():
        errors.append('diagnostic_reason_invalid');reason=''
    covered_numbers = set()
    own = {e['evidenceId']: e for e in evidence if e.get('evidenceId') in claim.get('evidenceRefs', [])}
    numbers=lambda text:_measurement_numbers(text,word_counts=True)
    if source_parameter_ids:
        from services.deep_research.review_parameter_numbers import scanner
        numbers=scanner(own)
    review_numbers=numbers
    target_references=[]
    table_notes=[]
    reverse = reverse or {}
    if target_structure:
        from services.deep_research.review_target_structure import table_locator_view, view
        from services.deep_research.execution_materialization import verification_claim_view
        target_text=verification_claim_view(claim).get('text','')

        def scan_view(text):
            scanned, references = view(text, target_text)
            scanned, table_references = table_locator_view(scanned, claim, own, reverse)
            return scanned, [*references, *table_references]

        review_numbers = lambda text: numbers(scan_view(text)[0])
        _, target_references = scan_view(reason)
    if not isinstance(facts, list) or len(facts) > 16:
        errors.append('diagnostic_facts_missing_or_invalid')
        facts = []
    for fact in facts:
        if (not isinstance(fact, dict) or set(fact) != {'statement', 'evidenceId', 'path', 'excerpt'}
                or not isinstance(fact.get('statement'), str) or not fact['statement'].strip()
                or not isinstance(fact.get('excerpt'), str) or not fact['excerpt'].strip()
                or not isinstance(fact.get('evidenceId'), str)):
            errors.append('invalid_diagnostic_fact')
            continue
        if normalize_quote(fact['statement']) not in normalize_quote(reason):
            errors.append('diagnostic_statement_not_in_reason')
            continue
        resolved = resolve({'evidenceId': reverse.get(fact['evidenceId'], fact['evidenceId']),
                            'path': fact['path']}, own)
        if resolved is None or normalize_quote(fact['excerpt']) not in normalize_quote(resolved[1]):
            errors.append('diagnostic_source_not_bound')
            continue
        covered_numbers |= (review_numbers(fact['statement']) & numbers(fact['excerpt']))
        if revision_row_counts and fact['path'] == ['quote']:
            table_notes.append((resolved[0], fact['statement'], fact['excerpt']))
    target = claim.get('text', '') + ' ' + json.dumps(claim.get('conditions', {}), ensure_ascii=False)
    numeric_reason = reason
    if revision_row_counts:
        from services.deep_research.review_target_structure import revision_row_count_view
        numeric_reason, references = revision_row_count_view(reason, table_notes, numbers)
        target_references.extend(references)
    introduced = review_numbers(numeric_reason) - numbers(target)
    missing = introduced - covered_numbers
    if missing:
        errors.append('new_diagnostic_numbers_not_bound')
    audit = DiagnosticAudit({'version': 1, 'reportedStatus': result.get('status'),
             'reasonSha256': hashlib.sha256(reason.encode('utf8')).hexdigest(),
             'bindingCount': len(facts), 'newNumberCount': len(introduced),
             'unboundNewNumberCount': len(missing), 'errors': list(dict.fromkeys(errors))})
    if source_parameter_ids:audit['sourceParameterIdentityContractVersion']=1
    if target_structure:
        audit.update(reviewTargetStructureContractVersion=1,targetStructureReferences=target_references)
    if revision_row_counts:
        audit['reviewRevisionRowCountVersion'] = 1
    result['reviewDiagnosticAudit'] = audit
    if errors:
        # Preserve the raw model response in the immutable call journal, not in
        # repair instructions where its invented correction could be copied.
        result['status'] = 'failed'
        result['reason'] = '审核说明中的新增事实未绑定本条可见原文，本条尚未核验；不能据此改动具体参数。'
        result['executionState'] = 'received_invalid'
    return result
