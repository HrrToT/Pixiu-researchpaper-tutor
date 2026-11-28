# Java/Python 持久发布与回退集成演练

本轮使用独立 Java 进程、Python FastAPI HTTP 服务、全新 H2/SQLite，验证实际创建/激活接口、发布事件投递、丢回执后的重复投递，以及关闭新版入口后的报告读取与重启。没有切换用户服务或写入真实任务数据。

## 已验证的跨服务行为

1. Java 通过真实 Python HTTP 创建研究，先绑定任务再激活运行。图执行器替换为完成的空 Future，不执行研究图或模型。
2. 通过 SQLite 发布事务写入明确标注的合成报告和 outbox 事件，生产 PublicationDispatcher 实际通知 Java；Java 回读 Python 中指定版本并保存业务投影。
3. 在 Java 保存成功后模拟响应丢失，Python 事件保持待投递；Java 已有2份成果（原稿/可编辑稿）和1条对话记录。
4. 真实 PUT 编辑可编辑稿，同时尝试覆盖原始机器报告及 sourceRunId/sourceResearchId/reportVersionId/材料/来源；后端保留原稿和真实关联，用户正文正常保存并标为已编辑。
5. 对同一事件再次投递，Python 收到确认后清除待投递状态；Java 的完整任务 JSON 与用户编辑后完全相同，没有新增成果、对话或修订号。再次调用同一发布事务也没有产生新 outbox。
6. 关闭新版开关并重新初始化生产 Python 工厂后，经 Java 仍能读取报告正文和版本；状态不再提供补查动作。通过 Java 发起新的研究返回503，没有新增运行或模型账本。
7. 重启独立 Java 后，H2 中完整任务 JSON 保持一致，Java→Python 报告读取仍通过。

最终增强案例：2份成果、1条对话、任务修订号3（创建0、绑定1、发布2、用户编辑3）；重复投递未再增加修订号。两个案例均成功，Python/Java测试服务均停止，0模型调用、0生产写入。

## 验证范围

使用当前 Python 源码（回退修复5ad89bc3）与成果保护修复构建的 Java JAR，SHA-256：`3172bd62c53081536f8d57288ea4accd587303226b15ae028b667e58f655a4aa`。Python 仅监听127.0.0.1:8193，Java仅监听127.0.0.1:8189；Python requests 拒绝其他HTTP目标并禁用环境代理。测试未下载论文或发送外部材料。

这是**真实HTTP与持久存储的集成证明**。研究图工作线程被抑制，报告通过底层发布事务写入合成内容，未经过真实模型生成或科学核验；不能据此声称回答质量、真实研究生成或独立内容门槛通过。Python重启指关闭并重新初始化生产运行时/SQLite，HTTP路由线程保留；Java执行了进程退出及重新启动。因此也不将其等同于完整生产部署回退演练。

本轮没有新增生产功能改动；验证了前两项候选修复在独立跨服务环境协同工作。上述独立演练之后，当前Java/Python服务已加载两项修复，见[修复加载记录](DEEP_RESEARCH_SERVICE_FIXES_LOADED_20261112.md)。完整DR0—DR5、内容质量、独立验收及生产发布门槛仍未完成。

## 可复现入口

需已有项目Python依赖、JDK和项目JAR；端口已占用或run-id目录已存在时拒绝复用：

```powershell
.venv-refactor/Scripts/python.exe -X utf8 scripts/verify-research-publication-integration.py --java <java.exe绝对路径> --jar <项目JAR绝对路径> --run-id <唯一标识>
```

首次基础案例和增强案例证据分别为 `deep-research-evidence/publication-integration-first-20261112.json`、`deep-research-evidence/publication-integration-edit-replay-20261112.json`。包含实际HTTP路径、状态码、隔离边界及结果，不保存凭据。数据库和Java日志保留在对应tmp目录。源码摘要及关闭端口复核见 `deep-research-evidence/cross-service-publication-verified-20261112.json`。
