"""Rank owned operations for a requested input, temporal model or training task.

Scores select passages only; they do not prove relevance, identity or support.
"""
import re


def query_intents(query):
    """All explicit acquisition aspects, not a factual or completion verdict.

    A compound request can ask for inputs AND temporal representation AND
    training organization. The legacy single-intent route remains unchanged.
    """
    patterns=(
        ('input',r'\binputs?\b|输入'),
        ('temporal',r'\btemporal (?:representation|model\w*)|\b(?:represent\w*|model\w*)[^.!?]{0,25}\btime\b|时间(?:变化|表示|建模)'),
        ('training',r'\b(?:online|offline|per.frame|joint\w* train\w*|training (?:organization|procedure|stages?))\b|训练(?:模式|流程|方式|次序|是)|逐帧|在线|离线'),
        ('operation',r'\b(?:mechanism|intervention|implementation|anneal\w*|smoothing)\b|退火|平滑|实现机制|方法操作'),
        ('data_membership',r'\b(?:dataset|subset|membership)\b|数据集|子集|场景.{0,8}(?:身份|成员|哪些)'))
    found=[intent for intent,pattern in patterns if re.search(pattern,query,re.I)]
    for metric in ('FPS','PSNR','SSIM','LPIPS','latency'):
        if re.search(r'(?<![A-Za-z0-9_])'+metric+r'(?![A-Za-z0-9_])',query,re.I):
            found.append('measurement:'+metric.lower())
            if re.search(r'主表|\bmain (?:results? )?table\b',query,re.I):
                found.append('comparison_result:'+metric.lower())
    return found


def query_intent(query, *, operational=False):
    if re.search(r'\b(?:input|inputs)\b|(?:什么|哪些|使用|采用).{0,8}输入|输入(?:数据|材料)', query, re.I):
        return 'input'
    if re.search(r'\btemporal (?:representation|model\w*)|\b(?:represent\w*|model\w*)[^.!?]{0,25}\btime\b'
                 r'|时间(?:变化|表示)|怎样表示时间', query, re.I):
        return 'temporal'
    if re.search(r'\b(?:online|offline|per.frame|joint)\b[^.!?]{0,22}\btrain\w*|训练(?:模式|流程|方式)', query, re.I):
        return 'training'
    if operational:
        metrics=set(re.findall(r'\b(?:FPS|PSNR|SSIM|LPIPS|latency)\b',query,re.I))
        if len(metrics)==1:
            return 'measurement:'+next(iter(metrics)).lower()
    if operational and re.search(r'\b(?:mechanism|intervention|implementation|anneal\w*|smoothing)\b'
                                 r'|退火|平滑|实现机制|方法操作',query,re.I):
        return 'operation'
    if operational and re.search(r'\b(?:dataset|subset|membership)\b|数据集|子集|场景.{0,8}(?:身份|成员|哪些)',query,re.I):
        return 'data_membership'
    return None


