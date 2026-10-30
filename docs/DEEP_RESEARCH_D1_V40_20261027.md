# D1-v40：表注进入证据池，事实核查保留两点，完整性仍失败

原 D1 问题、材料和 18 调用／100,000 Token／360 秒预算仅提交一次。运行 `dr_run_eaf2768447e55aab8fda154515219a4d`，源码 `e4f27c77`、提示 `.314`。124.221 秒，13 次模型调用、54,744 已结算 Token；全部调用成功结算，费用未知。结果 completed/partial，不计内容或独立验收。

## 修复实际到达的位置

物理页 6 的规范 PDF chunk 29 进入 sources，并提取出两个证据片段，其中一条原文明确包含“re-trained 3D-GS”、原代码与配置、NVIDIA A6000 和 marked by 星号说明。这证明新表注链路实际进入研究取证，不只是在隔离查询里出现。

最终两条声明通过语义核查：作者在 Mip-NeRF 360 报告 SSIM 下降 0.007、视觉接近；以及这些有限引用不能建立对所有数据集／场景的推广。它们主要引用引言摘要和视觉描述，tableBindings 均为空，没有直接利用主表两行及重训表注。故本例没有再次触发 table_condition_not_displayed，但也不能证明主表身份生成已经稳定正确。报告仍没有给出足够具体的成立条件、指标非无损说明，可读性也仍受重复范围模板影响。

初稿范围命题因 `scope_expression_premises_not_bound` 被拒绝；一次修订后进入正常重新核查，修订声明被保留。新 repairCompaction 阶段确实执行并保存对应 AST，但该候选已在字数内，没有产生 synthesize_compact 模型请求。不能把这一例称为实际超长压缩成功。

## 完整性审核的问题

初始审核生成“仅在 Mip-NeRF 360 验证”“其他数据集或场景未验证”的需求及缺口提示。它将一条引言结果的有限范围解释成论文整体缺席，和已有多数据集主表证据不一致。该诊断不作为论文事实采纳。

修订后审核又把若干 aspects 判为 covered，却仍保留“需要明确未验证其他数据集”的 partial 诊断；整体 answer_scope 所有子项 covered，gapDetail 的 criterionIds 和 aspectIds 却均为空。原校验拒绝这一矛盾，coverageStatus=invalid_response，diagnosticErrors=[answer_scope]，未将其改成完成。

下一步应修正完整性审核的需求来源和职责：按照原始用户／冻结研究义务审查已有回答，不能自行把论文事实或所谓缺席变成新增交付要求；同一回答多个已支持点可共同满足一个真实要求，不能因审核自己漏绑而要求用户再写一遍。此问题尚未修复；不通过去掉诊断校验、给旧结果改判或再跑同题来处理。

## 保全

新增 25 条账本仅属于本运行，旧 7,436 条前缀及全部旧研究 payload 精确保持。当前 7,461 条、0 活跃、12 个旧未知暂停保持；没有自动重试。

精简证据：`deep-research-evidence/D1-v40-quality-20261027.json`。原始响应、调用与保全记录：本地 `tmp/dr-acceptance-receipts/D1-v40.{json,result.json,payload.json,calls.json,preservation.json}`。原 DR0—DR5、内容质量与独立验收仍未完成，独立验收仍为 0/5。
