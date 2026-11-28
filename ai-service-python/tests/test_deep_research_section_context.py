from copy import deepcopy
from types import SimpleNamespace
import pytest

from services.deep_research.section_context import include_section_context


def row(i, text, page=5):
    return {'sourceId': f'p-v{"a" * 16}-chunk-{i}', 'pdfId': 'p',
            'sourceType': 'current_paper', 'text': text,
            'metadata': {'id': 'p', 'index_version': 'a' * 16, 'section_title': 'TRAINING', 'chunk_index': i},
            'location': {'page': page, 'chunk': i, 'section': 'TRAINING'}}


def record():
    return {'localSectionContextContractVersion': 1, 'sectionPremisesContractVersion': 2,
            'question': '解释第5节中两个约束分别约束什么。',
            'state': {'outputKind': 'claim_verification'}}


def sample():
    head = row(34, '5 TRAINING\nTwo regularizers are introduced. Depth distortion concentrates the weight')
    next1 = row(35, 'distribution along the ray. Normal consistency aligns splats')
    next2 = row(36, 'with normals computed from depth gradients.')
    return [head, row(50, 'Ablation result.'), row(51, 'Another experiment.')], [head, next1, next2]


def test_requested_section_gets_separate_unchanged_successors_within_limit():
    selected, candidates = sample();before = deepcopy((selected, candidates))
    out = include_section_context(selected, candidates, record(), 'p', 3)
    assert [r['location']['chunk'] for r in out] == [34, 35, 36]
    assert out[0] is selected[0]
    for original, result in zip(candidates[1:], out[1:]):
        assert {k: result[k] for k in original} == original
        assert result['contextForSourceId'] == selected[0]['sourceId']
    assert (selected, candidates) == before


@pytest.mark.parametrize('change', [
    {'pdfId': 'foreign'}, {'accessLevel': 'abstract'}, {'sourceId': 'forged'},
    {'location': {'page': 9, 'chunk': 35, 'section': 'TRAINING'}},
    {'metadata': {'id': 'foreign'}}, {'metadata': {'index_version': 'b' * 16}},
    {'metadata': {'section_title': 'RESULTS'}}, {'metadata': {'chunk_index': True}},
])
def test_invalid_next_chunk_cannot_bridge_to_a_later_one(change):
    selected, candidates = sample()
    for k, value in change.items():
        if k == 'metadata': candidates[1][k].update(value)
        else: candidates[1][k] = value
    assert include_section_context(selected, candidates, record(), 'p', 3) == selected


def test_ambiguous_successor_and_old_or_non_explanation_runs_keep_old_selection():
    selected, candidates = sample()
    assert include_section_context(selected, candidates + [candidates[1]], record(), 'p', 3) == selected
    for marker in [None, False, True, 0, 10]:
        r = record();r['localSectionContextContractVersion'] = marker
        assert include_section_context(selected, candidates, r, 'p', 3) == selected
    for question in ['解释方法。', '不要解释第5节。', '比较第5节中的性能。']:
        r = record();r['question'] = question
        assert include_section_context(selected, candidates, r, 'p', 3) == selected


def test_no_source_limit_increase_or_loss_of_best_hit_and_existing_context_pairs():
    selected, candidates = sample();best = row(0, 'Best semantic hit.')
    out = include_section_context([best] + selected, candidates, record(), 'p', 4)
    assert out[0] is best and len(out) == 4
    assert include_section_context([best] + selected, candidates, record(), 'p', 3) == [best] + selected[:2]
    selected[1]['contextForSourceId'] = selected[2]['sourceId']
    assert include_section_context(selected, candidates, record(), 'p', 3) == selected


