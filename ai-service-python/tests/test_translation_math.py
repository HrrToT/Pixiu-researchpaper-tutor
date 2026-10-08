import json
from unittest.mock import patch

import pytest
from schemas.requests import PageTranslationRequest
from services.page_translation_service import translate_page
from services.translation_math import protect_inline_math, has_intact_math_tokens


@pytest.mark.parametrize('expression', ['V(Σj) = 43πabc', 'SH ∈ R(k+1) × 3', 'T = j−1', 'Σ′ = J WΣWTJT'])
def test_damaged_inline_expression_is_not_sent_as_translatable_prose(expression):
    masked = protect_inline_math('The expression is ' + expression + ', where the definition follows.')
    assert expression not in masked
    assert '⟦原式1⟧' in masked
    assert 'where the definition follows.' in masked
    if expression == 'Σ′ = J WΣWTJT':
        assert 'WΣWTJT' not in masked


def test_math_protection_does_not_consume_ordinary_prose_or_guess_the_formula():
    prose = 'Gaussian pruning removes redundant points. SH distillation preserves appearance.'
    assert protect_inline_math(prose) == prose
    masked = protect_inline_math('The volume is V(Σj) = 43πabc, where abc are the scale dimensions.')
    assert 'frac' not in masked and 'where abc are the scale dimensions.' in masked
    assert has_intact_math_tokens(masked, '体积为⟦原式1⟧，abc是尺度维度。')
    assert not has_intact_math_tokens(masked, '体积为43πabc。')
    assert not has_intact_math_tokens(masked, '⟦原式1⟧ ⟦原式1⟧')
    assert not has_intact_math_tokens('⟦原式1⟧ and ⟦原式2⟧', '⟦原式2⟧和⟦原式1⟧')


def test_one_bad_math_block_is_partial_without_retrying_or_erasing_the_good_block():
    request = PageTranslationRequest(pageIndex=3, pageText='The volume is V(Σj) = 43πabc.',
        pageLayout={'blocks': [{'id':'math','text':'The volume is V(Σj) = 43πabc.'},
                              {'id':'prose','text':'Pruning reduces storage.'}]})
    def response(prompt, **kwargs):
        assert '43πabc' not in prompt and '⟦原式1⟧' in prompt
        return json.dumps({'translatedBlocks':[{'id':'math','translatedText':'体积是43πabc。'},
                                              {'id':'prose','translatedText':'剪枝降低存储。'}]})
    with patch('services.page_translation_service._call_translation_with_timeout',side_effect=response) as model:
        result=translate_page(request)
    assert model.call_count == 1
    assert result['status']=='partial' and result['missingBlockIds']==['math']
    assert result['translatedText']=='剪枝降低存储。'
    assert result['mathProtectionVersion']==1


def test_plain_translation_must_preserve_markers_without_automatic_fallback():
    request=PageTranslationRequest(pageIndex=3,pageText='The volume is V(Σj) = 43πabc.')
    with patch('services.page_translation_service._call_translation_with_timeout',return_value='体积是43πabc。') as model:
        with pytest.raises(RuntimeError,match='原式标记'):
            translate_page(request)
    assert model.call_count==1


def test_valid_math_markers_survive_a_successful_structured_translation():
    request=PageTranslationRequest(pageIndex=3,pageText='The volume is V(Σj) = 43πabc.',
        pageLayout={'blocks':[{'id':'body','text':'The volume is V(Σj) = 43πabc.'}]})
    with patch('services.page_translation_service._call_translation_with_timeout',return_value=
               '{"translatedBlocks":[{"id":"body","translatedText":"体积为⟦原式1⟧。"}]}') as model:
        result=translate_page(request)
    assert model.call_count==1 and result['status']=='success'
    assert result['translatedText']=='体积为⟦原式1⟧。' and result['mathProtectionVersion']==1
