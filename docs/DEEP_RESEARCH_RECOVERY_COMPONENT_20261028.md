# 服务恢复、中断运行与独立完整性审核

读取中断前已确认的 D1-v41 回执，runId 为 `dr_run_1c0c2e6510165086962408b8e3cf698b`。没有重新提交该运行。最初 Java/Python 不可达，Docker Desktop 后端在启动阶段因不可访问的遗留 Unix socket 退出。

## 恢复与保全

在无 Docker 进程时确认 `Docker/run` 只有运行时 socket；单个重解析点无法读取／改名，改为将原目录整体改名留存。随后 Secrets Engine 的旧 `engine.sock` 又阻断启动，确认该目录只有一个零字节 socket、没有凭据文件后，同样改名留存。失败启动还新留了一次推理 socket；两处运行时目录同时为空后，引擎恢复，版本 29.1.3。保留目录为 LocalAppData 下的 `Docker/run.stale-20261028`、`Docker/run.stale-20261028-second` 与 `docker-secrets-engine.stale-20261028`。没有恢复出厂、改设置、删除或重建卷。

Python 启动前，从停止的原容器冷备整个 SQLite store 到本地 `tmp/runtime-recovery-20261028/python-store`。原 H2 数据库也在启动前备份，SHA-256 为 `07F1E89CDD12FD50A302957CBD0629BABB713AE558F8A46EC1CDE545174463B4`。原容器、Java JAR、H2 路径及前端现有依赖继续使用。恢复后 RAG/GROBID 健康，Java 任务接口和前端 HTTP 200；四组受保护工作区与 D1-v41 前快照精确相同。全部 981 条索引及嵌入哈希仍为 `9196054db7ac32450eb86fc91cfb12de27c732469e4cf629bf06857a3490788d`。证据：`deep-research-evidence/runtime-recovery-20261028.json`。

## D1-v41 实际状态

冷备显示该运行还在 acquire 阶段：resolve_brief 与 plan 两次模型调用均 succeeded/settled，已结算 2,565 Token；两条 retrieve 调用仍 pending，预留 Token 均为 0。它没有生成回答，也没有进入新完整性审核。

原恢复代码将该运行暂停，两条中断检索改为 unknown；没有发送新的模型请求。不能把它说成两个未结算模型请求，不能通过换 attempt 重新提交该例，也不能计内容质量失败或成功。旧 7,461 条账本前缀及全部旧运行 payload 保持；现 7,465 条、0 活跃，原 12 个暂停保留，新增本次检索中断暂停。冷备 payload/calls 和恢复后的记录分别留在 `tmp/dr-acceptance-receipts/D1-v41.*.json`。精简证据：`deep-research-evidence/D1-v41-interrupted-20261028.json`。

## 一次独立审核组件验证

使用已完整保存的 D1-v40 已接受回答和证据，对 `.315` 固定清单审核单独执行一次。没有恢复 D1-v41、重新检索或生成答案。隔离 SQLite 中使用只读来源副本；发送前仍通过原 Java 材料快照作用域检查，使用原 ScopedModelClient、tracked 调度、预算和请求格式，原始 wire 在发送前保存；脚本仅允许一次 provider 提交，无自动重试。生产研究与账本前后完全一致。

这一次成功结算 6,687 Token（输入 6,084、输出 603），费用未知。返回 checked、四项 partial、四个缺口、diagnosticErrors 为空。它遵循固定 ID 协议，没有新增“其他数据集未验证”的必要项；仍认为旧回答没有充分区分结果、成立条件和未验证范围。该结果只证明这一保存输入上的协议遵循，不是完整流程、内容或独立验收通过。原请求、结果及隔离账本在本地 `tmp/component-request-coverage-20261028/receipt`；精简证据：`deep-research-evidence/request-coverage-component-real-20261028.json`。

进一步核对发现冻结计划的三条义务都被锚定到用户第一句，各自 completionCriteria 重复“核查压缩后图像质量接近原始3DGS这一说法”。后面的显式区分维度没有进入这些标准。下一步修复原问题总检查与修订交接，而不改判旧结果或重复发送中断运行。
