# 核查修订中的受控事实到推断转换

`.327` 真实阶段已消除 Size 中文显示误拒，但仍未补成有条件判断。源码中核查指令要求生成自己的推断判断，修订通用协议却冻结 same claimId/kind；原 reported 条目不能合法变成包含推导的 inference。这不是将作者报告当作已证实判断的理由。

`.328` 对新建 claimCheckContractVersion=6 的核查修订，只为 reason=answer_incomplete（包括固定 additionalChecks）的普通 reported 条目开放 reported→inference。实验角色和其他类型／理由不开放。必须保留 claimId、原义务与引用权限，实际改变正文，并提供 draftingBasis.scopeDecision=bounded_inference 的未核验意图；仅改标签、换来源或改为建议均拒绝。该意图不是事实支持，转换会记录 from/to/reason/unchecked 审计，修订后的推断继续接受普通、数值引用、范围及独立语义核查。版本 1—5 的类型冻结和缓存保持，版本 6 使用独立身份，不以转换来重抽旧语义判定。

先前补充的范围角色保护在版本 6 继续启用；转换不授予返回无结构范围点的权限。语义夹具返回 unresolved 时仍无可接受论断，允许转换不代表研究结论正确。60 项定向测试通过；初次夹具缺少 literal=passed 标记，并发现无 factual_scope 参数时转换审计未保存，已补齐证据夹具和版本 6 审计路径后通过。

实际输入离线回放的前三个核查请求逐字匹配保存输入，新修订只开放 c1，23998 UTF-8 字节，在原24000上限内，原表第8/10行均存在；没有模型调用、生产变更或内容批准。回放使用旧已结算核查回复及空修订夹具，仅证明路由、容量、身份和必要表格行保持。证据：deep-research-evidence/inference-kind-328-actual-input-replay-20261029.json。

最终固定源码的63文件、1097项关联回归通过，pytest99.63秒、外部103.765秒，源码和测试哈希前后一致，无模型调用。证据：deep-research-evidence/inference-kind-328-final-regression-20261029.json。