def operation_score(body, section, intent, *, operational=False):
    if operational and isinstance(intent,str) and intent.startswith('data_condition:'):
        from services.deep_research.data_conditions import condition_score
        return condition_score(body,section,intent.split(':',1)[1])
    measurement = operational and isinstance(intent,str) and intent.startswith('measurement:')
    comparison_result = operational and isinstance(intent,str) and intent.startswith('comparison_result:')
    if (not intent or re.search(r'related work|background|concurrent works|references',section,re.I)
            or (re.search(r'Table\s*\d',section,re.I) and not (measurement or comparison_result or operational and intent=='data_membership'))):
        return 0
    text = re.sub(r'(?<=[A-Za-z])-[ \t]*\r?\n[ \t]*(?=[A-Za-z])', '', body)
    method = bool(re.search(r'^(?:\d+[. ]*)?(?:Method|Approach|Proposed)', section, re.I))
    own = bool(re.search(r'\bwe\b|\bour\b|我们的|本文', text, re.I))
    if not method and not own and not (measurement or comparison_result or operational and intent=='data_membership'):
        return 0
    if comparison_result:
        metric=intent.split(':',1)[1]
        if not re.search(r'(?<![A-Za-z_])'+re.escape(metric)+r'(?![A-Za-z_])',text,re.I):
            return 0
        # A literal quantitative-comparison caption is a retrieval hint.
        # Do not assume Table1 is the main result, or certify the row/protocol.
        caption=section+'\n'+text[:450]
        comparison=bool(re.search(r'quantitative comparison|comparison (?:on|with)|benchmark comparison',caption,re.I))
        diagnostic=bool(re.search(r'profil\w*|ablation|sensitivity|overhead',caption,re.I))
        return max(0,10*comparison-12*diagnostic+own+method)
    if measurement:
        metric=intent.split(':',1)[1]
        if not re.search(r'(?<![A-Za-z_])'+re.escape(metric)+r'(?![A-Za-z_])',text,re.I):
            return 0
        conditions=sum(bool(re.search(pattern,text,re.I)) for pattern in (
            r'\b(?:NVIDIA|RTX|GPU|CPU|processor|hardware)\b',r'\b\d+\s*[x×]\s*\d+\b|resolution',
            r'\b(?:render\w*|train\w*|timing|seconds?|latency)\b',r'\b(?:Gaussians?|frames?|scenes?|views?)\b'))
        return 3*conditions+own+method
    if intent == 'data_membership' and operational:
        dataset = bool(re.search(r'\bdataset\b|数据集',text,re.I))
        member = bool(re.search(r'\b(?:scenes?|subsets?|sets?)\b[^.!?\n]{0,100}'
            r'\b(?:of|called|named|include\w*|contain\w*)\b|\b(?:of|in)\s+(?:the\s+)?'
            r'[A-Z][A-Za-z0-9_-]{2,}[^.!?\n]{0,40}\bdataset\b|(?:包含|属于).{0,30}(?:场景|子集)',text))
        return 8*member+own+method if dataset else 0
    if intent == 'input':
        explicit = bool(re.search(r'\binput(?:s)?\s+(?:to|of)\s+(?:our|the proposed)\s+(?:method|model|system)', text, re.I))
        data = bool(re.search(r'\b(?:monocular|multi.view|single.view|camera poses?|time labels?|video streams?)\b', text, re.I))
        operation = bool(re.search(r'\b(?:inputs?|construct\w*|initializ\w*|takes?|given|calibrat\w*)\b', text, re.I))
        return (4*explicit+2*method+own+data) if data and operation else 0
    if intent == 'temporal':
        state = bool(re.search(r'\b(?:previous|subsequent|current|canonical|timesteps?|time)\b', text, re.I))
        change = bool(re.search(r'\b(?:transform\w*|deform\w*|offsets?|translat\w*|rotat\w*|carr\w*|pass\w*)\b', text, re.I))
        output = bool(re.search(r'\b(?:output\w*|maps?[^.\n]{0,100}\bto\b|indicate\w*|given as)\b', text, re.I))
        types = sum(bool(re.search(pattern,text,re.I)) for pattern in
                    (r'\b(?:translation|position|mean)\b',r'\b(?:rotation|quaternion)\b',r'\b(?:scale|scaling)\b'))
        return 3*output+types+2*method+own+state if state and change else 0
    if intent == 'training':
        train = bool(re.search(r'\b(?:train\w*|optimiz\w*|learn\w*)\b', text, re.I))
        schedule = sum(bool(re.search(pattern,text,re.I)) for pattern in
                       (r'\b(?:per.frame|each timestep|subsequent timestep|online|offline)\b',
                        r'\b(?:jointly|joint optimization|entire|whole)\b',r'\b(?:initializ\w*|warm.up|stages?|iterations?)\b'))
        staged = (operational and bool(re.search(r'\b(?:initial(?:ly)?|first|warm.up)\b',text,re.I))
                  and bool(re.search(r'\b(?:subsequently|after|then|followed by)\b',text,re.I)))
        return 3*schedule+2*method+own+6*staged if train and schedule else 0
    if intent == 'operation' and operational:
        # Outcomes and a technique name alone do not specify its operation.
        action = sum(bool(re.search(pattern,text,re.I)) for pattern in (
            r'\b(?:add\w*|inject\w*|perturb\w*|sampl\w*|transform\w*|updat\w*|prun\w*)\b',
            r'\b(?:noise|distribution|offsets?|gradients?|weights?)\b',
            r'\b(?:decay\w*|anneal\w*|schedule|iterations?|threshold|linearly)\b',
            r'\b(?:input|encoding|time|coordinates?|positions?|state)\b'))
        equation = bool(re.search(r'Equation:|[=＝]',text))
        return 3*action+2*equation+own+method if action>=2 else 0
    return 0
