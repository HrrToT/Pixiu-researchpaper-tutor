"""Compile a reviewed shared definition into one nonpublishable candidate.

No second writer invents a different initialization/budget. Full answer audit,
scope checks and publication integration remain mandatory after compilation.
"""
from services.deep_research.contracts import DeepResearchError, digest
from services.deep_research.shared_experiment_review import prepare, _generation, review_slot


MEMORY_REPORT_MARKER = 'sharedExperimentMemoryReportVersion'


def _cell(value):
    return str(value).replace('\\','\\\\').replace('|',r'\|').replace('\r','').replace('\n',' / ')


def _operation(op):
    parameters = '；'.join(p['name']+'='+str(p['value']) for p in op['parameters'])
    return op['action'] + ('（'+parameters+'）' if parameters else '')


def compiled_roles(proposal):
    """Locate the rendered roles in a proposal already validated for compilation."""
    data = proposal['data']
    analysis = proposal['analysis']
    fields = {
        'hypothesis': proposal['hypothesis'],
        'groups': proposal['groups'],
        'controls': proposal['factors'] and proposal['pairing']['identityChecks'],
        'data': data['trainingSplit'] and data['evaluationSplit'] and data['seeds'],
        'budget': proposal['budgets'],
        'steps': proposal['steps'],
        'metrics': proposal['metrics'],
        'analysis': analysis['contrasts'] and analysis['decisionRule'],
        'limits': analysis['limitations'],
    }
    return tuple(role for role, content in fields.items() if content)


