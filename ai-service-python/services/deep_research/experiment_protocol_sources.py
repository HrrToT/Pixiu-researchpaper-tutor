"""Bounded navigation to literal experiment prerequisites in an owned PDF."""

import hashlib
import re

from services.deep_research.obligation_binding import eligible_obligation_ids

MARKER = 'sharedExperimentProtocolEvidenceVersion'
DENSIFICATION_MARKER = 'sharedExperimentDensificationEvidenceVersion'
BASELINE_CONFIG_MARKER = 'sharedExperimentBaselineConfigVersion'
OPACITY = 'opacity_schedule'
MEMBERSHIP = 'dataset_membership'
OPACITY_CONTINUATION = 'opacity_schedule_continuation'
DENSIFICATION = 'gaussian_densification_operations'
EXISTING_ABLATION = 'gaussian_densification_existing_ablation'
INITIALIZATION = 'gaussian_covariance_initialization'

_OPACITY_REQUEST = re.compile(r'\bopacity\b|不透明度', re.I)
_COMPLETE_SCHEDULE = re.compile(
    r'\b(?:every|at intervals of)\s*(?:[Nn𝑁]\s*=\s*)?\d[\d, ]*\s*(?:iterations?|steps?)\b'
    r'|每\s*\d[\d, ]*\s*(?:次迭代|步)', re.I)
_OPEN_SCHEDULE = re.compile(r'\bevery\s+[Nn𝑁]\s*=\s*\d+(?:,\d{3})*\b', re.I)
_CONTINUATION = re.compile(
    r'\b(?:iterations|steps)\.\s+(?:The\s+)?(?:optimization|training)'
    r'\b.{0,105}?(?:opacity|alpha|[α𝛼])[^.!?]{0,110}', re.I | re.S)
_OPACITY_ACTION = re.compile(
    r'\b(?:reset\w*|set|clamp\w*)\b.{0,48}(?:opacity|alpha|[α𝛼])'
    r'|\bopacity\b.{0,32}\b(?:reset\w*|set|clamp\w*)\b|不透明度.{0,20}(?:重置|设为)', re.I)
_SCENE_LIST = re.compile(
    r'\b(?:scenes|sequences|samples)\s+(?:are|include)\b.{0,55}?[:：]?\s*'
    r'[A-Z][\w-]+\s*,\s*[A-Z][\w-]+.{0,210}?\b(?:from|of|in)\s+(?:the\s+)?[\w-]+\s+dataset\b',
    re.I)
_GAUSSIAN = re.compile(r'\bgaussians?\b|高斯', re.I)
_CLONE = re.compile(r'\bclon\w*\b|克隆', re.I)
_SPLIT = re.compile(r'\bsplit\w*\b|分裂', re.I)
_ABLATION = re.compile(r'\bablat\w*\b|消融', re.I)
_ABLATION_METHOD = re.compile(
    r'\bdensification methods\b.{0,160}?\bclone\s+and\s+split\b.{0,130}?'
    r'\bdisable each method separately\b.{0,100}?\brest of\s+the method unchanged\.',
    re.I | re.S)
_ABLATION_CAPTION = re.compile(
    r'\bAblation of densification strategy\b.{0,110}?["“]clone["”]\s+and\s+["“]split["”]',
    re.I | re.S)
_INITIALIZATION_REQUEST = re.compile(r'\binitiali[sz]\w*\b|初始化|初值|共同起点', re.I)
_COVARIANCE_INITIALIZATION = re.compile(r'\binitial covariance matrix\b.{0,130}\bisotropic Gaussian\b', re.I)
_DENSIFICATION_PASSAGE = re.compile(
    r'\b(?:Since both cases are good candidates for densification.{0,310}?)?'
    r'For small Gaussians\b.{0,290}?\bclone\b.{0,180}?direction\s+of\s+the\s+positional\s+gradient\.'
    r'.{0,190}?\bsplit\b.{0,110}?\breplace\b.{0,160}?\bscale\b.{0,175}?'
    r'\boriginal\s+3D\s+Gaussian\s+as\s+a\s+PDF\s+for\s+sampling\.',
    re.I | re.S)
