"""Bounded obligation/paper reading order before model extraction."""
import re
from services.deep_research.extraction_priority import prioritize_extraction_passages
from services.deep_research.source_continuity import needs_preceding_context,method_reference
from services.deep_research.obligation_binding import eligible_obligation_ids


def select_read_sources(sources, obligations, limit, *, extracted=(),priority_version=6,illustrative_context=False,method_context=False,substantive=False,mixed_script_terms=False,measurement_tables=False,processing_cost=False,table_navigation_obligations=None, protocol_note=False, mechanism_overviews=False,
                        benchmark_human=None, named_table_question=None, experiment_protocol=False,
                        comparison_evaluation_protocol=False, comparison_deployment_memory=False,
                        comparison_memory_criteria=False, named_table_grouped_rows=False, local_pdf_methods=False,
                        threshold_benchmarks=None, named_benchmark_protocol=False, supervision=False,
                        figure_counts=False, compression_operations=False, experiment_densification=False):
    """Retain owned source identities and exact predecessor bundles.

    Storage ID order is not relevance order. Rank retrieved text by each
    obligation/paper, then read unextracted candidates first under the same cap.
    A predecessor is eligible only from the same work, version, index family
    and section; neither its text nor its source permissions are merged.
    """
    if type(measurement_tables) is not bool:raise ValueError('Invalid measurement table navigation policy')
    if type(processing_cost) is not bool:raise ValueError('Invalid processing cost navigation policy')
    readable=[]
    for source in sources:
        namespace=re.fullmatch(r'(.+)-v[0-9a-f]{16}-chunk-\d+',source['sourceId'])
        if namespace and namespace[1]!=source.get('workId'):
            continue  # An indexed ID cannot claim another paper's work identity.
        if eligible_obligation_ids(source,obligations):
            readable.append(source)
    pending=[(s,s.get('location',{}),s.get('text','')) for s in readable]
    ordered=[row[0] for row in prioritize_extraction_passages(pending,obligations,priority_version)]
    if substantive:
        from services.deep_research.reading_roles import order
        ordered=order(readable,obligations,ordered,extracted=extracted,mixed_script_terms=mixed_script_terms,
                      measurement_tables=measurement_tables,processing_cost=processing_cost)
    else:
        ordered.sort(key=lambda s:(s['sourceId'],s.get('contentHash')) in extracted)
    preferred = []
    if mechanism_overviews and limit >= 3:
        from services.deep_research.selection import balanced_sample
        definitions = [source for source in ordered
                       if source.get('location', {}).get('matchedRepresentationDefinition') is True
                       and source.get('accessLevel') == 'fulltext'
                       and source.get('ownerMaterialId') == source.get('workId')
                       and (source['sourceId'], source.get('contentHash')) not in extracted]
        preferred.extend(balanced_sample(definitions,
            lambda source: (source['workId'], source.get('versionId')), limit // 3))
    if local_pdf_methods:
        from services.deep_research.selection import balanced_sample
        methods = [source for source in ordered if source.get('location', {}).get('matchedPdfMethodPassage') is True
                   and (source['sourceId'], source.get('contentHash')) not in extracted]
        preferred.extend(balanced_sample(
            methods, lambda source: tuple(oid for oid in eligible_obligation_ids(source, obligations)
                                          if oid in source.get('obligationIds', ())), limit // 2))
    if measurement_tables and table_navigation_obligations:
        from services.deep_research.reading_roles import quality, requests
        from services.deep_research.measurement_table_navigation import score
        targets = requests(table_navigation_obligations, readable, mixed_script_terms=mixed_script_terms)
        best_by_paper = {}
        for source in ordered:
            if not source.get('tableData') or (source['sourceId'], source.get('contentHash')) in extracted:
                continue
            eligible = eligible_obligation_ids(source, table_navigation_obligations)
            match = max((score(source, request) for request in targets
                         if request['obligationId'] in eligible and quality(source, request['query']) == (True, True)),
                        default=0)
            identity = (source['workId'], source.get('versionId'))
            if match > best_by_paper.get(identity, (0, None))[0]:
                best_by_paper[identity] = (match, source)
        # Keep most read slots available for the active step's own role queues.
        preferred.extend(source for _, source in list(best_by_paper.values())[:limit // 2])
    if protocol_note and limit > 1:
        from services.deep_research.table_note_index import has_protocol_note
        extracted = set(extracted)
        note = next((source for source in ordered
                     if source.get('accessLevel') == 'fulltext'
                     and (source['sourceId'], source.get('contentHash')) not in extracted
                     and has_protocol_note(source.get('text'))), None)
        if note is not None:
            preferred.append(note)
    if mechanism_overviews and limit >= 3:
        from services.deep_research.mechanism_sources import comparison_overviews
        preferred.extend(comparison_overviews(
            ordered, obligations, extracted, compression_operations=compression_operations)[:limit // 3])
    if compression_operations == 5 and processing_cost and limit >= 3:
        from services.deep_research.criterion_sources import criterion_targets
        from services.deep_research.processing_cost_sources import codebook_training_score, recovery_training_score

        cost_goals = {oid for oid, _, intent in criterion_targets(obligations, compression_operations=5)
                      if intent in ('codebook_training_cost', 'recovery_training_cost')}
        best = {}
        for source in ordered:
            if (source.get('accessLevel') != 'fulltext' or source.get('ownerMaterialId') != source.get('workId')
                    or source.get('tableData') or (source['sourceId'], source.get('contentHash')) in extracted
                    or not cost_goals.intersection(source.get('obligationIds', ()))):
                continue
            section = source.get('location', {}).get('section') or ''
            for score in (codebook_training_score, recovery_training_score):
                if score(source.get('text', ''), section):
                    best.setdefault((source['workId'], source.get('versionId'), score), source)
        preferred.extend(list(best.values())[:limit // 3])
    if benchmark_human:
        from services.deep_research.named_benchmark_navigation import preferred_benchmark_reads
        preferred.extend(preferred_benchmark_reads(ordered, obligations, benchmark_human, limit, extracted))
    if named_table_question:
        from services.deep_research.named_table_scope import preferred_read_rows
        preferred = [*preferred_read_rows(ordered, named_table_question, limit, extracted,
                                          grouped_rows=named_table_grouped_rows), *preferred]
    if experiment_protocol:
        from services.deep_research.experiment_protocol_sources import preferred_reads
        preferred = [*preferred_reads(ordered, obligations, limit, extracted,
                                      densification=experiment_densification), *preferred]
    if comparison_evaluation_protocol:
        from services.deep_research.comparison_joint_reports import preferred_evaluation_reads
        preferred = [*preferred_evaluation_reads(ordered, obligations, limit, extracted), *preferred]
    if comparison_deployment_memory:
        from services.deep_research.comparison_joint_reports import preferred_deployment_memory_reads
        preferred = [*preferred_deployment_memory_reads(ordered, obligations, limit, extracted,
                                                       completion_criteria=comparison_memory_criteria), *preferred]
    if supervision:
        from services.deep_research.method_intent import operation_score, training_supervision_requested
        requested = {oid: o for oid, o in obligations.items()
                     if any(training_supervision_requested(c['requirement']) for c in
                            (o.get('completionCriteria') or [{'requirement': o['question']}]))}
        matched = {}
        for source in ordered:
            if not eligible_obligation_ids(source, requested) or source.get('tableData'):
                continue
            if (source['sourceId'], source.get('contentHash')) in extracted:
                continue
            score = operation_score(source.get('text', ''), source.get('location', {}).get('section', ''),
                                    'training_supervision', operational=True)
            identity = (source['workId'], source.get('versionId'))
            if score > matched.get(identity, (0, None))[0]:
                matched[identity] = (score, source)
        supervision_reads = [source for _, source in matched.values()]
        preferred = [*supervision_reads[:max(1, limit // 3)], *preferred]
    if threshold_benchmarks:
        from services.deep_research.measurement_table_navigation import preferred_threshold_reads
        tables = preferred_threshold_reads(ordered, obligations, threshold_benchmarks, limit, extracted)
        protocols = []
        if named_benchmark_protocol:
            from services.deep_research.pdf_benchmark_protocol import preferred_protocol_reads
            read_tables = preferred_threshold_reads(ordered, obligations, threshold_benchmarks, limit, ())
            protocols = preferred_protocol_reads(ordered, read_tables, obligations, extracted)[:limit // 4]
        figures = []
        if figure_counts:
            from services.deep_research.comparison_joint_reports import named_feature_matching_counts, named_quantitative_benchmarks
            from services.deep_research.selection import balanced_sample
            benchmark_goals = {oid: names for oid, o in obligations.items()
                               if (names := named_quantitative_benchmarks(threshold_benchmarks, o))}
            candidates = []
            for source in ordered:
                if (source['sourceId'], source.get('contentHash')) in extracted:
                    continue
                names = set().union(*(benchmark_goals[oid] for oid in eligible_obligation_ids(source, obligations)
                                      if oid in benchmark_goals and oid in source.get('obligationIds', ())))
                if named_feature_matching_counts({**source, 'quote': source.get('text', '')}, names):
                    candidates.append(source)
            figures = balanced_sample(candidates, lambda source: (source['workId'], source.get('versionId')), limit // 4)
        preferred = [*tables, *protocols, *figures, *preferred]
    ordered = [*preferred, *ordered]
    selected=[];used=set()
    for source in ordered:
        if source['sourceId'] in used:
            continue
        bundle=[]
        identity=re.fullmatch(r'(.+-v[0-9a-f]{16}-chunk-)(\d+)',source['sourceId'])
        if method_context is True:
            bundle=_method_bundle(source,readable,used)
        elif identity and int(identity[2])>0 and needs_preceding_context(source,illustrative=illustrative_context):
            prior_id=identity[1]+str(int(identity[2])-1)
            predecessors=[s for s in readable if s['sourceId']==prior_id
                and s.get('workId')==source.get('workId') and s.get('versionId')==source.get('versionId')
                and s.get('ownerMaterialId')==source.get('ownerMaterialId')
                and s.get('location',{}).get('section')==source.get('location',{}).get('section')
                and isinstance(source.get('location',{}).get('section'),str)
                and source['location']['section'].strip()]
            if illustrative_context is True:
                predecessors=[s for s in predecessors
                    if source.get('accessLevel') == s.get('accessLevel') == 'fulltext'
                    and type(source.get('location',{}).get('chunk')) is int
                    and source['location']['chunk'] == int(identity[2])
                    and type(s.get('location',{}).get('chunk')) is int
                    and s['location']['chunk'] == int(identity[2])-1]
            if len(predecessors)==1 and prior_id not in used:
                bundle.append(predecessors[0])
        bundle.append(source)
        if len(selected)+len(bundle)>limit:
            continue
        selected.extend(bundle);used.update(s['sourceId'] for s in bundle)
    return selected


def _method_bundle(source,readable,used):
    chain=[];current=source
    for _ in range(2 if method_reference(source) else 1):
        identity=re.fullmatch(r'(.+-v[0-9a-f]{16}-chunk-)(\d+)',str(current.get('sourceId','')))
        section=current.get('location',{}).get('section')
        if (not identity or int(identity[2])<1 or not isinstance(section,str) or not section.strip()
                or current.get('accessLevel')!='fulltext' or type(current.get('location',{}).get('chunk')) is not int
                or not isinstance(current.get('ownerMaterialId'),str) or not current['ownerMaterialId'].strip()
                or not isinstance(current.get('versionId'),str) or not current['versionId'].strip()
                or current['location']['chunk']!=int(identity[2])
                or not needs_preceding_context(current,illustrative=True,procedural=True)):
            break
        pid=identity[1]+str(int(identity[2])-1)
        matches=[r for r in readable if r['sourceId']==pid and r.get('accessLevel')=='fulltext'
            and r.get('workId')==current.get('workId') and r.get('versionId')==current.get('versionId')
            and r.get('ownerMaterialId')==current.get('ownerMaterialId')
            and r.get('location',{}).get('section')==section
            and type(r.get('location',{}).get('chunk')) is int and r['location']['chunk']==int(identity[2])-1]
        if len(matches)!=1 or pid in used:break
        chain.append(matches[0]);current=matches[0]
    return list(reversed(chain))