def test_local_retriever_applies_selector_and_rejects_revoked_scope():
    from services.deep_research.local_sources import LocalTaskRetriever
    from services.deep_research.contracts import DeepResearchError
    selected, candidates = sample();r = record();r['scopeEvidenceContractVersion'] = 1
    reader = LocalTaskRetriever(SimpleNamespace(require_run=lambda _: r), 'run', lambda *_: True, origin='http://localhost')
    assert [x['location']['chunk'] for x in reader._scope_evidence(selected, candidates, '', 'p', 3)] == [34, 35, 36]
    reader.validate = lambda *_: False
    with pytest.raises(DeepResearchError, match='论文范围'):
        reader._scope_evidence(selected, candidates, '', 'p', 3)


@pytest.mark.parametrize('eligible', [True, False])
def test_single_paper_explanation_gets_relevant_method_within_existing_budget(eligible):
    from services.deep_research.local_sources import LocalTaskRetriever

    r = record()
    question = 'Explain how the encoder converts sensor features into a compact message.'
    query = 'encoder converts sensor features compact message'
    r.update(localSectionContextContractVersion=3 if eligible else 2, scopeEvidenceContractVersion=1,
             question=question, sourcePolicy={'mode': 'task_only'}, materials=[{'materialId': 'p'}])
    r['state']['plan'] = [{'obligations': [{'question': question, 'searchQuery': query, 'requiredSources': ['p']}]}]
    top, overview = row(2, 'The introduction summarizes the proposed sensor compression system.'), row(3, 'A generic abstract.')
    detail = row(8, 'The encoder converts sensor features into a compact message. It extracts and normalizes each feature.')
    for key in ('metadata', 'location'):
        title_key = 'section_title' if key == 'metadata' else 'section'
        detail[key][title_key] = 'Methods'
        top[key][title_key] = 'Introduction'
        overview[key][title_key] = 'Abstract'
    foreign = {**detail, 'sourceId': f'p-v{"b" * 16}-chunk-8',
               'metadata': {**detail['metadata'], 'index_version': 'b' * 16}}
    reader = LocalTaskRetriever(SimpleNamespace(require_run=lambda _: r), 'run', lambda *_: True, origin='http://localhost')
    assert reader._scope_evidence([top, overview], [top, overview, foreign, detail], query, 'p', 2) == [
        top, detail if eligible else overview,
    ]
    assert reader._scope_evidence([top, overview], [top, overview, foreign], query, 'p', 2) == [top, overview]
    assert reader._scope_evidence([top, overview], [top, overview, detail, detail], query, 'p', 2) == [top, overview]


def test_pdf_candidate_keeps_a_literal_subsection_within_the_existing_slot_limit():
    from services.deep_research.section_context import include_pdf_method_heading

    r = {**record(), 'localSectionContextContractVersion':4, 'sourcePolicy':{'mode':'task_only'},
         'materials':[{'materialId':'p'}], 'question':'给新手解释自适应阶段的作用，限300字。',
         'audienceFirstContractVersion':2, 'audienceRewriteContractVersion':9,
         'audiencePublicationBudgetContractVersion':1, 'reportPresentationContractVersion':4}
    material = {'materialId':'p', 'contentHash':'a'*64, 'versionId':'p-v1'}
    detail = '3.3. Adaptive stages\nThe pipeline shortens its next stage when the observed signal stays stable. The later stages then use fewer inputs.\n'
    page = {'page':4, 'text':'Prior paragraph.\n'+detail+'3.4. Results\nLimitation.'}
    rows = [row(2, 'Best semantic source.'), row(3, 'Ablation discussion.')]
    out = include_pdf_method_heading(rows, [page], r, 'adaptive stages', material, 2)
    assert out[0] is rows[0] and len(out) == len(rows)
    assert out[1]['text'] == detail and out[1]['location']['offset'] == page['text'].index(detail)
    assert out[1]['location']['page'] == 4 and out[1]['versionId'] == 'p-v1'
    assert include_pdf_method_heading(rows, [page, {**page, 'page':5}], r, 'adaptive stages', material, 2) == rows
    assert include_pdf_method_heading(rows, [page], r, 'adaptive unrelated', material, 2) == rows
    assert include_pdf_method_heading(rows, [page], {**r, 'localSectionContextContractVersion':3},
                                      'adaptive stages', material, 2) == rows