_NAMED_BASELINE = re.compile(r'(?:以|基于|按照)\s*([A-Za-z][\w.-]*)\s*论文[的中]?([^，。；]{1,80}?)(?:设置|配置)')
_MODEL_SIZE = re.compile(r'\b[A-Za-z][A-Za-z0-9._-]*[- ]\d+(?:\.\d+)?B\b', re.I | re.ASCII)
_CONFIG_CAPTION = re.compile(r'\bTable\s+\d+[.:]\s*Hyperparameter\b', re.I)
_CONFIG_FIELDS = re.compile(r'\b(?:Optimizer|Learning Rate|LR)\b', re.I)
_TRAINING_BUDGET_FIELDS = re.compile(r'\b(?:Epochs?|Batch Size|Warmup Steps?)\b', re.I)
BASELINE_SPLIT = 'baseline_training_and_test_split'
BASELINE_TASKS = 'baseline_tasks_and_metric'
_COMMONSENSE = re.compile(r'常识推理|\bcommonsense\s+reasoning\b', re.I)
_BASELINE_SPLIT = re.compile(
    r'The commonsense reasoning tasks comprise\s+\d+\s+sub-?tasks,\s*'
    r'each with a predefined training and testing set\..{0,400}?'
    r'evaluations? on the individual testing dataset\s+for each task\.', re.I | re.S,
)
_RESULT_TABLE = re.compile(
    r'Table\s+(\d+)[.:]\s+Accuracy comparison[^\n]{0,200}\bcommonsense reasoning datasets\.'
    r'.{0,400}?\n[ \t]*Model\s+PEFT Method[^\n]+', re.I | re.S,
)


def enabled(record):
    return type(record.get(MARKER)) is int and record[MARKER] == 1


def densification_enabled(record):
    version = record.get(DENSIFICATION_MARKER)
    return type(version) is int and version in (1, 2)


def ablation_requested(record):
    version = record.get(DENSIFICATION_MARKER)
    if type(version) is not int or version != 2:
        return False
    from services.deep_research.request_context import effective_question
    question = effective_question(record)
    return all(pattern.search(question) for pattern in (_GAUSSIAN, _CLONE, _SPLIT, _ABLATION))


def roles(obligation, *, densification=False, existing_ablation=False):
    if obligation.get('dataPrerequisiteContractVersion') == 1:
        return (MEMBERSHIP,)
    text = obligation.get('searchQuery') or obligation.get('question', '')
    result = (OPACITY,) if _OPACITY_REQUEST.search(text) else ()
    if densification and _GAUSSIAN.search(text):
        if _CLONE.search(text) and _SPLIT.search(text):
            result = (*result, DENSIFICATION)
        if _INITIALIZATION_REQUEST.search(text):
            result = (*result, INITIALIZATION)
    if existing_ablation and (_ABLATION.search(text) or _ABLATION.search(obligation.get('question', ''))):
        result = (*result, EXISTING_ABLATION)
    return result


def query_roles(record, query, material_id):
    existing_ablation = ablation_requested(record)
    return tuple(dict.fromkeys(
        role for item in record['state'].get('plan', []) for obligation in item['obligations']
        if query in (obligation.get('searchQuery'), obligation.get('question'))
        and (not obligation.get('requiredSources') or material_id in obligation['requiredSources'])
        for role in roles(obligation, densification=densification_enabled(record), existing_ablation=existing_ablation)
    ))


def matches(text, role):
    if role == DENSIFICATION:
        return densification_range(text) is not None
    if role == EXISTING_ABLATION:
        return ablation_range(text) is not None
    body = ' '.join(text.split())
    if role == INITIALIZATION:
        return bool(_COVARIANCE_INITIALIZATION.search(body))
    if role == OPACITY:
        return any(_OPACITY_ACTION.search(body[max(0, hit.start() - 120):hit.end() + 72])
                   for pattern in (_COMPLETE_SCHEDULE, _OPEN_SCHEDULE) for hit in pattern.finditer(body))
    if role == OPACITY_CONTINUATION:
        return bool(_CONTINUATION.search(body))
    return role == MEMBERSHIP and bool(_SCENE_LIST.search(body))


