# 表格列名的受控中文显示

`.326` 新生成 c1 的表格绑定、方法标签和数据组均与原单元格一致，但正文把源列名 Size 写成“大小45MB对734MB”，本地硬门槛要求英文列名逐字出现，导致 table_condition_not_displayed。直接对各绑定逐项核对，缺失项为 Size，而不是 Datasets 通用后缀或 Ours／3D-GS 方法可见性。

`.327` 新建 tableReferencesContractVersion=2，只为 Size→大小、Mem→内存开放固定列名翻译。其他列名不猜测翻译，方法名、星号、重训／消融变体、数据集、层级分组、单位和值均按原规则检查。原版本 0／1 保持，不修改旧结果或单元格。推断类原单元格引用有效性检查在版本 2 继续启用。

这只解决显示语言差异，不批准论文结论。实际保存的 c1 原文和证据不变时，旧本地检查拒绝、新本地检查通过；语义夹具返回 unresolved 时，新版本仍拒绝。错误数值、错误单元格、错误方法、缺星号、错数据集、缺聚合层级和无关列名均继续拒绝。67 项定向测试通过，实际回复回放无模型调用与生产写入，证据：deep-research-evidence/metric-translation-327-actual-replay-20261029.json。

最终固定源码的 62 文件、1,078 项关联回归通过（pytest 90.59 秒、外部 94.75 秒），全部源码及测试哈希前后稳定，无模型调用。证据：deep-research-evidence/metric-translation-327-final-regression-20261029.json。

`.327` 已从 821d6f97 加载，7,465 条账本、全部旧 payload、五个任务和完整索引摘要保持；0 活跃、13 旧暂停，RAG/GROBID 正常、前端 200。加载证据：deep-research-evidence/runtime-load-metric-translation-327-20261029.json。本版本尚无新增真实模型质量结果，不能把原 .326 失败案例升级为通过。

`.327` 对已结算 `.326` 初稿重新进行独立核查和修订，共 5 次成功结算、28,052 Token，无未知、无重试、无新生成或检索、未发布生产。原因“大小”被拒的 c1 本次通过核查，c2 因只引用未支持全部数据集／指标的片段而拒绝，完整性仍有四个缺口。修订又罗列两组全部指标，精简后不能容纳共享预算，repairDraft 为空，未替换原已核查内容。本例证明中译误拒修复实际生效，不代表内容通过。

下一项核对生成要求与修订类型：系统要求补充自己的有条件判断，但修订通用契约又要求 same claimId/kind；原 c1 为 reported，无法合法改为包含推导判断的 inference。需在明确缺少判断的核查修订中支持受控的 reported→inference 转换，保留原身份与证据范围，再按新类型重新核查，不能将更改类型当作批准。证据：deep-research-evidence/metric-translation-327-real-stage-20261029.json。
