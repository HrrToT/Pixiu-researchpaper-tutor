# 停止状态的耗时记账（.405）

G1N-v10 在相关性评估中收到 HTTP 500，结果未知。公开状态按 startedAt/finishedAt 显示约 49 秒，原始预算却保留 elapsedSeconds=0。成功发布已有耗时写入，异常退出缺少相同处理；用户暂停后如果只按 updatedAt 展示，元数据编辑还可能让停止时长增长。

## 新运行行为

服务器冻结 `elapsedAccountingContractVersion=1`。在同一 SQLite 事务里，执行状态 running/stopping 离开到 waiting_user、paused、failed、cancelled 或 completed 时，保存当前墙钟耗时。普通阶段更新不增加记账字段。已停止状态的公开耗时读取保存值，不因 GET、重命名、迟到响应或出站发布操作继续增长。执行中的公开耗时仍使用既有 startedAt 时钟，并避免使用上次暂停的 finishedAt。

成功发布使用相同规则，预算和公开耗时统一到同一事务时间。恢复进程中断的 running/stopping 时，只能得到原 startedAt 到恢复时刻的墙钟界限；私有字段明确标为 `recovery_wall_clock_upper_bound`，不声称知道宕机期间真正执行了多久。恢复后的再次扫描不重写已暂停记录。

此变更不延长原墙钟截止时间，不修改 startedAt，不增加 18 次调用、10 万 Token 或 360 秒上限。既有澄清等待扣除仍按原恢复规则执行一次；本轮没有把用户暂停时间改为额外免费预算。预算 tokens 仍是保守的预算占用，未知预留不是已确认的模型消耗；本轮未改变预留、结算、未知保护或前端统计。

## 兼容与验证边界

旧记录没有新字段时保持原规则，不补写 G1N-v10 的历史 0 秒，不迁移已暂停的 14 个运行，也不切换契约重发未知请求。

- 实际 worker 的离线 HTTP 500 与 402 路径均复现了 49 秒持久化；未知仍保留预留并阻止 begin_execution。
- 暂停、等待、失败、完成和取消后，元数据编辑与重新打开数据库不改变已冻结耗时。
- 迟到响应只写调用审计，不改变暂停运行和预算；澄清等待扣除一次后继续使用原剩余额度。
- 临时 SQLite 中，旧运行的元数据更新及恢复 payload 与提交 c7786b9e 逐值一致。保存 G1N-v10 的前瞻副本在其原停止时间得到 49 秒，原文件和预留保持不变。

保存输入回放证据：`deep-research-evidence/elapsed-accounting-405-saved-legacy-replay-20261107.json`。这是离线可靠性验证，不是模型质量、未知结果恢复或完整 DR0—DR5 验收。真实 G1N-v10 仍保持原请求身份与 unknown/paused 状态，不自动重发。
