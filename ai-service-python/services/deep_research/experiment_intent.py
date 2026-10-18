"""Requested inference strength and observable experimental outcomes."""
import json
import re


def enabled(record):
    return type(record.get('experimentIntentContractVersion')) is int and record['experimentIntentContractVersion'] in (1,2)


def single_toggle_request(question):
    return (isinstance(question,str) and bool(re.search(r'两组|two groups|单因素|single.factor',question,re.I))
            and bool(re.search(r'关闭[^、，,；;。\n]{1,24}[与和]启用|single.factor|单因素',question,re.I)))


def guidance(question, roles=None, *, draft=False, policy_version=1):
    question = question if isinstance(question,str) else ''
    parts=['Judge the proposed experiment at the inference strength actually requested, while retaining source, initialization, pairing, budget and scientific-validity checks. A future hypothesis is not an already established result.']
    if roles is not None and None not in roles and not set(roles)&{'hypothesis','analysis','metrics','limits'}:
        return parts[0]  # These targets cannot rewrite the supplied measurement/decision definitions.
    if draft:
        parts=['Use the requested inference strength; keep the proposed plan unexecuted, paired, controlled and finite.']
        if re.search(r'描述性|\bdescriptive\b',question,re.I):
            parts.append('Explicit descriptive comparison uses explore/descriptive modes, paired effects and bounded conclusions; no significance test or CI is required or promised.')
        if re.search(r'抖动|\bjitter\b|temporal (?:flicker|smoothness)',question,re.I):
            parts.append('Per-frame PSNR-score variance ALONE does not measure jitter. Specify actual temporal image/motion observations on the same view/time path, handle genuine motion and include a quality guard against blur/suppressed motion. Never invent GT at unseen interpolation times; reference-free stability is not reconstruction accuracy.')
        return '\n'.join(parts)
    if type(policy_version) is int and policy_version == 2:
        parts.append('Check each target against the complete linked metric, hypothesis, analysis and configuration definitions supplied here. A concrete tolerance, pose-error setting or aggregation rule defined in a linked role need not be copied into every hypothesis/limits paragraph. Fail a missing definition, contradiction or broken reference, not absence of repetition. Repair metrics and their scientific decision together.')
    if re.search(r'描述性|\bdescriptive\b',question or '',re.I):
        parts.append('The user explicitly requests DESCRIPTIVE comparison. Use the existing explore purpose, descriptive uncertainty and descriptive decision modes when appropriate. A bounded paired effect/direction under the declared scene/settings needs NO significance test, confidence interval, bootstrap or population inference. Still specify matched observations, aggregation and the paired decision rule. Do not promise acceptance of a population hypothesis, equivalence or generalization. Do not fail solely because significance is absent.')
    if re.search(r'抖动|\bjitter\b|temporal (?:flicker|smoothness)',question or '',re.I):
        parts.append('Jitter is a temporal image/motion phenomenon. Variance or standard deviation of per-frame PSNR scores ALONE is not a valid primary jitter measure: a consistently poor reconstruction can have zero score variance, and changing content/views can vary scores without jitter. Define what temporal image/motion differences are measured on the SAME view/time path for both groups, how genuine motion/content is handled, and an image-quality guard against blur or suppressed motion. Do not invent ground truth at unobserved interpolation times. If using rendered stability without reference, state that limited observable and do not call it reconstruction accuracy. A named metric without its executable measurement operation is insufficient.')
    return '\n'.join(parts)


def repair_prompt(*, question,length_contract,accepted,siblings,questions,targets,checks,
                  permissions_marker,evidence_marker,shape,table_instructions,policy_version=1):
    encode=lambda x:json.dumps(x,ensure_ascii=False,separators=(',',':'))
    return f'''Revise ONLY these rejected UNEXECUTED experimental targets. Correct the specific checks;
do not return a verdict, rerun research or invent established results. Choose concrete proposed
settings now; they need no author attribution. Every factual paper operation, dataset/subset,
named scene, available count or existing asset still needs the target's OWN supplied evidence.
Quotation/source permissions are not proof of relevance. Missing passages prove no paper-wide
absence. Preserve exact empirical identities, values, units and conditions; do not generalize
an ablation or transfer another claim's facts. Abstract-only sources permit only abstract facts.
Question: {question}
{length_contract}
Accepted experimental definitions (consistency only; immutable here, not paper evidence):
{encode(accepted)}
Other draft definitions (UNVERIFIED consistency context; do not return these IDs):
{encode(siblings)}
App suffixes are omitted; full executionSpec is retained and will be rendered. Preserve consistent
prose, all required states and actual parameter choices. Do not duplicate fields in narrative.
Missing-question dictionary (Q IDs are internal, never evidence or published text):
{encode(questions)}
detailRequirementRole refers to the same required role definition under Experimental deliverables below.
Rejected claims and checks:
{encode([{'claim':row,'check':checks[row['claimId']]} for row in targets])}
Allowed evidence IDs per claim (candidate permissions only):
{permissions_marker}
Exact available evidence:
{evidence_marker}
{table_instructions}
Return only a COMPACT JSON array using actual values and this schema, or [] if unsupported:
{encode(shape)}
Preserve IDs, kinds and valid roles. Fill server-allocated missing-role slots without new IDs.
Each empirical clause cites only the target's own allowed supplied evidence; purely proposed
choices/math may use evidenceRefs=[]. E aliases belong only in citation fields, not prose.
Never convert an unsupported existing fact into a proposed choice to evade checking. Retain
necessary conditions once and the total answer length limit. Keep complete typed configuration
and all accepted definitions; other unverified drafts may be repaired in later batches.
{guidance(question,{row.get('designRole') for row in targets},policy_version=policy_version)}'''