def test_synthesis_prioritizes_only_complete_literal_units_from_the_owned_subsection():
    from services.deep_research.section_context import prioritize_pdf_heading

    material = {'materialId':'p', 'contentHash':'a'*64, 'versionId':'p-v1'}
    source = {'sourceId':'selected', 'ownerMaterialId':'p', 'workId':'p', 'versionId':'p-v1',
              'contentHash':material['contentHash'], 'accessLevel':'fulltext', 'obligationIds':['steps'],
              'text':'First. Second.', 'location':{'page':4, 'matchedPdfSubsection':True}}
    r = {'localSectionContextContractVersion':4, 'materials':[material],
         'state':{'readResults':[source], 'plan':[{'obligations':[{'obligationId':'steps','question':'Explain the steps.'}]}]}}
    shared = {'sourceId':'selected', 'sourceWorkId':'p', 'sourceVersionId':'p-v1',
              'contentHash':material['contentHash'], 'verification':{'literal':'passed'}, 'obligationIds':['steps']}
    a = {**shared, 'evidenceId':'a', 'quote':'First. ', 'location':{'sourcePassageStart':0,'sourcePassageEnd':7}}
    b = {**shared, 'evidenceId':'b', 'quote':'Second.', 'location':{'sourcePassageStart':7,'sourcePassageEnd':14}}
    other = {'evidenceId':'other', 'sourceId':'other-source'}
    ordered, bundles = prioritize_pdf_heading([b, a], [other, a], [], r)
    assert ordered == [a, b, other] and bundles[0]['evidenceIds'] == ['a', 'b']
    for bad in ({**b,'sourceVersionId':'p-v2'}, {**b,'verification':{'literal':'failed'}},
                {**b,'location':{'sourcePassageStart':8,'sourcePassageEnd':15}}):
        assert prioritize_pdf_heading([a, bad], [other], [], r) == ([other], [])


def test_pdf_method_reading_admits_the_continuation_of_a_matching_inline_heading():
    from services.deep_research.section_context import include_pdf_method_passages

    r = {**record(), 'localSectionContextContractVersion':5, 'sourcePolicy':{'mode':'task_only'},
         'materials':[{'materialId':'p'}], 'question':'给新手解释训练损失，限300字。',
         'audienceFirstContractVersion':2, 'audienceRewriteContractVersion':9,
         'audiencePublicationBudgetContractVersion':1, 'reportPresentationContractVersion':4}
    material = {'materialId':'p', 'contentHash':'a'*64, 'versionId':'p-v1', 'title':'ACME: Feature learning'}
    reprojection = '1) Reprojection loss: The distance compares a projected observation with a matched point in the second view.\n'
    continuation = 'The spatial peak score penalizes high responses away from the estimated location within its window.\n'
    pages = [{'page':1, 'text':'II. RELATED WORKS\nA. Fitting Methods\n' + ('Reprojection peak score. ' * 6)},
             {'page':2, 'text':'III. METHODS\nA. Learning Consistent Points\n'+reprojection
                            +'2) Peak loss: The local peak is instead a property of a single response map.\n'},
             {'page':3, 'text':continuation + 'B. Feature Encoder\n' + ('Feature channels combine independent blocks. ' * 3)}]
    table = {**row(2, 'Verified measurements.'), 'tableData': {'rows': [['owned']]}}
    sources = include_pdf_method_passages([table, row(3, 'Preface.')], pages, r, 'reprojection peakiness loss', material, 3)
    assert sources[0] is table and len(sources) == 3
    assert {source['text'] for source in sources[1:]} == {reprojection, continuation}
    for source in sources[1:]:
        loc = source['location']
        assert source['versionId'] == 'p-v1' and loc['matchedPdfMethodPassage'] is True
        assert pages[loc['page']-1]['text'].startswith(source['text'], loc['offset'])


