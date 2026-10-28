# 表格列名的受控中文显示

`.326` 新生成 c1 的表格绑定、方法标签和数据组均与原单元格一致，但正文把源列名 Size 写成“大小45MB对734MB”，本地硬门槛要求英文列名逐字出现，导致 table_condition_not_displayed。直接对各绑定逐项核对，缺失项为 Size，而不是 Datasets 通用后缀或 Ours／3D-GS 方法可见性。

`.327` 新建 tableReferencesContractVersion=2，只为 Size→大小、Mem→内存开放固定列名翻译。其他列名不猜测翻译，方法名、星号、重训／消融变体、数据集、层级分组、单位和值均按原规则检查。原版本 0／1 保持，不修改旧结果或单元格。推断类原单元格引用有效性检查在版本 2 继续启用。

这只解决显示语言差异，不批准论文结论。实际保存的 c1 原文和证据不变时，旧本地检查拒绝、新本地检查通过；语义夹具返回 unresolved 时，新版本仍拒绝。错误数值、错误单元格、错误方法、缺星号、错数据集、缺聚合层级和无关列名均继续拒绝。67 项定向测试通过，实际回复回放无模型调用与生产写入，证据：deep-research-evidence/metric-translation-327-actual-replay-20261029.json。

最终固定源码的 62 文件、1,078 项关联回归通过（pytest 90.59 秒、外部 94.75 秒），全部源码及测试哈希前后稳定，无模型调用。证据：deep-research-evidence/metric-translation-327-final-regression-20261029.json。
