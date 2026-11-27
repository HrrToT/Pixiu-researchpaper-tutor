"""Keep generated requirements neutral and independently cover each requested aspect."""
from copy import deepcopy
import re

from services.deep_research.request_context import ResearchQuestion

_ASK = re.compile(r'如何|怎样|为什么|为何|什么|哪些|是否|能否|多少|何时|\b(?:how|why|what|which|whether|when)\b', re.I)
_EXPLAIN = re.compile(r'如何|怎样|为什么|为何|机制|原理|\b(?:how|why)\b', re.I)
_EXAMPLE = re.compile(r'[（(]\s*(?:例如|如|e\.g\.|such as)\s*[^（）()]*[）)]', re.I)


def enabled(record):
    return type(record.get('evidenceCoverageContractVersion')) is int and record['evidenceCoverageContractVersion'] in (1, 2, 3)


def grounded(record):
    return type(record.get('requestGroundingContractVersion')) is int and record['requestGroundingContractVersion'] in (1,2,3,4,5)


def imperative_grounded(record):
    return type(record.get('requestGroundingContractVersion')) is int and record['requestGroundingContractVersion'] in (2,3,4,5)


def criteria(obligation):
    return obligation.get('completionCriteria') or [{'criterionId': 'whole_obligation',
        'requirement': obligation['question'], 'responseType': 'explanation'}]


def _question_parts(text):
    # A comma inside a user-supplied example or a decimal point is not a new
    # requested aspect. Return literal slices, never paraphrase the request.
    opens = {'(': ')', '（': '）', '[': ']', '【': '】', '《': '》', '“': '”', '‘': '’'}
    stack, start, parts = [], 0, []
    for i, char in enumerate(text):
        if char in opens:
            stack.append(opens[char])
        elif stack and char == stack[-1]:
            stack.pop()
        elif not stack and char in '，,；;？?。\n':
            parts.append(text[start:i].strip()); start = i + 1
    parts.append(text[start:].strip())
    return parts


_COMMAND = re.compile(r'^(?:(?:请你?|帮我|同时|并且?|然后|还要|再|只|仅|必须|需要)\s*|'
    r'(?:please|and|then|also|only)\s+)*(核查|核对|验证|判断|评估|评价|比较|对比|区分|解释|讲解|说明|'
    r'阐明|分析|设计|规划|给出|总结|概括|归纳|梳理|指出|'
    r'check\b|verify\b|assess\b|evaluate\b|compare\b|contrast\b|distinguish\b|explain\b|'
    r'describe\b|analy[sz]e\b|design\b|plan\b|summari[sz]e\b|identify\b)',re.I)
_LIMIT = re.compile(r'未验证|未核验|边界|限制|适用范围|推广范围|\b(?:unverified|limit\w*|boundar\w*)\b',re.I)
_PROCEDURE_COMMAND = re.compile(r'^(?:设计|规划|design|plan)$',re.I)
_PER_SOURCE_RESULT = re.compile(
    r'^(?:(?:并且?|同时|还要|请)\s*)?(?:各自?|分别)\s*(?:引用|列出|提供|给出|报告|选取)\s*'
    r'(?:一|1)\s*(?:条|项|个|组).{0,75}(?:定量结果|原文结果|测量结果|评测结果|数值)')
_JOINT_RESULT = re.compile(r'比较|对比|对照|共同|排名|排序|可比')


def _outside_examples(text):
    opens={'(':')','（':'）','[':']','【':'】','《':'》','“':'”','‘':'’','"':'"'}
    stack=[];visible=[]
    for char in text:
        if stack and char==stack[-1]:
            stack.pop();visible.append(' ')
        elif char in opens:
            stack.append(opens[char]);visible.append(' ')
        else: visible.append(' ' if stack else char)
    return ''.join(visible)


def _request_parts(text):
    """Literal command slices; commas inside a requested object list stay put.

    Only a new explicit command/question can start another aspect at a comma.
    Quoted examples and scientific hypotheses never become commands themselves.
    """
    opens={'(':')','（':'）','[':']','【':'】','《':'》','“':'”','‘':'’','"':'"'}
    stack=[];separators=[]
    for i,char in enumerate(text):
        if stack and char==stack[-1]: stack.pop()
        elif char in opens: stack.append(opens[char])
        elif not stack and char in '，,；;？?。\n': separators.append((i,char))
    def is_start(value):
        value=value.lstrip()
        return bool(_COMMAND.match(value) or re.match(r'^(?:如何|怎样|为什么|为何|什么|哪些|是否|能否|多少|何时|how\b|why\b|what\b|which\b|whether\b|when\b)',value,re.I))
    parts=[];start=0
    for index,char in separators:
        if char in '，,' and not is_start(text[index+1:]): continue
        parts.append(text[start:index].strip());start=index+1
    parts.append(text[start:].strip())
    return parts


