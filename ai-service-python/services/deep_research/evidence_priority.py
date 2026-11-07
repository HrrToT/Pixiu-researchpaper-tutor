"""Question-driven ordering of existing evidence, never permission or support."""
import re

_CONDITION_INTENT=re.compile(
    r'可比|公平比较|条件(?:对齐|一致)|同一条件|成立条件|实验设置|评测设置|未验证范围'
    r'|(?:直接|跨条件|跨论文)[^。！？\n]{0,20}(?:相除|比较|比值)'
    r'|\b(?:comparab\w*|align\w*|fair\s+comparison|experimental\s+(?:conditions|settings)|'
    r'controlled\s+comparison|cross[- ](?:paper|study)\s+(?:ratio|comparison))\b',re.I)
_DIMENSIONS=[
    re.compile(r'\b(?:gpu|cpu|hardware|platform|devices?)\b|硬件|平台|设备',re.I),
    re.compile(r'\b(?:datasets?|scenes?|resolution|image\s+size|test\s+split|benchmarks?)\b|数据集|场景|分辨率|测试划分',re.I),
    re.compile(r'\b(?:hyperparameters?|configurations?|settings?|implementation|re[- ]?train\w*|'
               r'original\s+code|batch\s+size|protocols?)\b|超参数|设置|配置|重训|实现|协议',re.I),
]
_MEASUREMENT=re.compile(r'\b(?:evaluat\w*|experiments?|measure\w*|report\w*|test(?:ed|ing)?|'
    r're[- ]?train\w*|for\s+(?:a\s+)?fair\s+(?:metric|comparison)|on\s+our\s+platform)\b|'
    r'评测|评估|实验|测量|报告|重训|公平比较',re.I)


def priority_enabled(record):
    return type(record.get('repairEvidencePriorityVersion')) is int and record['repairEvidencePriorityVersion']==1


def prioritize_existing_evidence(evidence,question):
    layers=getattr(question,'instruction_layers',None)
    current=layers[0] if layers else question
    if not isinstance(current,str) or not _CONDITION_INTENT.search(current):
        return list(evidence)
    def score(pair):
        index,row=pair
        # Direct source words outrank incidental context. Table packets or a
        # section title cannot by themselves establish measurement conditions.
        quote=str(row.get('quote',''))
        dimensions=sum(bool(pattern.search(quote)) for pattern in _DIMENSIONS)
        measurement=bool(_MEASUREMENT.search(quote))
        specificity=sum(min(3,len({m.group().casefold() for m in pattern.finditer(quote)})) for pattern in _DIMENSIONS)
        return (bool(dimensions and measurement),dimensions,specificity,measurement,-index)
    return [row for _,row in sorted(enumerate(evidence),key=score,reverse=True)]
