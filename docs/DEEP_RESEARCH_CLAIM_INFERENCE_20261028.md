# 主表送达后的核查与推导类型

`.318` 在已结算 D1-v40 缓存上执行一次隔离的生成、修订和核查阶段。7 次调用全部成功结算，共 37,003 Token；没有自动重试、检索、恢复 D1-v41 或生产发布。7,465 条生产账本及全部运行 payload 精确保持。

这次主表确实到达生成模型。初稿给出两个数据集上 Ours 与原始 3D-GS 的 PSNR，并推算差值及“接近但非无损”的判断；但整条标成 reported。程序拒绝未直接报告的 0.30 及未绑定表测量。一次修订删除推导，最终一条已核查事实保留四个精确 PSNR 值，引用、行、组与基线对应；另一条边界仍因 scope_boundary_entailment_unresolved 被拒绝。完整性审核返回 checked、4 个缺口。最终仍缺有条件的核查判断，不能算内容通过。

边界审核原文把“接近缺乏量化标准”等理由标成 quantification=ambiguous、relation=undetermined。本次保留其失败状态，没有把理由中的“不能推出”解释成通过，也没有放宽明确量词和自身来源前提要求。该问题仍待进一步判断。

核查生成指令同时存在“推导量属于 inference”和“No ... inferred differences”的笼统禁令。新版本 `.319`、claimCheckContractVersion=3 消除这一冲突，并明确：包含论文观察值及自己的推导／有条件判断的点应为 inference，即使开头写“作者报告”；tableBindings 绑定被报告的输入单元格，不能把推算差值伪装成原文单元格。无需算术时优先简洁定性判断，不能凭数值差就认定感知等价或用户容差，也不能用安全的数值列表替代请求的判断。旧策略保持。

离线通过实际 make_synthesize_node 截获发送前请求：23,911 UTF-8 字节，仍在 24,000 字节窗口内，保留主表两片段及重训表注，missingPremiseBundles 为空，没有模型调用或生产写入。证据为 `deep-research-evidence/claim-inference-319-replay-20261028.json`。回放证明提示与材料到达，不证明新模型内容成功。`.319` 没有新增真实内容验证，独立验收不增加。

固定源码的 45 文件、746 项关联回归通过，pytest 120.08 秒、外部 125.328 秒，源码及测试哈希前后一致，无模型调用。新增检查同时证明旧策略仍保留原提示，且新指令不会让错误的 reported 差值越过独立数值核查。证据为 `deep-research-evidence/claim-check-319-regression-20261028.json`。

源码 `e43cd6da` 已按空闲快照流程重启原 Python 容器一次加载 `.319`。源码模块哈希一致，RAG/GROBID 健康，前端 HTTP 200；7,465 条账本、全部旧运行 payload、五组任务及完整索引/嵌入哈希精确保持，0 活跃、13 暂停保持。加载无新增模型请求。证据为 `deep-research-evidence/runtime-load-claim-check-319-20261028.json`。完整 DR0—DR5 和内容／独立验收仍未完成。
