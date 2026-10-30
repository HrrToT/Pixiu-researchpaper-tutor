"""Retain literal dataset/header/member rows, without interpreting columns."""
import re


def requested(question):
    return bool(re.search(r'\b(?:dataset|subset|membership)\b|数据集|子集|'
        r'(?:场景|样本)[^。；;\n]{0,16}(?:成员|身份|依据|选择)|(?:选择|核对)[^。；;\n]{0,16}(?:场景|样本)',
        question or '',re.I))


def table_spans(text,questions, *, caption_headers=False):
    """One complete unchanged header/member span occupies one of three slots.

    No labels are generated or rebound to a dataset. In particular, merged or
    unverified numeric columns remain unverified and grant no numerical cells.
    """
    if not any(requested(q) for q in questions):
        return []
    rows=list(re.finditer(r'(?m)^[ \t]*Table row \d+:[^\r\n]*(?:\r?\n|$)',text))
    for index,row in enumerate(rows):
        if not re.search(r'\bdatasets?\b|数据集',row.group(),re.I):
            continue
        following=rows[index+1:index+3]
        if len(following)!=2 or any(text[left.end():right.start()].strip()
                for left,right in zip([row,*following],following)):
            continue
        if not re.search(r'\b(?:scene|sample|sequence|subject)\b|场景|样本',following[0].group(),re.I):
            continue
        member=following[1].group().split(':',1)[1].split('|',1)[0].strip()
        if not re.search(r'[A-Za-z\u4e00-\u9fff]',member) or re.match(r'(?:ours|method|baseline)\b',member,re.I):
            continue
        quote=text[row.start():following[-1].end()].strip()
        if len(quote)<=1200 and not any(mark in quote for mark in ('…','...')):
            return [quote]
    if caption_headers:
        # Preserve horizontal labels exactly, including merged cells. Neither
        # dataset membership nor a numerical column binding is established here.
        pattern=r'(?m)^[ \t]*Table caption:[^\r\n]*\r?\n[ \t]*Table row \d+:[^\r\n]*'
        for match in re.finditer(pattern,text):
            caption,header=match.group().splitlines()
            if not re.search(r'\bdatasets?\b|数据集',caption,re.I):
                continue
            if not re.search(r'Table row \d+:\s*(?:Method|Model|方法|模型)\s*\|',header,re.I):
                continue
            quote=match.group().strip()
            labels=header.split('|',1)[1]
            if (len(quote)<=1200 and not any(mark in quote for mark in ('…','...'))
                    and len(re.findall(r'[A-Za-z]{2,}|[\u4e00-\u9fff]{2,}',labels))>=2):
                return [quote]
    return []
