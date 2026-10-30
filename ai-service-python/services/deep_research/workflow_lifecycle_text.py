"""Workflow5 display derived from validated choices; never an execution result."""
from html import escape

from services.deep_research.workflow_lifecycle import lifecycle_events


def _safe(value):
    return escape(str(value), quote=True)


def _input(value):
    source = (value['state'] if 'state' in value else value['phaseId'] + '/' + value['outputId'])
    return _safe(source) + '；选取：' + _safe(value['selector'])


def _initialization(value, title):
    from services.deep_research.state_initialization import state_definitions_text
    from services.deep_research.operation_text import operation_text
    lines=['', '<details>', '<summary>'+_safe(title)+'</summary>', '',
           '创建方式：'+('从显式初值新建。' if value['initializationMode']=='fresh' else '从已声明输入派生。')]
    lines += [f'输入{i}：'+_input(source) for i,source in enumerate(value['inputs'])]
    lines += [_safe(operation_text(value['creation'])), _safe(state_definitions_text(value['stateDefinitions'])),
              '执行前核对所选状态的实际形状、初值广播和RNG版本；不满足条件时停止。', '', '</details>', '']
    return lines


def lifecycle_text(spec):
    """Caller must validate the complete Workflow5, including all initial values."""
    from services.deep_research.operation_text import operation_text
    from services.deep_research.experiment_workflow import RECORD_LABELS
    phases={p['phaseId']:p for p in spec['phases']}
    components={c['componentId']:c for c in spec['componentInitializations']}
    lines=['拟议执行流程（尚未执行）：',
           '先完成数据预检，锁定训练与最终评估划分；最终评估集不参与拟合、初始化、调参或选模。']
    selection=spec['checkpointSelection']
    if selection['mode']=='validation_split':
        from services.deep_research.protocol_text import render_split
        lines += ['验证部分仅从训练数据再次划出：'+_safe(render_split(selection['split'],training='拟合',evaluation='验证')),
                  '拟合与验证部分必须都非空且互不重叠，否则停止。']
    if spec['replicationMode']=='retrained_per_seed':
        lines.append('每个数据种子分别重建并拟合基线，再执行配对流程。' if spec['baselineMode']=='train'
                     else '各重复从相同已有资产开始；不将其称为独立重训的基线。')
    else:
        lines.append('复用同一个固定基线；后续随机种子不代表基线独立重训。')
    lines.append('共同基线先按预算声明完成拟合，再进入下列阶段。' if spec['baselineMode']=='train'
                 else '先按预算声明的规则获取已有资产，并核对来源、可用性和身份，再进入下列阶段。')
    if spec['baselineInitialization'] is not None:
        lines += _initialization(spec['baselineInitialization'],'基线初始状态（拟合前）')
    if components:
        lines.append('以下为初始化配方；实例按后面的时序创建。')
    for c in spec['componentInitializations']:
        life=c['lifecycle']
        scope='每帧新建' if life['scope']=='per_frame' else '每次重复创建一次'
        after='、'.join(life['createAfter']) or '该作用域入口'
        end=life['disposeAfter'] or '本重复保留'
        lines.append(_safe(c['componentId'])+'：'+scope+'；依赖 '+_safe(after)+'；释放点：'+_safe(end)+'。')
        lines += _initialization(c,c['componentId']+'的完整初值配方')
    frame_open=False;step=0
    kinds={'fit':'拟合','setup':'准备/干预','evaluate':'最终评估','record':'记录'}
    units={'optimizer_steps':'次优化更新','epochs':'轮','wall_seconds':'秒'}
    for event in lifecycle_events(spec):
        if event['scope']=='per_frame' and not frame_open:
            lines += ['',f"逐帧循环：对每帧依次执行下列动作，共{spec['frameIterations']}帧。"]
            frame_open=True
        elif event['scope']=='per_repeat' and frame_open:
            lines += ['', '逐帧循环完成后：'];frame_open=False
        step+=1; groups='、'.join(event['groups'])
        if event['kind']=='initialize':
            lines.append(f"{step}. 为组 {_safe(groups)} 按上述配方创建 {_safe(event['id'])} 实例。")
        elif event['kind']=='dispose':
            lines.append(f"{step}. 释放 {_safe(event['id'])} 实例；后续只使用已明确保存的输出。")
        else:
            p=phases[event['id']]
            sharing='共享一次执行' if p['sharing']=='shared' else '分别执行'
            lines.append(f"{step}. {_safe(p['phaseId'])} · {kinds[p['kind']]} · 组 {_safe(groups)}{sharing}："+_safe(p['action']['action']))
            if p['budget'] is not None:
                cap=p['budget'];count=spec['frameIterations'] if p['scope']=='per_frame' else 1
                lines.append('   每次拟合上限 '+_safe(cap['perExecution'])+units[cap['unit']]+'；每次重复执行 '+str(count)+' 次，归属预算按全部次数核对。')
            lines += ['', '<details>', '<summary>本阶段的输入、更新和输出</summary>', '',
                      _safe(operation_text(p['action']))]
            lines += ['读取：'+_input(source) for source in p['reads']]
            lines += ['允许更新：'+_safe('、'.join(p['updates']) or '无'),
                      '产生输出：'+_safe('、'.join(p['outputs']) or '无'), '', '</details>', '']
    if frame_open: lines.append('完成本帧记录与清理后进入下一帧。')
    if selection['mode']=='fixed_budget':lines.append('检查点使用预算结束时的状态，不依据最终评估表现挑选。')
    else:lines.append('检查点仅按训练损失或独立训练内验证规则选择：'+_safe(operation_text(selection['rule'])))
    lines.append('保存：'+'、'.join(_safe(RECORD_LABELS.get(key,key)) for key in spec['records'])+'。')
    return '\n'.join(lines)