def companion(first, rows, field):
    """Keep cross-page units separate and restricted to the same document version."""
    page = first.get('location', {}).get('page')
    if (type(page) is not int or _COMPLETE_SCHEDULE.search(' '.join(first[field].split()))
            or not (first.get('versionId') or first.get('sourceVersionId'))):
        return None
    identity_keys = ('pdfId', 'workId', 'versionId', 'sourceWorkId', 'sourceVersionId', 'ownerMaterialId')
    return next((row for row in rows if row.get('location', {}).get('page') == page + 1
                 and all(row.get(key) == first.get(key) for key in identity_keys)
                 and matches(row[field], OPACITY_CONTINUATION)), None)


def continuation_spans(sources):
    """Preserve the original unit and following action across sentence splitting."""
    tails = [row for row in sources if row.get('accessLevel') == 'fulltext'
             and matches(row['text'], OPACITY_CONTINUATION)]
    result = set()
    for row in sources:
        if row.get('accessLevel') == 'fulltext' and matches(row['text'], OPACITY):
            adjacent = companion(row, tails, 'text')
            if adjacent:
                result.add(adjacent['sourceId'])
    return result


def continuation_range(text):
    match = _CONTINUATION.search(text)
    return match.span() if match else None


def densification_range(text):
    match = _DENSIFICATION_PASSAGE.search(text)
    return match.span() if match else None


def ablation_range(text):
    match = _ABLATION_METHOD.search(text)
    return match.span() if match else None


def has_passage(rows, role):
    owned = [row for row in rows if row.get('accessLevel') == 'fulltext']
    return any(matches(row['text'], role) and (role != OPACITY
               or _COMPLETE_SCHEDULE.search(' '.join(row['text'].split()))
               or companion(row, owned, 'text')) for row in owned)


def include_passages(rows, passages, requested, limit):
    """Protect the lead hit and use one existing slot per missing role."""
    selected = list(rows[:limit])
    protected = {row['sourceId'] for row in selected[:1]}
    for role in requested:
        current = next((row for row in selected if row.get('accessLevel') == 'fulltext'
                        and matches(row['text'], role)), None)
        if role == OPACITY and current and not has_passage(selected, role):
            # A PDF anchor can carry the matching document version needed to
            # read its physical continuation. An index chunk may lack it.
            current = None
        candidate = current or next((row for row in passages if matches(row['text'], role)), None)
        if candidate is None:
            continue
        protected.add(candidate['sourceId'])
        adjacent = companion(candidate, [*selected, *passages], 'text') if role == OPACITY else None
        if adjacent:
            protected.add(adjacent['sourceId'])
        for row in (candidate, adjacent):
            if row is None or any(item['sourceId'] == row['sourceId'] for item in selected):
                continue
            if len(selected) >= limit:
                index = next((i for i in reversed(range(len(selected)))
                              if selected[i]['sourceId'] not in protected and not selected[i].get('tableData')), None)
                if index is None:
                    continue
                selected.pop(index)
            selected.append(row)
    return selected


