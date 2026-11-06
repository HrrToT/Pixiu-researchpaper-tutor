# 比较审核的原文字段引用（.398）

G1N-v7 的 c1 修订去掉了无引文支持的 0.5，但比较审核器手工抄写高斯公式时改变了字符。原有逐字引用检查正确拒绝该元数据；原失败不回填为通过。

本次新增服务器冻结的 auditSourceFieldsContractVersion=4：scopeAudit 保持已有字段路径，comparisonAudit 的提示示例也改为 evidenceId + path。路径由既有解析器还原为该条证据自身未改写的字段，条件比较仍必须给出原文中的实际 value。没有修改来源归属、版本覆盖、条件核对、数值核验或独立语义支持的通过规则。旧版本提示保持。

保存的真实 c1 原始审核离线回放仍返回 comparison_premise_quote_mismatch；仅在独立的前瞻副本把手工引文改为同一证据的 quote 字段路径后，该绑定检查通过。全程零模型调用，不写回历史运行。此回放不能证明完整回答通过：c1 仍遗漏 PGSR 平面高斯表示，其他事实与材料不足表达也仍有缺口。

验证证据：

- comparison-path-398-saved-audit-replay-20261106.json：保存输入的前瞻绑定回放。
- comparison-path-398-legacy-prompts-20261106.json：8 种旧审核提示与旧提交逐字一致。
- comparison-path-398-associated-final-regression-20261106.json：冻结关联回归的最终结果。

完整 DR0—DR5 尚未验收通过；独立内容验收积分维持 0。