def test_numbered_local_method_subsections_on_one_page_beat_experiment_text():
    from services.deep_research.section_context import include_pdf_method_passages

    r = {**record(), 'localSectionContextContractVersion':6, 'sourcePolicy':{'mode':'task_only'},
         'materials':[{'materialId':'p'}], 'question':'给新手解释邻域匹配，限300字。',
         'audienceFirstContractVersion':2, 'audienceRewriteContractVersion':9,
         'audiencePublicationBudgetContractVersion':1, 'reportPresentationContractVersion':4}
    material = {'materialId':'p','contentHash':'a'*64,'versionId':'p-v1','title':'ACME -- Image Processing'}
    details = ('3. Methodology\n3.1. Matching Probability\n'
               'We normalize matching probabilities over candidates in one direction and then in the reverse direction.\n'
               '3.2. Training\nThe training objective favors matching probabilities around the expected correspondence.\n'
               '4. Experiments\n4.1. Relative pose estimation\n' + 'Matching probabilities benchmark. ' * 16)
    pages = [{'page':4,'text':details}]
    sources = include_pdf_method_passages([],pages,r,'ACME Image Processing matching probabilities training',material,3)
    assert len(sources) == 2
    assert all(s['location']['page']==4 and '3 Methodology /' in s['location']['section'] for s in sources)
    assert all('benchmark' not in s['text'] for s in sources)
    assert include_pdf_method_passages([],pages,{**r,'localSectionContextContractVersion':5},
                                       'ACME Image Processing matching probabilities training',material,3) == []


def test_new_activation_is_server_owned_and_immutable(tmp_path):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo = DeepResearchRepository(tmp_path / 'r.sqlite3');repo.initialize()
    facade = ResearchFacade(repo, lambda **_: None, llm_client=object())
    try:
        r, _ = facade.create({'workspaceTaskId': 't', 'operationKey': 'one', 'question': 'Explain',
            'deferStart': True, 'localSectionContextContractVersion': 0}, start_async=False)
        assert r['localSectionContextContractVersion'] == 9
        for value in [None, True, 0, 2, 3, 4, 5, 6, 7, 8, 10]:
            with pytest.raises(ValueError, match='Immutable run field'):
                repo.update_run(r['runId'], lambda x: {**x, 'localSectionContextContractVersion': value})
    finally:
        facade.shutdown()


def test_inline_formula_labels_on_same_page_form_separate_literal_method_passages():
    from services.deep_research.section_context import include_pdf_method_passages

    r = {**record(), 'localSectionContextContractVersion':9, 'sourcePolicy':{'mode':'task_only'},
         'materials':[{'materialId':'p'}], 'question':'给新手解释训练采样和匹配，限300字。',
         'audienceFirstContractVersion':4, 'audienceRewriteContractVersion':9,
         'audiencePublicationBudgetContractVersion':1, 'reportPresentationContractVersion':4}
    material = {'materialId':'p','contentHash':'a'*64,'versionId':'p-v1','title':'ACME: Image Processing'}
    a = 'Feature distributionP (F|I). We sample a feature from each region and retain it using its detection probability.\n'
    b = 'Match distribution P(M|F). We sample forward and backward matches with probabilities based on descriptor distances.\n'
    text = '3 Method\n'+a+b+'4 Experiments\n'+('Matching sampling benchmark. '*8)
    pages = [{'page':3,'text':text}]
    sources = include_pdf_method_passages([],pages,r,'feature sampling match probabilities',material,3)
    assert {source['text'] for source in sources} == {a,b}
    assert {source['location']['section'] for source in sources} == {'3 Method / Feature distribution','3 Method / Match distribution'}
    assert all(text.startswith(source['text'],source['location']['offset']) for source in sources)
    legacy = include_pdf_method_passages([],pages,{**r,'localSectionContextContractVersion':8},
                                         'feature sampling match probabilities',material,3)
    assert len(legacy) == 1 and legacy[0]['location']['section'] == '3 Method'