def preferred_reads(sources, obligations, limit, extracted, *, densification=False, baseline_evaluation=False,
                    existing_ablation=False):
    selected = {}
    if baseline_evaluation:
        for part in (BASELINE_SPLIT, BASELINE_TASKS):
            source = next((row for row in sources if row.get('accessLevel') == 'fulltext'
                           and row.get('location', {}).get('baselineEvaluationPart') == part
                           and (row['sourceId'], row.get('contentHash')) not in extracted
                           and eligible_obligation_ids(row, obligations)), None)
            if source:
                selected[source['sourceId']] = source
    roles_with_preference = []
    order = (DENSIFICATION, INITIALIZATION, OPACITY, MEMBERSHIP) if densification else (OPACITY, MEMBERSHIP)
    if existing_ablation:
        order = (*order, EXISTING_ABLATION)
    for role in order:
        eligible = {oid: row for oid, row in obligations.items()
                    if role in roles(row, densification=densification, existing_ablation=existing_ablation)}
        source = next((row for row in sources if row.get('accessLevel') == 'fulltext'
                       and (row['sourceId'], row.get('contentHash')) not in extracted
                       and eligible_obligation_ids(row, eligible) and matches(row['text'], role)), None)
        if source:
            selected[source['sourceId']] = source
            roles_with_preference.append(role)
            adjacent = companion(source, [row for row in sources if eligible_obligation_ids(row, eligible)], 'text') if role == OPACITY else None
            if adjacent and (adjacent['sourceId'], adjacent.get('contentHash')) not in extracted:
                selected[adjacent['sourceId']] = adjacent
    extra = int(DENSIFICATION in roles_with_preference and INITIALIZATION in roles_with_preference)
    extra += int(EXISTING_ABLATION in roles_with_preference)
    return list(selected.values())[:limit // 3 + extra]


def premise_bundles(candidates, obligations, *, densification=False):
    bundles = []
    for role in ((DENSIFICATION, OPACITY, MEMBERSHIP, INITIALIZATION) if densification else (OPACITY, MEMBERSHIP)):
        ids = {oid for oid, row in obligations.items() if role in roles(row, densification=densification)}
        eligible = [item for item in candidates if item.get('accessLevel') == 'fulltext'
                    and item.get('verification', {}).get('literal') == 'passed'
                    and ids.intersection(item.get('obligationIds', []))]
        row = next((item for item in eligible if matches(item['quote'], role)), None)
        if row:
            adjacent = companion(row, eligible, 'quote') if role == OPACITY else None
            bundles.append({'evidenceIds': [row['evidenceId'], *([adjacent['evidenceId']] if adjacent else [])]})
    return bundles


def ablation_bundles(candidates, obligations, materials):
    """Keep the literal ablation procedure and its same-version caption when available."""
    ids = {oid for oid, row in obligations.items() if EXISTING_ABLATION in roles(row, existing_ablation=True)}
    owned = {(m.get('materialId'), m.get('versionId') or m.get('contentHash'), m.get('contentHash'))
             for m in materials if m.get('materialId') and m.get('contentHash')}
    def identity(row):
        return row.get('ownerMaterialId'), row.get('sourceVersionId'), row.get('contentHash')

    rows = [row for row in candidates if identity(row) in owned
            and row.get('sourceWorkId') and row.get('accessLevel') == 'fulltext'
            and row.get('verification', {}).get('literal') == 'passed'
            and row.get('location', {}).get('pageResolution') == 'exact'
            and type(row['location'].get('page')) is int
            and ids.intersection(row.get('obligationIds', []))]
    bundles = []
    seen = set()
    for method in rows:
        key = identity(method)
        if key in seen or not matches(method['quote'], EXISTING_ABLATION):
            continue
        seen.add(key)
        page = method['location']['page']
        caption = next((row for row in rows if identity(row) == key
                        and row['sourceWorkId'] == method['sourceWorkId']
                        and row['location']['page'] in (page, page + 1)
                        and _ABLATION_CAPTION.search(row['quote'])), None)
        bundle_ids = [method['evidenceId']]
        if caption and caption['evidenceId'] != method['evidenceId']:
            bundle_ids.append(caption['evidenceId'])
        bundles.append({'evidenceIds': bundle_ids, 'literalQuotesSufficient': True})
    return bundles


def _named_baseline(question, paper_titles):
    anchor = _NAMED_BASELINE.search(question)
    if not anchor or not (model := _MODEL_SIZE.search(anchor[2])):
        return None
    owner_name = anchor[1].casefold()
    owners = [owner for owner, title in paper_titles.items()
              if title and (title.casefold() == owner_name or title.casefold().startswith(owner_name + ':'))]
    if len(owners) != 1:
        return None
    return owners[0], model[0], anchor[2]


def baseline_configuration_bundles(candidates, question, paper_titles):
    """Retain a named baseline's caption and data, bound to the same owned page."""
    baseline = _named_baseline(question, paper_titles)
    if not baseline:
        return []
    owner, model, _ = baseline
    model_name = re.compile(r'(?<![\w-])' + re.escape(model) + r'(?![\w-])', re.I)
    rows = [row for row in candidates if row.get('ownerMaterialId') == owner
            and row.get('accessLevel') == 'fulltext'
            and row.get('verification', {}).get('literal') == 'passed'
            and row.get('sourceVersionId') and row.get('sourceContext')
            and type(row.get('location', {}).get('page')) is int]
    for caption in rows:
        if not (_CONFIG_CAPTION.search(caption['quote']) and model_name.search(caption['quote'])):
            continue
        values = next((row for row in rows if row.get('sourceVersionId') == caption['sourceVersionId']
                       and row['location']['page'] == caption['location']['page']
                       and row.get('sourceContext') == caption.get('sourceContext')
                       and model_name.search(row['quote']) and _CONFIG_FIELDS.search(row['quote'])
                       and _TRAINING_BUDGET_FIELDS.search(row['quote'])), None)
        if values:
            return [{'evidenceIds': list(dict.fromkeys((caption['evidenceId'], values['evidenceId'])))}]
    return []


def baseline_evaluation_requested(record, query, material_id):
    if (record.get(BASELINE_CONFIG_MARKER) != 2 or record.get('state', {}).get('outputKind') != 'experiment_design'
            or not _COMMONSENSE.search(query)):
        return None
    from services.deep_research.request_context import effective_question
    baseline = _named_baseline(effective_question(record),
        {row['materialId']:row.get('title') for row in record.get('materials', [])})
    if not baseline or baseline[0] != material_id or not _COMMONSENSE.search(baseline[2]):
        return None
    return baseline[1]


def baseline_evaluation_passages(pages, material, model):
    """Keep the paper's split statement and the header of the linked accuracy table."""
    splits = [(page, match) for page in pages for match in _BASELINE_SPLIT.finditer(page['text'])]
    if len(splits) != 1:
        return []
    page, split = splits[0]
    after = page['text'][split.end():split.end()+1000]
    table = re.search(r'\bTable\s+(\d+)\b', after)
    if not table:
        return []
    model_name = re.compile(r'\b' + re.escape(model).replace(r'\-', r'[-\s]*') + r'\b', re.I)
    tables = [(body, match) for body in pages for match in _RESULT_TABLE.finditer(body['text'])
              if match[1] == table[1] and model_name.search(match[0])]
    if len(tables) != 1:
        return []
    entries = [(page, split, BASELINE_SPLIT), (*tables[0], BASELINE_TASKS)]
    material_id, content_hash = material['materialId'], material['contentHash']
    out = []
    for body, match, part in entries:
        location = {'page':body['page'], 'pageIndex':body['page']-1, 'pageResolution':'exact',
                    'offset':match.start(), 'baselineEvaluationPart':part}
        identity = hashlib.sha256(f'{material_id}:{content_hash}:{location}'.encode()).hexdigest()
        out.append({'sourceId':'src_'+identity, 'pdfId':material_id, 'text':match[0],
                    'location':location, 'contentHash':content_hash,
                    'versionId':material.get('versionId') or content_hash,
                    'title':material.get('title', material_id), 'accessLevel':'fulltext'})
    return out


def baseline_evaluation_bundles(candidates, question, paper_titles):
    baseline = _named_baseline(question, paper_titles)
    if not baseline or not _COMMONSENSE.search(baseline[2]):
        return []
    rows = {part: [row for row in candidates if row.get('ownerMaterialId') == baseline[0]
                   and row.get('accessLevel') == 'fulltext'
                   and row.get('verification', {}).get('literal') == 'passed'
                   and row.get('location', {}).get('baselineEvaluationPart') == part]
            for part in (BASELINE_SPLIT, BASELINE_TASKS)}
    for split in rows[BASELINE_SPLIT]:
        table = next((row for row in rows[BASELINE_TASKS]
                      if row.get('sourceVersionId') == split.get('sourceVersionId')
                      and row.get('contentHash') == split.get('contentHash')), None)
        if table:
            return [{'evidenceIds':[split['evidenceId'],table['evidenceId']]}]
    return []


def retain_baseline_evaluation(rows, additions, limit):
    if not additions or limit < 3:
        return rows
    ids = {row['sourceId'] for row in additions}
    existing = [row for row in rows if row['sourceId'] not in ids]
    protected = [row for i, row in enumerate(existing) if i == 0 or row.get('tableData')]
    if len(protected) + len(additions) > limit:
        return rows
    available = limit - len(additions)
    while len(existing) > available:
        index = next(i for i in reversed(range(len(existing))) if existing[i] not in protected)
        existing.pop(index)
    return [*existing, *additions]
