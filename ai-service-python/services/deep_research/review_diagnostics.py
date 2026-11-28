"""Ground reviewer-added facts without approving either a claim or a reason."""
from copy import deepcopy
import hashlib
import json
import re


_MIP_NERF_360 = re.compile(r'(?<![A-Za-z0-9_])Mip-NeRF\s*360(?![A-Za-z0-9_%％×倍]|\.\d)', re.I)
_CITED_PAPER_PAIR = re.compile(r'(?<![第零一二两三四五六七八九十百千万亿0-9.])两篇论文')
_NUMBERED_REFERENCE = re.compile(
    r'(?:文献|参考文献|\breference|\bcitation)\s*\[\s*([1-9][0-9]{0,3})\s*\]', re.I)
_BRACKETED_LABEL = re.compile(r'\[\s*([1-9][0-9]{0,3})\s*\]')
_QUALIFIED_SCENE_COUNT = re.compile(
    r'\b(zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)'
    r'(?:\s+(?:real[- ]world|large[- ]scale|synthetic|indoor|outdoor)){1,3}(?=\s+scenes?\b)', re.I)


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


def parameter_options(policy):
    return dict(
        source_parameter_ids=policy is True or policy in (2, 3, 4, 5, 6, 7),
        bound_benchmark_names=policy in (2, 3, 4, 5, 6, 7),
        alignment_words=policy in (3, 4, 5, 6, 7),
        explicit_condition_pairs=policy in (4, 5, 6, 7),
        interpolation_kernel_labels=policy in (5, 6, 7),
        bound_citation_labels=policy == 7,
    )


def bind(verdict, claim, evidence, reverse=None, *, source_parameter_ids=False,target_structure=False,
         revision_row_counts=False, bound_benchmark_names=False, alignment_words=False,
         explicit_condition_pairs=False, interpolation_kernel_labels=False, cited_paper_pair=False,
         bound_citation_labels=False):
    if type(target_structure) is not bool and not (type(target_structure) is int and target_structure == 2):
        raise ValueError('Invalid target structure diagnostic policy')
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
    cited_labels = set()
    numeric_reason = reason
    own = {e['evidenceId']: e for e in evidence if e.get('evidenceId') in claim.get('evidenceRefs', [])}
    numbers=lambda text:_measurement_numbers(text,word_counts=True)
    if source_parameter_ids:
        from services.deep_research.review_parameter_numbers import scanner
        numbers=scanner(own, alignment_words=alignment_words, explicit_condition_pairs=explicit_condition_pairs,
                        interpolation_kernel_labels=interpolation_kernel_labels)
    review_numbers=numbers
    target_references=[]
    table_notes=[]
    reverse = reverse or {}
    if target_structure:
        from services.deep_research.review_target_structure import table_locator_view, view
        from services.deep_research.execution_materialization import verification_claim_view
        target_text=verification_claim_view(claim).get('text','')

        def scan_view(text):
            scanned, references = view(text, target_text,
                                       named_pairs=target_structure == 2 and result.get('status') == 'passed')
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
        statement, excerpt = fact['statement'], fact['excerpt']
        if bound_citation_labels:
            labels = set(_NUMBERED_REFERENCE.findall(statement)) & set(_BRACKETED_LABEL.findall(excerpt))
            cited_labels.update(labels)
            statement = _NUMBERED_REFERENCE.sub(
                lambda m: '所引文献' if m.group(1) in labels else m.group(), statement)
            excerpt = _BRACKETED_LABEL.sub(lambda m: '' if m.group(1) in labels else m.group(), excerpt)
            excerpt = _QUALIFIED_SCENE_COUNT.sub(r'\1', excerpt)
        if bound_benchmark_names:
            cleaned = _MIP_NERF_360.sub('Mip-NeRF', statement)
            if _MIP_NERF_360.search(excerpt):
                numeric_reason = numeric_reason.replace(statement, cleaned)
            statement = cleaned
            excerpt = _MIP_NERF_360.sub('Mip-NeRF', excerpt)
        covered_numbers |= (review_numbers(statement) & numbers(excerpt))
        if revision_row_counts and fact['path'] == ['quote']:
            table_notes.append((resolved[0], fact['statement'], fact['excerpt']))
    target = claim.get('text', '') + ' ' + json.dumps(claim.get('conditions', {}), ensure_ascii=False)
    if revision_row_counts:
        from services.deep_research.review_target_structure import revision_row_count_view
        numeric_reason, references = revision_row_count_view(numeric_reason, table_notes, numbers)
        target_references.extend(references)
    if cited_paper_pair:
        numeric_reason = _CITED_PAPER_PAIR.sub('所引论文', numeric_reason)
    if cited_labels:
        numeric_reason = _NUMBERED_REFERENCE.sub(
            lambda m: '所引文献' if m.group(1) in cited_labels else m.group(), numeric_reason)
    introduced = review_numbers(numeric_reason) - numbers(target)
    missing = introduced - covered_numbers
    if missing:
        errors.append('new_diagnostic_numbers_not_bound')
    audit = DiagnosticAudit({'version': 1, 'reportedStatus': result.get('status'),
             'reasonSha256': hashlib.sha256(reason.encode('utf8')).hexdigest(),
             'bindingCount': len(facts), 'newNumberCount': len(introduced),
             'unboundNewNumberCount': len(missing), 'errors': list(dict.fromkeys(errors))})
    if source_parameter_ids:audit['sourceParameterIdentityContractVersion']=1
    if bound_benchmark_names:audit['sourceParameterIdentityContractVersion']=3 if alignment_words else 2
    if explicit_condition_pairs:audit['sourceParameterIdentityContractVersion']=4
    if interpolation_kernel_labels:audit['sourceParameterIdentityContractVersion']=5
    if cited_paper_pair:audit['sourceParameterIdentityContractVersion']=6
    if bound_citation_labels:audit['sourceParameterIdentityContractVersion']=7
    if target_structure:
        audit.update(reviewTargetStructureContractVersion=2 if target_structure == 2 else 1,
                     targetStructureReferences=target_references)
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