def compile_candidate(record, input_data, aliases):
    saved = record.get('state',{}).get(review_slot(record))
    if not isinstance(saved,dict) or saved.get('status') != 'checked':
        raise DeepResearchError('shared_experiment_not_reviewed','科学审核尚未完成，不能生成正式结果候选。')
    def no_action(*args, **kwargs): raise AssertionError('Compilation cannot invoke or checkpoint')
    generation = _generation(record)
    review = prepare(record,input_data,aliases,invoke=no_action,checkpoint=no_action,
                     required_domains=generation['boundProposal']['requiredDomains'])
    assessment = review['assessment']
    if assessment.get('complete') is not True or assessment.get('scientificApproval') is not True:
        raise DeepResearchError('shared_experiment_incomplete','方案尚有未通过或未解决的科学问题。')
    p = generation['boundProposal']['proposal']
    states = {s['id']:s for s in p['states']}
    factors = {f['id']:f for f in p['factors']}
    step_numbers = {s['id']:i+1 for i,s in enumerate(p['steps'])}
    names = lambda ids: '、'.join(states[s]['meaning'] for s in ids) or '无'
    arms = lambda ids: '、'.join(ids) or '共同准备'
    citations = {}
    for fact in p['sourceFacts']:
        for eid in fact['evidenceRefs']:
            if eid not in citations:
                row = next(r for r in input_data['evidence'] if r['evidenceId'] == eid)
                citations[eid] = {'number':len(citations)+1, 'evidenceId':aliases[eid], 'source':row['source']}
    lines = ['# 实验方案（尚未执行）', '', '**假设：** '+p['hypothesis'], '', '**估计对象：** '+p['estimand'], '',
             '## 四组对照', '', '| 组别 | '+_cell(factors['A']['label'])+' | '+_cell(factors['B']['label'])+' |',
             '| --- | --- | --- |']
    for group in p['groups']:
        lines.append('| '+group['id']+' | '+('开启' if group['levels']['A'] else '关闭')+' | '
                     +('开启' if group['levels']['B'] else '关闭')+' |')
    lines += ['', '| 因素 | 关闭：保留原参数 | 开启 |', '| --- | --- | --- |']
    for factor in p['factors']:
        lines.append('| '+_cell(factor['label'])+' | '+_cell(_operation(factor['offOperation']))+' | '
                     +_cell(_operation(factor['onOperation']))+' |')
    data = p['data']
    lines += ['', '## 共同准备与配对', '']
    for row in data['inputs']:
        lines += ['- '+row['description']+'（'+('待准备' if row['availability']=='prepare' else '已提供')+'）：'+row['preparation']]
    lines += ['', '- 训练划分：'+data['trainingSplit'], '- 评估划分：'+data['evaluationSplit'],
              '- 划分预检：'+data['splitPrecheck'], '- 选择与调参：仅使用训练数据。',
              '- 独立重复单位：'+data['independentUnit']+'；配对种子：'+', '.join(map(str,data['seeds'])),
              '- 共同起点：'+names(p['pairing']['sharedStateIds']),
              '- 复制步骤：'+', '.join(str(step_numbers[s]) for s in p['pairing']['cloneStepIds']),
              '- 身份与初值核对：'+p['pairing']['identityChecks'], '', '## 状态与更新规则', '',
              '| 状态 | 表示 | 来源 | 固定 | 存储计量 | 适用组 |', '| --- | --- | --- | --- | --- | --- |']
    for state in p['states']:
        source = state['source']
        origin = (next(i['description'] for i in data['inputs'] if i['id'] == source['id'])
                  if source['kind']=='input' else '步骤 '+str(step_numbers[source['id']]))
        lines.append('| '+' | '.join(_cell(v) for v in (state['meaning'],state['representation'],origin,
                     '是' if state['fixed'] else '按步骤更新', '计入' if state['persisted'] else '不持久化',arms(state['groups'])))+' |')
    lines += ['', '## 执行顺序', '']
    data_uses = {'training':'训练数据', 'evaluation':'评估数据', 'evaluation_prepare':'仅准备评估数据',
                 'none':'不读取新数据'}
    asset_names = {row['id']: row['description'] for row in data['inputs']}
    shared_budget_starts = {}
    for i,step in enumerate(p['steps'],1):
        if step['factor'] is not None:
            factor = step['factor']; action = ('开启' if factor['level'] else '关闭')+factors[factor['id']]['label']+'，按上表操作'
        else: action = _operation(step['operation'])
        lines += [f"{i}. {arms(step['groups'])}：{action}。数据范围：{data_uses[step['dataUse']]}。",
                  '   读取：'+names(step['reads'])+'；创建：'+names(step['creates'])+'；更新：'+names(step['updates'])+'。']
        if step.get('inputIds'):
            lines += ['   输入材料：'+'、'.join(asset_names[input_id] for input_id in step['inputIds'])+'。']
        if step['metricIds']:
            lines += ['   测量：'+'、'.join(next(m['domain']+'（'+m['unit']+'）' for m in p['metrics'] if m['id']==mid)
                                             for mid in step['metricIds'])+'。']
        if step['budgetId'] is not None:
            b = next(b for b in p['budgets'] if b['id']==step['budgetId'])
            unit = {'optimizer_steps':'优化步','epochs':'轮','wall_seconds':'秒'}[b['unit']]
            if b.get('allocation') == 'shared_preparation_total':
                start = shared_budget_starts.setdefault(b['id'], i)
                if start == i:
                    end = max(step_numbers[s['id']] for s in p['steps'] if s['budgetId'] == b['id'])
                    lines.append(f'   步骤 {start}–{end} 共用 {b["cap"]} 秒准备预算，连续计时。{b["stopRule"]}')
                else:
                    lines.append(f'   沿用步骤 {start} 开始的准备计时。')
            else:
                lines += ['   预算：'+str(b['cap'])+' '+unit+'；'+('等预算对照' if b['matching']=='equal' else '原生预算，单独报告')
                          +'；'+b['stopRule']]
    lines += ['', '## 测量口径', '']
    for metric in p['metrics']:
        direction = '越大越好' if metric['direction']=='higher_better' else '越小越好'
        lines += ['- '+metric['domain']+'（'+metric['unit']+'，'+direction+'）：'+metric['procedure'],
                  '  涉及状态：'+names(metric['stateIds'])+'；仅对状态实际存在的组计量。']
        if captures := metric.get('fitMemoryCaptures'):
            intervals = '、'.join(f'步骤 {step_numbers[capture["stepId"]]}' for capture in captures)
            if record.get(MEMORY_REPORT_MARKER) == 1:
                lines.append(
                    f'  在{intervals}各自的完整拟合窗口记录峰值。按配对重复分开，每组取当次完整窗口中的最大值。'
                )
            else:
                lines.append(f'  在{intervals}各自的完整拟合窗口记录峰值。对每个实验组取本组各拟合窗口中的最大值。')
    lines += ['', '## 效应与判断', '', '各指标单独分析：越大越好的指标取负号作为损失，越小越好的指标保留原值，不混合不同单位。',
              '按 00、10、01、11 顺序，对损失使用以下对比权重：']
    labels = {'A':'因素 A 平均主效应','B':'因素 B 平均主效应','interaction':'交互效应'}
    for contrast in p['analysis']['contrasts']:
        lines += ['- '+labels[contrast['kind']]+'：'+str(contrast['weights'])]
    lines += ['', p['analysis']['uncertainty'], '', p['analysis']['decisionRule'], '', '**解释边界：** '+p['analysis']['limitations']]
    if p['sourceFacts']:
        lines += ['', '## 论文依据', '']
        for fact in p['sourceFacts']:
            refs=' '.join('['+str(citations[e]['number'])+'](#research-evidence-'+citations[e]['evidenceId']+')'
                          for e in fact['evidenceRefs'])
            lines += ['- '+fact['text']+' '+refs]
    text = '\n'.join(lines)+'\n'
    result = {'version':1, 'markdown':text, 'citations':list(citations.values()),
              'generationBindingDigest':generation['bindingDigest'], 'reviewDigest':assessment['reviewDigest'],
              'finalAnswerAuditRequired':True, 'publishable':False}
    return {**result,'candidateDigest':digest(result)}


def validate_candidate(candidate, record, input_data, aliases):
    try: return digest(candidate) == digest(compile_candidate(record,input_data,aliases))
    except (DeepResearchError,ValueError,TypeError,KeyError,IndexError): return False
