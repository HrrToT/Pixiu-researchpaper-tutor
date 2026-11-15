from unittest.mock import Mock
import pytest

from services.deep_research.prose_checks import absence_not_established
from services.deep_research.verification import verify_claims,precheck_claims


def fixture(text,kind='proposal'):
    claim={'claimId':'c','kind':kind,'text':text,'evidenceRefs':['e']}
    evidence={'evidenceId':'e','quote':'The method uses a compact representation.',
              'accessLevel':'fulltext','verification':{'literal':'passed'}}
    return claim,evidence


@pytest.mark.parametrize('kind',['reported','inference','proposal','suggestion','hypothesis'])
@pytest.mark.parametrize('text',[
    '建议采用该方法，但其画质指标未在论文中量化报告。',
    '这些结果没有在该论文中明确给出。',
    'Quality metrics are not quantitatively reported in the paper.',
    'These results were never provided in this article.',
    '若干指标未在论文中报告。',
])
def test_source_owner_after_negation_is_checked_in_every_claim_kind(kind,text):
    claim,evidence=fixture(text,kind);semantic=Mock()
    result=verify_claims([claim],[evidence],semantic,absence_scope_version=8)
    assert not result['accepted'] and result['rejected'][0]['reason']=='absence_not_established'
    semantic.assert_not_called()


@pytest.mark.parametrize('text',[
    '如果指标未在论文中报告，建议先向作者核实。',
    '需要核实指标是否未在论文中报告。',
    '不能据此认为指标未在论文中量化报告。',
    'Quality is not reported in the paper excerpt.',
    "Quality is not reported in this paper's excerpt.",
    'If quality is not reported in the paper, ask the authors.',
    'We cannot conclude that quality is not reported in the paper.',
    '指标未在论文片段中报告。',
    '尚不能从当前引用确认画质指标与另一方法对齐。',
    '建议在统一设备上报告画质指标。',
])
def test_hypothetical_epistemic_bounded_or_proposed_reporting_is_not_source_absence(text):
    claim,evidence=fixture(text)
    assert not absence_not_established(claim,[evidence],scope_version=8)


@pytest.mark.parametrize('version',range(8))
def test_old_profiles_do_not_reinterpret_the_saved_advice(version):
    claim,evidence=fixture('建议采用该方法，但其画质指标未在论文中量化报告。')
    assert not absence_not_established(claim,[evidence],scope_version=version)


def test_new_policy_keeps_all_prior_internal_alias_checks():
    claim,evidence=fixture('建议先阅读P1的方法。')
    old=precheck_claims([claim],[evidence],absence_scope_version=7)
    new=precheck_claims([claim],[evidence],absence_scope_version=8)
    assert old==new and old['rejected'][0]['reason']=='internal_reference_in_prose'


def test_source_explicit_reporting_absence_still_requires_semantic_judgement():
    claim,evidence=fixture('该结果未在论文中报告。')
    evidence['quote']='We do not report this result.'
    assert not absence_not_established(claim,[evidence],scope_version=8)
    semantic=Mock(return_value=[{'claimId':'c','status':'failed','reason':'The cited absence concerns a different result.'}])
    result=verify_claims([claim],[evidence],semantic,absence_scope_version=8)
    assert not result['accepted'] and semantic.call_count==1
