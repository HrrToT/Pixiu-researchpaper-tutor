from copy import deepcopy
import json
from services.deep_research.repair_prompt import factor_repair_questions


def test_factorization_roundtrip_retains_every_question_and_claim_binding():
    original = {'a': {'reason': 'incomplete', 'missingQuestions': ['exact question 一', 'other', 'exact question 一'],
                      'missingEvidenceRefs': ['e1']},
                'b': {'missingQuestions': ['other'], 'detail': 'unchanged'}}
    before = deepcopy(original)
    dictionary, packed = factor_repair_questions(original)
    assert len(dictionary) == 2
    restored = deepcopy(packed)
    for row in restored.values():
        row['missingQuestions'] = [dictionary[key] for key in row.pop('missingQuestionIds')]
    assert restored == original == before


def test_unknown_or_colliding_fields_are_preserved_without_reinterpretation():
    original = {'a': {'missingQuestions': [None]}, 'b': {'detail': 'plain'},
                'c': {'missingQuestions': ['x'], 'missingQuestionIds': ['user-field']}}
    dictionary, packed = factor_repair_questions(original)
    assert dictionary == {} and packed == original


def test_repeated_long_questions_are_stored_once_without_truncation():
    question = '完整的实验条件与数据范围问题' * 30
    original = {str(i): {'missingQuestions': [question]} for i in range(10)}
    dictionary, packed = factor_repair_questions(original)
    assert list(dictionary.values()) == [question]
    assert len(json.dumps([dictionary, packed], ensure_ascii=False)) < len(json.dumps(original, ensure_ascii=False)) / 2
