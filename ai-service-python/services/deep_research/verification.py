"""Fail-closed evidence checks, separate from model judgements."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable

from services.deep_research.asset_availability import requires_existing_asset, enforce_asset_prerequisites

_MIP_NERF_360 = re.compile(r'(?<![A-Za-z0-9_])Mip[-‐‑–]NeRF\s*360(?![A-Za-z0-9_]|[.,][0-9])', re.I)
_SCENE_MEMBERSHIP = re.compile(r'(列为[^，。；！？\r\n]{1,80}?数据集的)一个场景(?=[，。；！？\r\n]|\s*$)')
_RUNNING_PAGE_LABEL = re.compile(r'•\s*\d+:\d+(?=[ \t]*(?:\r?\n|$))')


def normalize_quote(text: str) -> str:
    # Whitespace is the only permitted transformation of an exact quotation.
    return re.sub(r"\s+", " ", text).strip()


def evidence_id(source: dict, quote: str, location: dict) -> str:
    identity = [source["workId"], source["versionId"], source["contentHash"], location, quote]
    return "ev_" + hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def make_evidence(source: dict, quote: str, original: str, *, location: dict,
                  obligation_ids: list[str], conditions: dict | None = None) -> dict:
    for key in ("workId", "versionId", "contentHash", "accessLevel"):
        if not isinstance(source.get(key), str) or not source[key]:
            raise ValueError(f"Evidence source missing {key}")
    if source["accessLevel"] not in {"fulltext", "abstract", "user_note"}:
        raise ValueError("Metadata is not textual evidence")
    normalized = normalize_quote(quote)
    if not normalized or normalized not in normalize_quote(original):
        raise ValueError("Quotation does not match original source")
    return {"evidenceId": evidence_id(source, quote, location), "sourceWorkId": source["workId"],
            "sourceVersionId": source["versionId"], "contentHash": source["contentHash"],
            "accessLevel": source["accessLevel"], "quote": quote, "location": dict(location),
            "obligationIds": list(dict.fromkeys(obligation_ids)), "conditions": dict(conditions or {}),
            "sourceContext": original,
            "verification": {"literal": "passed", "semantic": "unchecked"}}


def _measurement_numbers(text: str, *, word_counts=False, relative_references=False, artifact_references=False,
                         conceptual_articles=False, expanded_counts=False,dimensional_labels=False,
                         collection_articles=False,enumeration_labels=False,surface_dimensional_labels=False,
                         geometric_collection_articles=False, explicit_quantity_phrases=False) -> set[str]:
    # Dimensional method labels are not measured quantities. The semantic
    # verifier still checks their identity; standalone dimensions stay checked.
    text = re.sub(r'(?<![A-Za-z0-9_])[234]D(?:-?[A-Za-z]+)?(?![A-Za-z0-9_])', '', text)
    if dimensional_labels:
        from services.deep_research.measurement_numbers import without_dimensional_labels
        text=without_dimensional_labels(text,surface_labels=surface_dimensional_labels)
    if enumeration_labels:
        from services.deep_research.enumeration_labels import without_enumeration_labels
        text=without_enumeration_labels(text,balanced_parentheses=type(enumeration_labels) is int and enumeration_labels in (8,9),numbered_items=type(enumeration_labels) is int and enumeration_labels==9)
    text = re.sub(r'(?<![A-Za-z])Table\s+\d+(?![A-Za-z0-9])|表\s*\d+', '', text, flags=re.I)
    from services.deep_research.measurement_numbers import (
        measurement_numbers, normalize_explicit_quantity_phrases,
        normalize_interpolation_kernel_labels, split_dimension_series,
    )
    dimensions = set()
    if explicit_quantity_phrases:
        text = normalize_explicit_quantity_phrases(text, shared_range_scale=explicit_quantity_phrases >= 17,
                                                   gaussian_replacement_counts=explicit_quantity_phrases == 18 or explicit_quantity_phrases >= 22,
                                                   image_pair_articles=explicit_quantity_phrases >= 19,
                                                   explicit_forward_pass=explicit_quantity_phrases >= 20,
                                                   explicit_sh_band_schedule=explicit_quantity_phrases >= 22,
                                                   evaluation_counts=explicit_quantity_phrases >= 23,
                                                   gaussian_figure_split=explicit_quantity_phrases == 24,
                                                   thousands_of_iterations=explicit_quantity_phrases == 25)
        if explicit_quantity_phrases >= 20:
            text, dimensions = split_dimension_series(text)
        if explicit_quantity_phrases >= 21:
            text = normalize_interpolation_kernel_labels(text)
    return dimensions | measurement_numbers(text, word_counts=word_counts, relative_references=relative_references,
                               artifact_references=artifact_references, conceptual_articles=conceptual_articles,
                               expanded_counts=expanded_counts,chinese_factors=dimensional_labels,
                               collection_articles=collection_articles,
                               **({'geometric_collection_articles':geometric_collection_articles} if geometric_collection_articles else {}))


def _condition_values_text(value):
    # Pure numeric dictionary keys are labels (models may use "1", "2").
    # Other keys can themselves assert a quantity; retain those and every
    # nested value rather than globally erasing metadata digits.
    if isinstance(value, dict):
        return ' '.join(('' if isinstance(key, str) and key.isdigit() else str(key))
                        + ' ' + _condition_values_text(item) for key, item in value.items())
    if isinstance(value, list):
        return ' '.join(_condition_values_text(item) for item in value)
    return str(value) if value is not None else ''


def _table_display_diagnostic(claim, support,comparison_context=None):
    from services.deep_research.table_bindings import bound_table_context
    required = []
    for cell in bound_table_context(claim, support):
        identity = {'group': cell['group'], 'method': cell['method']}
        if identity not in required:
            required.append(identity)
    if comparison_context is not None:
        from services.deep_research.comparison_table_context import author_headers
        headers=author_headers(claim,support,comparison_context)
        if headers:
            return {'requiredTableDisplay':required,
                'authorMethodColumn':next(iter(headers.values())),
                'detail':'数据组、指标和数值仍需同条显示。原表普通Ours行可由已绑定的同论文列标题表示；'
                    '其他方法、基线、星号和变体仍需保留其明确身份。列标题不是科学通过依据。'}
    return {'requiredTableDisplay': required,
        'detail': '保留表格数值时，同条正文或条件必须显示原表的数据组和方法身份。'
            '请核对requiredTableDisplay；保留星号、变体及分组层级，末尾参考文献序号可省略。'
            '不能只写另一个方法名代替Ours等原表标签，也不能修改单元格或加入未报告的计算。'}


_TEST_IMAGE_ORDINAL = re.compile(
    r'\b(?:taking|selecting|using|take|select|use)\s+every\s+([1-9]\d*)(?:st|nd|rd|th)'
    r'\s+(?:photo(?:graph)?|image)\s+for\s+(?:the\s+)?test(?:ing)?\b', re.I,
)
_TEST_IMAGE_SAMPLE = re.compile(
    r'(每(?:隔)?\s*([1-9]\d*)\s*(?:张(?:照片|图像|图片)|幅(?:图像|图片))\s*(?:抽取|选取|留出|取)\s*)'
    r'(?:1|一)(?=\s*(?:张|幅)(?:照片|图像|图片)?\s*(?:作为|用于|做|供)?测试)',
)


def precheck_claims(claims: list[dict], evidence: list[dict], *, absence_scope_version=0,
                    quantity_spelling_version=0, feedback_version=0, table_references_version=0,
                    requested_source_revisions=None,comparison_context=None,bound_duration_spelling=False,
                    comparison_embedded_measurements=False, bound_composite_cells=False,
                    bind_composite_revisions=False, named_revision_table=None, numeric_context=None,
                    cited_passage_scope=False, named_revision_question=None, test_image_sampling=False,
                    dataset_scene_membership=False) -> dict:
    """Pure hard checks shared by publication and pre-classification edits.

    Candidates still require a separate semantic verdict; nothing is accepted
    for publication here and no provider-capable callback is invoked.
    """
    if type(bound_duration_spelling) is not bool:raise ValueError('Invalid bound duration spelling policy')
    if type(bound_composite_cells) is not bool:
        raise ValueError('Invalid composite table cell policy')
    if type(bind_composite_revisions) is not bool or (bind_composite_revisions and not bound_composite_cells):
        raise ValueError('Invalid composite table revision policy')
    if type(comparison_embedded_measurements) is not bool:raise ValueError('Invalid comparison measurement policy')
    if requested_source_revisions is not None:
        from services.deep_research.source_revisions import validate_constraints
        validate_constraints(requested_source_revisions)
    by_id = {item["evidenceId"]: item for item in evidence}
    if len(by_id) != len(evidence):
        raise ValueError("Duplicate evidence identity")
    candidates, rejected, seen = [], [], set()
    spelling = quantity_spelling_version if type(quantity_spelling_version) is int and 1 <= quantity_spelling_version <= 25 else 0
    word_counts = spelling >= 1
    relative_references = spelling >= 2
    artifact_references = spelling >= 3
    conceptual_articles = spelling >= 4
    dimensional_labels = spelling >= 5
    collection_articles = spelling >= 6
    enumeration_labels = min(spelling, 9) if spelling >= 7 else False
    surface_labels = 4 if spelling >= 15 else 3 if spelling >= 13 else 2 if spelling >= 11 else spelling == 10
    geometric_articles = 2 if spelling >= 14 else spelling in (12, 13)
    explicit_quantity_phrases = spelling if spelling >= 16 else False
    concurrent_feedback = type(feedback_version) is int and feedback_version == 2
    for claim in claims:
        claim_id = claim.get("claimId")
        reason = ""
        unsupported_numbers = set()
        binding_reason = None
        if not claim_id or claim_id in seen:
            reason = "invalid_identity"
        seen.add(claim_id)
        kind = claim.get("kind")
        refs = claim.get("evidenceRefs", [])
        if kind not in {"reported", "inference", "suggestion", "proposal", "hypothesis"} or not claim.get("text"):
            reason = reason or "invalid_claim"
        if not isinstance(refs, list) or any(ref not in by_id for ref in refs):
            reason = reason or "unknown_evidence"
        support = [by_id[ref] for ref in refs if ref in by_id] if isinstance(refs, list) else []
        mismatched_revisions=[item for item in support if requested_source_revisions
            and item.get('sourceWorkId') in requested_source_revisions
            and item.get('sourceVersionId') not in requested_source_revisions[item['sourceWorkId']]]
        if mismatched_revisions:
            reason=reason or 'requested_version_mismatch'
        if kind in {"reported", "inference"} and not support:
            reason = reason or "missing_evidence"
        if any(item.get("verification", {}).get("literal") != "passed" for item in support):
            reason = reason or "unverified_quotation"
        from services.deep_research.prose_checks import absence_not_established, leaks_internal_reference
        if absence_not_established(claim, support, scope_version=absence_scope_version,
                                   cited_passage_scope=cited_passage_scope):
            reason = reason or 'absence_not_established'
        if type(absence_scope_version) is int and absence_scope_version in (6,7,8,9):
            from services.deep_research.result_scope import purpose_not_established
            if purpose_not_established(claim,support):
                reason=reason or 'result_purpose_not_established'
        if leaks_internal_reference(claim, support,table_aliases=type(absence_scope_version) is int and absence_scope_version in (6,7,8)):
            reason = reason or 'internal_reference_in_prose'
        declared_reference_error=None
        if kind in {'inference','proposal','suggestion','hypothesis'} and type(table_references_version) is int and table_references_version in (1,2,3,4):
            from services.deep_research.table_bindings import validate_declared_references
            declared_reference_error=validate_declared_references(claim,support)
            reason=reason or declared_reference_error
        if kind in {'reported', 'inference'}:
            from services.deep_research.condition_identity import unsupported_device_condition
            if unsupported_device_condition(claim, support):
                reason = reason or 'uncited_device_condition'
        if kind == "reported":
            if any(item.get("accessLevel") == "abstract" for item in support) and claim.get("detailLevel") != "abstract":
                reason = reason or "abstract_only"
            claim_text = claim.get("text", "") + " " + _condition_values_text(claim.get("conditions") or {})
            # Numbers in parser-established dataset names are identifiers, not
            # measurements (e.g. Mip-NeRF 360). Remove the entire exact label,
            # not its digits globally; wrong numerical claims still fail.
            from services.deep_research.table_bindings import dataset_label
            from services.deep_research.table_evidence import visible_table_packet
            for item in support:
                packet = visible_table_packet(item.get('tableData'), item.get('quote', ''))
                for dataset, _ in packet['groups'] if packet else []:
                    for label in (dataset, dataset_label(dataset)):
                        if any(ch.isalpha() for ch in label):
                            pattern = r'(?<![A-Za-z0-9])' + re.escape(label).replace(r'\ ', r'\s*') + r'(?![A-Za-z0-9])'
                            claim_text = re.sub(pattern, '', claim_text, flags=re.I)
            for item in support:
                # Strip only complete, established identities, longest first.
                # Removing a work-ID prefix from arxiv:...v4 leaves a spurious
                # measurement of 4; an uncited version must remain checked.
                identities = {item.get('sourceWorkId', ''), item.get('sourceVersionId', '')}
                if bind_composite_revisions:
                    from services.deep_research.bound_composite_table_cells import evidence_revision
                    revision = evidence_revision(item)
                    if revision:
                        identities.add(revision)
                for identity in sorted(identities, key=len, reverse=True):
                    if re.fullmatch(r'arxiv:\d{4}\.\d{4,5}(?:v\d+)?', identity, re.I):
                        pattern = r'(?<![A-Za-z0-9_])' + re.escape(identity) + r'(?![A-Za-z0-9_.])'
                        claim_text = re.sub(pattern, '', claim_text, flags=re.I)
            source_texts = [item['quote'] for item in support]
            if spelling >= 23 and any(_MIP_NERF_360.search(text) for text in source_texts):
                # PDF body text commonly joins this benchmark's name. Match
                # the cited identity and exclude it on both sides of the numeric check.
                claim_text = _MIP_NERF_360.sub('', claim_text)
                source_texts = [_MIP_NERF_360.sub('', text) for text in source_texts]
            if numeric_context:
                source_texts.extend(text for item in support for text in numeric_context.get(item['evidenceId'], ()))
            if dataset_scene_membership:
                # Membership says which dataset contains the scene. It does not
                # report a count. A running article/page label supplies no count.
                claim_text = _SCENE_MEMBERSHIP.sub(r'\1场景之一', claim_text)
                source_texts = [_RUNNING_PAGE_LABEL.sub('', text) for text in source_texts]
            if test_image_sampling:
                # An exact held-out ordinal expresses one selected image per stride.
                # Remove that translated count only, never the stride or unrelated numbers.
                strides = {stride for text in source_texts for stride in _TEST_IMAGE_ORDINAL.findall(text)
                           if stride != '1'}
                claim_text = _TEST_IMAGE_SAMPLE.sub(
                    lambda match: match[1] if match[2] in strides else match[0], claim_text)
            if conceptual_articles:
                from services.deep_research.measurement_numbers import parameter_identifiers, without_parameter_identifiers
                known = set().union(*(parameter_identifiers(text) for text in source_texts))
                claim_text = without_parameter_identifiers(claim_text, known)
                source_texts = [without_parameter_identifiers(text) for text in source_texts]
            if bound_duration_spelling:
                from services.deep_research.table_bindings import normalize_bound_duration_spelling
                claim_text = normalize_bound_duration_spelling(claim_text,claim,support)
            numbers = _measurement_numbers(claim_text, word_counts=word_counts, relative_references=relative_references,
                                          artifact_references=artifact_references, conceptual_articles=conceptual_articles,
                                          expanded_counts=conceptual_articles,dimensional_labels=dimensional_labels,
                                          collection_articles=collection_articles,enumeration_labels=enumeration_labels,
                                          surface_dimensional_labels=surface_labels,
                                          explicit_quantity_phrases=explicit_quantity_phrases,
                                          **({'geometric_collection_articles':geometric_articles} if geometric_articles else {}))
            original_numbers = set().union(*(_measurement_numbers(text, word_counts=word_counts,
                relative_references=relative_references, artifact_references=artifact_references,
                conceptual_articles=conceptual_articles, expanded_counts=conceptual_articles,
                dimensional_labels=dimensional_labels,collection_articles=collection_articles,
                enumeration_labels=enumeration_labels,surface_dimensional_labels=surface_labels,
                explicit_quantity_phrases=explicit_quantity_phrases,
                **({'geometric_collection_articles':geometric_articles} if geometric_articles else {})) for text in source_texts))
            if not numbers <= original_numbers:
                reason = reason or "numeric_mismatch"
                unsupported_numbers = numbers - original_numbers
            from services.deep_research.table_bindings import validate_table_bindings
            table_options = {'bound_duration_spelling':True} if bound_duration_spelling else {}
            if bound_composite_cells:
                table_options['bound_composite_cells'] = True
            if bind_composite_revisions:
                table_options['bind_composite_revisions'] = True
            if comparison_context is not None:
                table_options['comparison_context']=comparison_context
            if type(table_references_version) is int and table_references_version in (2,3,4):
                table_options['translated_metrics'] = True
                if table_references_version in (3,4):
                    table_options['dataset_joiners'] = True
            if concurrent_feedback:
                # A fixed numeric error must not hide the next known failure
                # from the one bounded revision. Legacy short-circuit stays.
                binding_reason = validate_table_bindings(claim, support, **table_options)
                reason = reason or binding_reason
            else:
                reason = reason or validate_table_bindings(claim, support, **table_options)
        if named_revision_table and kind in {'reported', 'inference'}:
            from services.deep_research.revision_table_display import broadens_common_setting, contradictory_revision_values
            if contradictory_revision_values(claim, support, named_revision_table):
                reason = reason or 'table_revision_value_mismatch'
            if named_revision_question and broadens_common_setting(claim, support, named_revision_table, named_revision_question):
                reason = reason or 'table_revision_setting_outside_request'
        if comparison_embedded_measurements and kind in {'inference', 'proposal', 'suggestion', 'hypothesis'}:
            # Ordinary comparison advice can embed reported measurements. Its
            # label cannot waive exact table identity/display checks. This is
            # not the experimental-design path and does not prove semantics.
            table_options = {'bound_duration_spelling': bound_duration_spelling}
            if bound_composite_cells:
                table_options['bound_composite_cells'] = True
            if bind_composite_revisions:
                table_options['bind_composite_revisions'] = True
            if comparison_context is not None:
                table_options['comparison_context'] = comparison_context
            if type(table_references_version) is int and table_references_version in (2,3,4):
                table_options['translated_metrics'] = True
                if table_references_version in (3,4):
                    table_options['dataset_joiners'] = True
            from services.deep_research.table_bindings import validate_comparison_measurements
            reason = reason or validate_comparison_measurements(claim, support, **table_options)
        if (claim.get('designRole') is not None or
                (claim.get('designContractVersion') == 2 and kind in {'proposal', 'suggestion', 'hypothesis'})):
            from services.deep_research.experimental_reasoning import DESIGN_ROLES
            if not isinstance(claim.get('designRole'), str) or claim['designRole'] not in DESIGN_ROLES or kind not in {'proposal', 'suggestion', 'hypothesis'}:
                reason = reason or 'invalid_design_role'
        if not reason and claim.get('designContractVersion') == 2:
            from services.deep_research.execution_spec import execution_spec_errors
            errors = execution_spec_errors(claim.get('designRole'), claim.get('executionSpec'))
            if errors:
                rejected.append({"claimId": claim_id, "reason": "incomplete_execution_spec",
                                 "detail": ', '.join(errors)})
                continue
        if not reason and 'workflowContractVersion' in claim:
            from services.deep_research.experiment_workflow import workflow_errors, workflow_version
            if (not workflow_version(claim['workflowContractVersion'])
                    or claim.get('designRole') != 'steps' or kind not in {'proposal', 'suggestion', 'hypothesis'}):
                reason = 'invalid_workflow_contract'
            else:
                errors = workflow_errors(claim.get('executionSpec'), claim['workflowContractVersion'])
                if errors:
                    rejected.append({'claimId': claim_id, 'reason': 'incomplete_experiment_workflow',
                                     'detail': ', '.join(errors)})
                    continue
        if not reason and 'protocolContractVersion' in claim:
            from services.deep_research.experiment_protocol import protocol_errors, protocol_version, PROTOCOL_ROLES
            if (not protocol_version(claim['protocolContractVersion'])
                    or claim.get('designRole') not in PROTOCOL_ROLES
                    or kind not in {'proposal','suggestion','hypothesis'}):
                reason='invalid_protocol_contract'
            else:
                errors=protocol_errors(claim['designRole'],claim.get('executionSpec'),claim['protocolContractVersion'])
                if errors:
                    rejected.append({'claimId':claim_id,'reason':'incomplete_experiment_protocol','detail':', '.join(errors)})
                    continue
        if not reason and 'budgetContractVersion' in claim:
            from services.deep_research.budget_spec import validate_budget_spec
            if (type(claim['budgetContractVersion']) is not int or claim['budgetContractVersion'] != 1
                    or claim.get('designRole') != 'budget'
                    or kind not in {'proposal', 'suggestion', 'hypothesis'}):
                reason = 'invalid_budget_contract'
            else:
                errors = validate_budget_spec(claim.get('executionSpec'))
                if errors:
                    rejected.append({'claimId': claim_id, 'reason': 'incomplete_budget_spec',
                                     'detail': ', '.join(errors)})
                    continue
        if not reason and 'hypothesisContractVersion' in claim:
            from services.deep_research.hypothesis_spec import validate_hypothesis_spec
            if (type(claim['hypothesisContractVersion']) is not int or claim['hypothesisContractVersion'] != 1
                    or claim.get('designRole') != 'hypothesis'
                    or kind not in {'proposal', 'suggestion', 'hypothesis'}):
                reason = 'invalid_hypothesis_contract'
            else:
                errors = validate_hypothesis_spec(claim.get('executionSpec'))
                if errors:
                    rejected.append({'claimId': claim_id, 'reason': 'incomplete_hypothesis_spec',
                                     'detail': ', '.join(errors)})
                    continue
        if reason:
            diagnostic = {}
            if reason == 'requested_version_mismatch':
                diagnostic={'requestedSourceRevisions':requested_source_revisions,
                    'observedSourceRevisions':[{'evidenceId':item['evidenceId'],'sourceVersionId':item.get('sourceVersionId')} for item in mismatched_revisions],
                    'detail':'本条引用使用了与用户明确指定修订不一致的论文版本；不能改写来源标签或改kind绕过，需取得指定版本的原文。'}
            elif reason == 'numeric_mismatch' and word_counts:
                from services.deep_research.measurement_numbers import number_display
                missing = sorted(unsupported_numbers)
                diagnostic = {'missingReportedNumbers': missing,
                    'detail': '本条引用原文未直接报告这些数值：' + '、'.join(number_display(n) for n in missing)
                        + '。移除这些数字，保留有依据的属性或机制说明；不要用推算、改kind或改写引文绕过检查。'}
            elif reason == 'table_condition_not_displayed' and type(feedback_version) is int and feedback_version in (1, 2):
                diagnostic = _table_display_diagnostic(claim, support,comparison_context)
            elif reason == 'table_revision_setting_outside_request':
                diagnostic = {'detail': '把共同结论限定在问题指定的设置。原表题注给出的参数范围不能替代指定列。'}
            elif reason == 'result_purpose_not_established':
                diagnostic={'detail':'所引用的渲染剖析未建立主表结果的归属。区分算子剖析与主要比较；不得把剖析值改称主表值。'}
            elif reason == 'absence_not_established' and type(absence_scope_version) is int and absence_scope_version in (2,3,4,5,6,7,8,9):
                diagnostic = {'detail':'本条引用没有明确建立作者或论文缺少这些验证。'
                    '把结论限定为本次引用能支持的实验范围及其不能证明的推广；'
                    '不要写成作者未在其他条件验证、论文没有提供或全文不存在。'
                    '引用中的其他否定句不构成这项缺席判断的依据。'}
            if declared_reference_error:
                from services.deep_research.table_bindings import available_reference_rows
                reference_check={'reason':declared_reference_error,
                    'availableTableReferences':available_reference_rows(claim,support),
                    'detail':'tableBindings必须指向本条自身原文的真实单元格；rowNumber是源行号，不是所选行的数组下标。推算值不能伪装为原表单元格。'}
                if declared_reference_error==reason:
                    diagnostic={k:v for k,v in reference_check.items() if k!='reason'}
                else:
                    diagnostic.setdefault('additionalChecks',[]).append(reference_check)
            if concurrent_feedback and binding_reason and binding_reason != reason:
                diagnostic.setdefault('additionalChecks',[]).append({'reason': binding_reason,
                    **(_table_display_diagnostic(claim, support,comparison_context) if binding_reason == 'table_condition_not_displayed' else {})})
            rejected.append({"claimId": claim_id, "reason": reason, **diagnostic})
        else:
            candidates.append(dict(claim))
    return {'candidates': candidates, 'rejected': rejected}


def verify_claims(claims: list[dict], evidence: list[dict],
                  semantic_check: Callable[[list[dict], list[dict]], list[dict]] | None = None,
                  *, absence_scope_version=0, quantity_spelling_version=0, feedback_version=0,
                  table_references_version=0, review_context_version=0, requested_source_revisions=None,
                  complete_review_feedback=False,comparison_context=None,bound_duration_spelling=False,
                  comparison_embedded_measurements=False, bound_composite_cells=False,
                  bind_composite_revisions=False, named_revision_table=None, named_revision_question=None) -> dict:
    """Publish only after hard checks and an independent semantic verdict.

    Missing, malformed or duplicate model verdicts fail closed. A proposal or
    source-derived explanation never becomes a reported fact by its label.
    """
    if type(complete_review_feedback) is not bool:
        raise ValueError('Invalid complete review feedback policy')
    if type(bound_duration_spelling) is not bool:
        raise ValueError('Invalid bound duration spelling policy')
    if type(comparison_embedded_measurements) is not bool:
        raise ValueError('Invalid comparison measurement policy')
    checked = precheck_claims(claims, evidence, absence_scope_version=absence_scope_version,
        quantity_spelling_version=quantity_spelling_version, feedback_version=feedback_version,
        table_references_version=table_references_version, requested_source_revisions=requested_source_revisions,
        **({'bound_duration_spelling':True} if bound_duration_spelling else {}),
        bound_composite_cells=bound_composite_cells,
        bind_composite_revisions=bind_composite_revisions,
        **({'named_revision_table':named_revision_table} if named_revision_table else {}),
        **({'named_revision_question':named_revision_question} if named_revision_question else {}),
        **({'comparison_embedded_measurements':True} if comparison_embedded_measurements else {}),
        **({'comparison_context':comparison_context} if comparison_context is not None else {}))
    candidates, rejected = checked['candidates'], checked['rejected']
    proposals = {"suggestion", "proposal", "hypothesis"}
    # Suggestions are not established facts, but still need a logic/identity check.
    # A model must not hide a measured result or an invalid formula behind this tag.
    needs_check = candidates
    verdicts: dict[Any, dict] = {}
    if needs_check and semantic_check:
        from services.deep_research.rejected_design_context import enabled, rejected_context
        context=(rejected_context(claims,rejected,exclude=[c['claimId'] for c in candidates])
                 if enabled(review_context_version) else [])
        raw = semantic_check(needs_check,evidence,**({'proposal_context':context} if context else {}))
        if isinstance(raw, list):
            for verdict in raw:
                if not isinstance(verdict, dict):
                    continue
                key = verdict.get("claimId")
                if key in verdicts:
                    verdicts[key] = {"status": "invalid"}
                else:
                    verdicts[key] = verdict
    from services.deep_research.review_diagnostics import invalid as invalid_diagnostic
    from services.deep_research.review_response_failure import invalid as invalid_response_audit
    accepted = []
    for claim in candidates:
        if verdicts.get(claim["claimId"], {}).get("status") == "passed":
            accepted.append({**claim, "verification": "proposal" if claim["kind"] in proposals else "semantic_passed",
                             **({'assetAvailability': verdicts[claim['claimId']].get('assetAvailability')}
                                if requires_existing_asset(claim) else {})})
        else:
            verdict = verdicts.get(claim["claimId"], {})
            rejected.append({"claimId": claim["claimId"], "reason": "semantic_unresolved",
                             "detail": (str(verdict.get("reason", "")) if complete_review_feedback
                                        else str(verdict.get("reason", ""))[:400]),
                             **({'reviewResponseAudit':verdict['reviewResponseAudit'],
                                 'executionState':'received_invalid'} if invalid_response_audit(verdict.get('reviewResponseAudit')) else {}),
                             **({'reviewDiagnosticAudit':verdict['reviewDiagnosticAudit'],
                                 'executionState':'received_invalid'} if invalid_diagnostic(verdict.get('reviewDiagnosticAudit')) else {}),
                             **({'rejectionAudit':verdict['rejectionAudit'],
                                 **({'executionState':'received_invalid'} if verdict.get('executionState')=='received_invalid' else {})}
                                if type(review_context_version) is int and review_context_version in (5,6,7,8,9,10)
                                and isinstance(verdict.get('rejectionAudit'),dict) else {}),
                             **({'executionState':'not_started','reviewTimeAdmission':verdict.get('reviewTimeAdmission')}
                                if verdict.get('executionState')=='not_started' else {}),
                             **({'reviewInputCapacity':verdict['reviewInputCapacity']}
                                if verdict.get('executionState')=='not_started'
                                and isinstance(verdict.get('reviewInputCapacity'),dict) else {})})
    asset_ids = {c.get('claimId') for c in claims if requires_existing_asset(c)}
    for row in rejected:
        if row.get('claimId') in asset_ids:
            row['assetPrerequisite'] = True
    return enforce_asset_prerequisites({"accepted": accepted, "rejected": rejected}, evidence)