def _requested_type(text):
    command=_COMMAND.match(text)
    if command:
        verb=command.group(1)
        if _PROCEDURE_COMMAND.fullmatch(verb) or verb=='给出' and re.search(r'实验|方案|对照|步骤|执行',text):
            return 'procedure'
        if _LIMIT.search(text) and re.fullmatch(r'区分|说明|指出|distinguish|describe|identify',verb,re.I):
            return 'limitation'
        return 'explanation'
    return 'explanation' if _EXPLAIN.search(text) else 'identification'


def _split_measurements_from_joint_results(plan, question, human):
    """Recover a literal per-paper measurement before planning evidence cells."""
    from services.deep_research.comparison_intent import validate_role

    obligations = [row for item in plan for row in item['obligations']]
    identities = {row['obligationId'] for row in obligations}
    owned_measurements = set()
    changes = []
    for row in obligations:
        role = validate_role(row, question)
        if role['kind'] != 'per_paper':
            continue
        excerpt = row.get('requestExcerpt')
        if isinstance(excerpt, str):
            measurement = excerpt.rstrip('，,；;？?。\n ')
            if (_PER_SOURCE_RESULT.fullmatch(measurement) and not _JOINT_RESULT.search(measurement)
                    and role['requestExcerpt'] in measurement and any(measurement in layer for layer in human)
                    and role['requestExcerpt'] != measurement):
                role['requestExcerpt'] = measurement
                changes.append({'obligationId': row['obligationId'], 'change': 'complete_per_paper_result_excerpt'})
        owned_measurements.add(role['requestExcerpt'])
    for item in plan:
        for row in list(item['obligations']):
            role = validate_role(row, question)
            excerpt = row.get('requestExcerpt')
            if (role['kind'] != 'joint' or not isinstance(excerpt, str)
                    or role['requestExcerpt'] not in excerpt
                    or not any(excerpt in layer for layer in human)):
                continue
            measurement, *rest = _question_parts(excerpt)
            if rest and not rest[-1]:
                rest.pop()
            if (not rest or not excerpt.startswith(measurement)
                    or not _PER_SOURCE_RESULT.fullmatch(measurement) or _JOINT_RESULT.search(measurement)
                    or not all(4 <= len(part) <= 500 and (
                        _ASK.search(_outside_examples(part)) or _COMMAND.match(part)) for part in rest)
                    or not any(_JOINT_RESULT.search(_outside_examples(part)) for part in rest)):
                continue
            remainder = excerpt[len(measurement):].strip('，,；;？?。\n ')
            anchor = role['requestExcerpt']
            if anchor not in remainder:
                anchor = next(part for part in rest if _JOINT_RESULT.search(_outside_examples(part)))
            row.update(question=remainder, requestExcerpt=remainder)
            role.update(label='比较范围', requestExcerpt=anchor)
            changes.append({'obligationId': row['obligationId'], 'change': 'split_joint_quantitative_result'})
            if measurement in owned_measurements:
                continue

            identity = 'per_paper_result'
            suffix = 1
            while identity in identities:
                suffix += 1
                identity = f'per_paper_result_{suffix}'
            identities.add(identity)
            owned_measurements.add(measurement)
            result = deepcopy(row)
            result.update(
                obligationId=identity, question=measurement, requestExcerpt=measurement,
                comparisonRole={'kind': 'per_paper', 'label': '逐篇定量结果', 'requestExcerpt': measurement},
                completionCriteria=[{
                    'criterionId': 'human_aspect_1', 'requirement': measurement, 'responseType': 'identification',
                }],
            )
            item['obligations'].append(result)
            changes.append({'obligationId': identity, 'change': 'retained_per_paper_quantitative_result',
                            'jointObligationId': row['obligationId']})
    return changes


