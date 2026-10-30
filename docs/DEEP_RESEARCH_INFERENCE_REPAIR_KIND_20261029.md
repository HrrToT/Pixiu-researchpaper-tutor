# 核查修订中的受控事实到推断转换

`.327` 真实阶段已消除 Size 中文显示误拒，但仍未补成有条件判断。源码中核查指令要求生成自己的推断判断，修订通用协议却冻结 same claimId/kind；原 reported 条目不能合法变成包含推导的 inference。这不是将作者报告当作已证实判断的理由。

`.328` 对新建 claimCheckContractVersion=6 的核查修订，只为 reason=answer_incomplete（包括固定 additionalChecks）的普通 reported 条目开放 reported→inference。实验角色和其他类型／理由不开放。必须保留 claimId、原义务与引用权限，实际改变正文，并提供 draftingBasis.scopeDecision=bounded_inference 的未核验意图；仅改标签、换来源或改为建议均拒绝。该意图不是事实支持，转换会记录 from/to/reason/unchecked 审计，修订后的推断继续接受普通、数值引用、范围及独立语义核查。版本 1—5 的类型冻结和缓存保持，版本 6 使用独立身份，不以转换来重抽旧语义判定。

先前补充的范围角色保护在版本 6 继续启用；转换不授予返回无结构范围点的权限。语义夹具返回 unresolved 时仍无可接受论断，允许转换不代表研究结论正确。60 项定向测试通过；初次夹具缺少 literal=passed 标记，并发现无 factual_scope 参数时转换审计未保存，已补齐证据夹具和版本 6 审计路径后通过。

实际输入离线回放的前三个核查请求逐字匹配保存输入，新修订只开放 c1，23998 UTF-8 字节，在原24000上限内，原表第8/10行均存在；没有模型调用、生产变更或内容批准。回放使用旧已结算核查回复及空修订夹具，仅证明路由、容量、身份和必要表格行保持。证据：deep-research-evidence/inference-kind-328-actual-input-replay-20261029.json。

最终固定源码的63文件、1097项关联回归通过，pytest99.63秒、外部103.765秒，源码和测试哈希前后一致，无模型调用。证据：deep-research-evidence/inference-kind-328-final-regression-20261029.json。

`.328` 已从9442d95d加载，原7,465条账本、全部旧payload、五个任务和完整索引保持；0活跃、13旧暂停，RAG/GROBID正常、前端200。真实核查与修订阶段7次调用全部成功结算，32,587 Token，无未知/重试，也未发布生产。

模型确实将c1由reported修订为inference，保留原身份和同源主表输入；类型转换审计为unchecked，修订经过正常精简及独立verify_repair。该推断因对“画质接近”的笼统评估仍不足以被所引指标严格支撑而拒绝，c2因数据集条件引用到未支持该条件的相关工作上下文而拒绝。原已核查c1保持，最终仍1条接受、1条拒绝、4个完整性缺口。新类型路径实际走通，但内容未通过，不能把正确的类型表达视为研究结论成立。证据：deep-research-evidence/inference-kind-328-real-stage-20261029.json。

扩大检查到全部315个Deep Research测试文件，固定最终源码的5662项全部通过（pytest494.15秒、外部499.75秒），源码与测试哈希稳定，无模型调用。与前述1097项重叠，不相加。证据：deep-research-evidence/research-328-broad-regression-20261029.json。
