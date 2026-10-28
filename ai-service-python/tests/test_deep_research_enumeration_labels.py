from copy import deepcopy
from unittest.mock import Mock
import pytest
from services.deep_research.enumeration_labels import without_enumeration_labels
from services.deep_research.verification import make_evidence,precheck_claims,verify_claims


def sample(text='流程三个主要环节分别改变：剪枝减少数量；蒸馏压缩特征；量化降低精度。'):
    quote='Pruning reduces Gaussian count; distillation compresses features; quantization reduces precision.'
    ev=make_evidence({'workId':'p','versionId':'v','contentHash':'h','accessLevel':'fulltext'},quote,quote,location={},obligation_ids=[])
    return ev,{'claimId':'c','kind':'reported','text':text,'evidenceRefs':[ev['evidenceId']]}


@pytest.mark.parametrize('label',['三个主要环节分别改变','3个主要环节分别改变','三项要点','三个关键方面如下'])
@pytest.mark.parametrize('version',[7,8])
def test_complete_prose_list_reaches_semantic_check_not_automatic_acceptance(label,version):
    ev,c=sample(label+'：剪枝减少数量；蒸馏压缩特征；量化降低精度。');before=deepcopy((ev,c))
    assert precheck_claims([c],[ev],quantity_spelling_version=6)['rejected'][0]['reason']=='numeric_mismatch'
    assert not precheck_claims([c],[ev],quantity_spelling_version=version)['rejected']
    semantic=Mock(return_value=[{'claimId':'c','status':'unresolved','reason':'list content still needs checking'}])
    assert not verify_claims([c],[ev],semantic,quantity_spelling_version=version)['accepted']
    semantic.assert_called_once();assert (ev,c)==before


@pytest.mark.parametrize('text',[
    '三个要点：甲；乙。','三个要点：甲；乙；丙；丁。','三个要点：甲；乙；。',
    '三个要点：例如甲；乙；丙。','三个要点：甲；乙；丙等。',
    '三个要点：甲（说明；补充）；乙；丙。',
    '共有三个环节：甲；乙；丙。','流程只有三个环节：甲；乙；丙。',
    '至少三个方面：甲；乙；丙。','固定三个环节：甲；乙；丙。',
    '负 三个方面：甲；乙；丙。','二至三个方面：甲；乙；丙。',
    '三个数据集：甲；乙；丙。','三个高斯：甲；乙；丙。',
    '三个阶段：甲；乙；丙。','三维特征：甲；乙；丙。',
    '论文三个层：甲；乙；丙。','三个要点分别改变了表示。',
])
@pytest.mark.parametrize('version',[7,8])
def test_nonlist_mismatched_empirical_and_exact_counts_remain_checked(text,version):
    assert without_enumeration_labels(text)==text
    ev,c=sample(text)
    assert precheck_claims([c],[ev],quantity_spelling_version=version)['rejected'][0]['reason']=='numeric_mismatch'


def test_measured_number_inside_an_editorial_list_is_not_removed():
    ev,c=sample('三个要点：剪枝减少3%数量；蒸馏压缩特征；量化降低精度。')
    assert precheck_claims([c],[ev],quantity_spelling_version=7)['rejected'][0]['reason']=='numeric_mismatch'


def test_undeclared_or_noninteger_policy_cannot_enable_exemption():
    ev,c=sample()
    for version in (None,True,'7',0,1,2,3,4,5,6,9):
        # Version0 does not parse Chinese word counts; only assert unchanged
        # spelling behavior for policies that do, with Arabic label for all.
        c['text']=c['text'].replace('三个','3个')
        assert precheck_claims([c],[ev],quantity_spelling_version=version)['rejected']


@pytest.mark.parametrize('parenthetical',['（VQ）','(VQ)','（位置、尺度、旋转）','[特征]'])
def test_balanced_explanatory_brackets_only_in_version8(parenthetical):
    ev,c=sample('三个主要环节分别改变：剪枝减少数量；蒸馏压缩特征；量化'+parenthetical+'降低精度。')
    assert precheck_claims([c],[ev],quantity_spelling_version=7)['rejected']
    assert not precheck_claims([c],[ev],quantity_spelling_version=8)['rejected']


@pytest.mark.parametrize('body',['甲（说明；补充）；乙；丙','甲（说明）；乙；丙）','甲（说明；乙；丙','甲（说明）；乙','甲（说明）；乙；丙；丁','甲（3%）；乙；丙'])
def test_nested_malformed_mismatched_or_measured_brackets_still_fail(body):
    ev,c=sample('三个要点：'+body+'。')
    assert precheck_claims([c],[ev],quantity_spelling_version=8)['rejected']
