"""Human-only display constraints; never substitute format for scientific support."""
import re

from services.deep_research.answer_constraints import answer_character_count, requested_character_limit
from services.deep_research.request_context import ResearchQuestion, effective_question

_COUNT = r'(\d{1,2}|[一二两三四五六七八九十]{1,3})'
_CHINESE = re.compile(r'(只写|只列出?|列出|写成|分成|分为|分|用|最多|不超过)\s*' + _COUNT
                      + r'\s*(?:个)?(?:要点|点|条)(以内|以下)?')
_ENGLISH = re.compile(r'\b(exactly|only|at most|no more than)\s+(\d{1,2})\s+(?:bullet\s+)?points?\b', re.I)
_CANCEL = re.compile(r'(?:取消|去掉)(?:原来(?:的)?|之前(?:的)?)?(?:分点|点数|条数)(?:要求|限制)?'
                     r'|(?:不用|无需|不要|不必)分点|(?:写成|改成)(?:一|1)段'
                     r'|\bno (?:bullet |point )count limit\b', re.I)


def _number(value):
    if value.isdigit():
        return int(value)
    digits = dict(zip('一二两三四五六七八九', (1, 2, 2, 3, 4, 5, 6, 7, 8, 9)))
    if '十' in value:
        left, right = value.split('十', 1)
        if left not in ('', '一', '二', '两') or right and right not in digits:
            return 0
        return digits.get(left, 1) * 10 + digits.get(right, 0)
    return digits.get(value, 0)


def requested_points(question):
    """Recognize explicit requests, newest human clarification first.

    A paper's 'three contributions', model examples and parent artifact text do
    not create instructions. Ambiguous prose is left to the existing audit.
    """
    layers = getattr(question,'point_instruction_layers',question.instruction_layers) if isinstance(question, ResearchQuestion) else (question,)
    for layer in layers:
        found = [(m.start(), None) for m in _CANCEL.finditer(layer)]
        for pattern in (_CHINESE, _ENGLISH):
            for match in pattern.finditer(layer):
                if re.search(r'(?:不要|不用|无需|不必|不能|不是|不再|\b(?:not|never)(?:\s+(?:use|write|list|give|return))?)\s*$', layer[:match.start()], re.I):
                    continue
                number = _number(match[2])
                if not 1 <= number <= 20:
                    continue
                maximum = match[1].lower() in ('最多', '不超过', 'at most', 'no more than')
                if pattern is _CHINESE and match[3]:
                    maximum = True
                found.append((match.start(), {'count': number, 'mode': 'max' if maximum else 'exact'}))
        if found:
            return max(found, key=lambda row: row[0])[1]
    return None


def enabled(record):
    return type(record.get('answerFormatContractVersion')) is int and record['answerFormatContractVersion'] == 1


def guidance(constraint):
    if not constraint:
        return ''
    quantity = ('exactly ' if constraint['mode'] == 'exact' else 'at most ') + str(constraint['count'])
    return ('\nHuman display requirement: use ' + quantity + ' distinct answer points, one claim per point. '
            'Allocate points to the requested aspects before optional caveats. Put necessary limits beside '
            'the relevant explanation, rather than spending a point on repeated generic disclaimers. '
            'Do not pad or invent facts to meet the count. Unsupported points remain explicit gaps.')


def publication_format_gaps(record, claims, sections):
    if not enabled(record):
        return []
    question = effective_question(record)
    by_id = {c.get('claimId'): c for c in claims if c.get('claimId')}
    ids = list(dict.fromkeys(key for section in sections for key in section.get('claimIds', []) if key in by_id))
    visible = [by_id[key] for key in ids]
    constraint, gaps = requested_points(question), []
    if constraint:
        expected, actual = constraint['count'], len(visible)
        mismatch = actual != expected if constraint['mode'] == 'exact' else actual > expected
        if mismatch:
            prefix = '最多' if constraint['mode'] == 'max' else ''
            gaps.append({'question': f'按要求整理为{prefix}{expected}点',
                'missingEvidence': f'当前已核验正文有{actual}点，尚未满足分点要求。',
                'stage': 'answer_format', 'wholeQuestion': True,
                'expectedPointCount': expected, 'actualPointCount': actual, 'pointMode': constraint['mode']})
        if any(re.search(r'\n[ \t]*(?:[-+*]|\d+[.)]|#{1,6})\s+', row.get('text', '')) for row in visible):
            gaps.append({'question': '按要求整理分点结构',
                'missingEvidence': '单个回答点中还包含额外列表或标题，尚未满足分点要求。',
                'stage': 'answer_format', 'wholeQuestion': True})
    limit = requested_character_limit(question)
    actual = answer_character_count({'claims': visible})
    if limit and actual > limit:
        gaps.append({'question': f'将正文控制在{limit}字以内',
            'missingEvidence': f'当前正文和适用条件合计{actual}字，尚未满足字数要求。',
            'stage': 'answer_format', 'wholeQuestion': True,
            'expectedCharacterLimit': limit, 'actualCharacterCount': actual})
    return gaps