def normalize_generated_requirements(plan, question, *, literal_questions=False,literal_imperatives=False,atomic_dimensions=False,compound_questions=False,comparison_roles=False,joint_comparison_requests=False,per_paper_comparison_requests=False,complete_comparison_clauses=False,correct_per_paper_results=False,split_joined_per_paper_results=False):
    """Change only the initial AI plan, never a saved human plan edit.

    Separate literal human questions when one generated criterion merged them.
    Candidate examples absent from human instructions are removed from generated
    questions/requirements, not treated as scientific answers. Other semantic
    additions remain subject to the original-question and factual audits.
    """
    human = question.instruction_layers if isinstance(question, ResearchQuestion) else (question,)
    result, changes = deepcopy(plan), []
    if comparison_roles and split_joined_per_paper_results:
        changes.extend(_split_measurements_from_joint_results(
            result, question, getattr(question, 'point_instruction_layers', None) or human))
    comparison_obligations = [row for item in result for row in item['obligations']] if (
        joint_comparison_requests or per_paper_comparison_requests) else []
    if comparison_roles and comparison_obligations:
        from services.deep_research.comparison_intent import validate_role
        comparison_spans = {id(row): validate_role(row, question)['requestExcerpt']
                            for row in comparison_obligations}
    else:
        comparison_spans = {}
    def neutral(text, identity, field):
        def replace(match):
            if any(match.group() in layer for layer in human):
                return match.group()
            changes.append({'obligationId': identity, 'field': field, 'change': 'removed_generated_example'})
            return ''
        return _EXAMPLE.sub(replace, text)
    for item in result:
        anchored = []
        for obligation in item['obligations']:
            oid = obligation['obligationId']
            obligation['question'] = neutral(obligation['question'], oid, 'question')
            original = obligation.get('completionCriteria', [])
            for criterion in original:
                criterion['requirement'] = neutral(criterion['requirement'], oid, 'requirement')
            excerpt = obligation.get('requestExcerpt', '')
            anchored_parts = None
            allow_source_results = False
            if comparison_roles:
                from services.deep_research.comparison_intent import validate_role
                role = validate_role(obligation, question)
                if (correct_per_paper_results and role['kind'] == 'joint'
                        and len(original) == 1 and isinstance(excerpt, str)
                        and role['requestExcerpt'] in excerpt and any(excerpt in layer for layer in human)
                        and _PER_SOURCE_RESULT.fullmatch(excerpt)
                        and not re.search(r'比较|对照|共同|排名|排序', excerpt)):
                    role.update(kind='per_paper', requestExcerpt=excerpt)
                    changes.append({'obligationId': oid, 'change': 'per_paper_quantitative_result_role'})
                allow_source_results = complete_comparison_clauses and role['kind'] == 'per_paper'
                # The longer context excerpt can straddle adjacent dimensions.
                # Its typed short span identifies this obligation's actual axis.
                preserve_explicit = (joint_comparison_requests and role['kind'] == 'joint'
                                     or per_paper_comparison_requests and role['kind'] == 'per_paper')
                if (preserve_explicit
                        and isinstance(excerpt,str) and role['requestExcerpt'] in excerpt
                        and any(excerpt in layer for layer in human)):
                    clauses = _question_parts(excerpt)
                    if compound_questions and role['kind'] == 'per_paper':
                        from services.deep_research.compound_questions import split_questions
                        clauses = [part for clause in clauses for part in split_questions(clause)]
                    if 2 <= len(clauses) <= 4 and all(
                            _ASK.search(_outside_examples(clause)) or _COMMAND.match(clause)
                            or allow_source_results and _PER_SOURCE_RESULT.match(clause) for clause in clauses):
                        other_spans = [span for identity, span in comparison_spans.items() if identity != id(obligation)]
                        owned = [clause for clause in clauses if not any(
                            span in clause or clause in span for span in other_spans)]
                        anchor = role['requestExcerpt']
                        has_anchor = any(anchor in clause or complete_comparison_clauses and clause in anchor
                                         for clause in owned)
                        if len(owned) >= 2 and has_anchor:
                            anchored_parts = owned
                if anchored_parts is None:
                    excerpt = role['requestExcerpt']
            if not isinstance(excerpt, str) or not excerpt or not any(excerpt in layer for layer in human):
                continue
            parts = anchored_parts or (_request_parts(excerpt) if literal_imperatives else _question_parts(excerpt))
            if compound_questions:
                from services.deep_research.compound_questions import split_questions,has_question,explanatory
                if not (complete_comparison_clauses and anchored_parts):
                    parts=[piece for part in parts for piece in split_questions(part)]
            if literal_imperatives:
                requests = [part for part in parts if _ASK.search(_outside_examples(part)) or _COMMAND.match(part)
                            or allow_source_results and _PER_SOURCE_RESULT.match(part)
                            or compound_questions and has_question(part)]
            else:
                requests = [part for part in parts if _ASK.search(part)]
            if not (1 if literal_questions else 2) <= len(requests) <= 4 or any(not 4 <= len(part) <= 500 for part in requests):
                continue
            resolved = [
                {'criterionId': f'human_aspect_{i+1}', 'requirement': part,
                 'responseType': 'identification' if allow_source_results and _PER_SOURCE_RESULT.match(part) else
                     _requested_type(part) if literal_imperatives else
                     'explanation' if _EXPLAIN.search(part) else 'identification'}
                for i, part in enumerate(requests)]
            if compound_questions:
                for row in resolved:
                    if row['responseType']=='identification' and explanatory(row['requirement']):row['responseType']='explanation'
            if atomic_dimensions:
                from services.deep_research.request_dimensions import split_dimensions
                dimensions=[dimension for row in resolved for dimension in
                            (split_dimensions(row['requirement']) or [{k:row[k] for k in ('requirement','responseType')}])]
                if len(dimensions)<=4:
                    resolved=[{'criterionId':f'human_aspect_{i+1}',**row} for i,row in enumerate(dimensions)]
            obligation['completionCriteria'] = resolved
            if literal_questions:
                # The generated criterion can add an unprovided attribute list
                # even when the user asked one simple question. Use the literal
                # question, not a model paraphrase of the desired answer.
                obligation['question'] = '；'.join(anchored_parts) if anchored_parts else excerpt
                anchored.append(obligation['question'])
            changes.append({'obligationId': oid, 'change': 'anchored_literal_human_aspects' if literal_questions else 'separated_literal_human_aspects',
                            'criterionCount': len(resolved)})
        if literal_questions and len(anchored) == len(item['obligations']):
            item['question'] = '；'.join(dict.fromkeys(anchored))
    return result, changes
