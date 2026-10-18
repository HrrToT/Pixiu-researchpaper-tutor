# Deep Research 单实例备份、恢复与回退

2026-10-18最新检查点：Python/Java `.153`，源码`27ac4beb`。Java包为`tmp/dr153-java-target/backend-java-0.0.1-SNAPSHOT.jar`，PID161948、官方校验JDK21、本机隐藏进程；H2备份`tmp/dr153-runtime-backup-20261018/academic_db.mv.db`。加载保护曾在旧PID退出窗口中止；后续已从确认停服状态仅启动一次，禁止再次运行旧停服脚本。完整91个任务、3,747条账本及9个未知暂停身份保持。只读动作回执API已实际验证，验证CLI恢复尚未接入，不能据此直接重试未知请求。当前内容尚未验收。证据：[运行时保留](deep-research-evidence/action-receipt-java-runtime-20261018.json)、[实际GET无写入](deep-research-evidence/action-receipt-live-api-20261018.json)。

2026-10-18当前检查点：Python `.151` / `03d6c25e`，完整回归2,389项通过；Java `47f94b28`、前端 `c3843700`未改。加载时无活动研究，3,708条账本前后相等；两例单次诊断后3,747条、0活动、9个历史未知暂停身份保持。新契约由服务器固定，旧任务不补跑新规则。内容仍未验收，PR保持草稿。证据见[加载核对](deep-research-evidence/runtime-load-dr151-human-grounding-20261018.json)及[运行后账本](deep-research-evidence/runtime-postcases-dr151-20261018.json)。

适用：当前 Java/H2 + Python/SQLite + Chroma 单实例部署。2026-10-13 已在本机完成配套恢复演练；不是多实例、生产高可用或在线热备方案。质量发布门槛仍以实施记录和固定案例为准。

## 备份边界

必须一起保存：

| 内容 | 本机开发位置 | 作用 |
| --- | --- | --- |
| Java 数据库 | `backend-java/target/stage0-data/academic_db.mv.db` | 任务、消息、笔记、成果、研究投影、论文原文件和解析结果 |
| Python 业务数据 | `ai-service-python/data` | 原研究、任务操作等已有业务记录 |
| 新版研究库和 checkpoint | Linux 卷 `academic_dr_runtime_20261012` 中 `/research_data/store` | 执行状态、证据、调用账本、检查点、外部全文 |
| Chroma 索引 | `tmp/dr-container-validation/chroma` | 当前论文向量索引 |
| Java 包、Python 镜像和源码版本 | 本次部署实际使用版本 | 与数据契约一致的程序 |
| 配置清单 | 目录、端口、Provider、功能开关 | 恢复实际挂载和路由；密钥通过原有安全配置注入 |

这些是本机实测位置，不是固定生产路径。先检查实际 Java 启动参数、容器挂载和环境中的目录项。不要把旧 `tmp/dr-live-data` 当作当前运行库。不要把密钥写入备份日志或提交仓库。

## 一致备份

1. 从权威研究库检查 `queued/running/stopping`，等待结束或通过正常操作暂停；不要将未知调用重新发出。
2. 保存代表性任务、成果和论文文件的内容指纹。关闭 Java 入口并停止 Python 服务，防止备份期间新写入。
3. 在停服后复制 H2、Python 业务目录和 Chroma 到一个全新备份目录。不要直接复制运行中的 H2 文件或仅复制 SQLite 主文件而丢掉 WAL。
4. 在可访问 Linux 数据卷的工具容器中运行研究备份工具：

   ```sh
   python /app/scripts/deep_research_backup.py backup \
     --database /research_data/store/research.sqlite3 \
     --sources /research_data/store/sources \
     --destination /backup/research --services-stopped
   python /app/scripts/deep_research_backup.py verify /backup/research
   ```

   `--services-stopped` 是操作人的停服确认，不负责停止服务。工具用 SQLite backup API 导出独立数据库，校验完整性及被引用全文。源连接使用只读模式，但 WAL 数据库可能需要创建共享内存文件，数据卷的只读挂载可能导致 `unable to open database file`；停服后使用正常可写挂载，由工具保持业务记录只读。
5. 对备份全部文件计算 SHA-256，最后写入部署清单；保存实际应用包及版本信息。恢复原服务并确认健康及原任务内容不变。

## 恢复到隔离副本

先恢复到新目录/新 Linux 卷，不覆盖原库。Windows 文件夹绑定中的研究 SQLite 曾复现重开 `disk I/O error`，当前已改用 Linux 命名卷；恢复继续使用 Linux 卷。

```sh
python /app/scripts/deep_research_backup.py restore \
  --backup /backup/research --destination /restore/store
```

Java 使用复制的 H2 文件和备份包，设置新端口（本次 `8083`），将 `PYTHON_URL` 指向恢复 Python（本次 `http://127.0.0.1:8003/api`）。Python 必须使用独立的数据、索引和研究挂载，并明确设置：

```text
DEEP_RESEARCH_DB_PATH=/research_data/store/research.sqlite3
DEEP_RESEARCH_SOURCE_DIR=/research_data/store/sources
CHROMA_DB_PATH=/app/chroma_data
CHROMA_DB_DIR=/app/chroma_data
DEEP_RESEARCH_V2_ENABLED=false
DEEP_RESEARCH_EXTERNAL_ENABLED=false
DEEP_RESEARCH_FULLTEXT_ENABLED=false
```

本次恢复检查将模型密钥置空，不执行新研究。嵌入模型使用已有离线缓存。不要漏掉 `CHROMA_DB_PATH`：默认目录位于源码挂载内，会因只读挂载导致索引初始化失败。Docker Desktop 的本次内部网络未发布主机端口，容器内 200 不能代替 Java 到 Python 的链路验证；改用正常开发网络并明确绑定本机端口后才通过。

预热完成后检查：

- Java 能读取既有任务、消息、笔记、成果与研究；从 Java 下载原论文并核对 SHA-256。
- 已存报告仍可读；关闭新版入口时新请求被拒绝，不能交给旧引擎继续执行。
- 对同一既有运行同步发布两次，消息和成果均不增加。
- 比较全部研究主要内容及完整调用账本指纹；验证外部全文缓存哈希和按论文身份限定的索引数量。
- 结束演练后停止隔离服务，保持原服务可用；保留备份和验证记录。

## 本次实测结果及范围

证据摘要：[`deep-research-evidence/deployment-20261013.json`](deep-research-evidence/deployment-20261013.json)。本地原始记录位于 `tmp/dr-deployment-drill-20261013`。

- 配套备份与新目录恢复通过；33 条研究主要内容、971 条完整调用账本前后指纹一致。
- 代表性 D2 任务经 Java API 核对：2 篇论文、8 条消息、16 项成果、15 条研究记录及报告指纹一致。该任务笔记为 0 条，不以此宣称非空笔记编辑路径已覆盖。
- 两篇实际 PDF 字节和哈希一致；被引用外部全文缓存哈希一致。
- 恢复索引中四篇冻结论文分别为 55、82、57、56 个片段。集合含其他旧身份，总数 363，不能把总数当四篇论文数量。
- 新版开关关闭，实际新请求返回 503；重复发布两次均 200 且没有新增消息/成果；账本没有新增调用。

此演练验证本机停服一致备份、恢复读取和关闭入口后的行为。它不替代真实研究内容质量、完整浏览器体验、生产环境发布演练或多实例故障转移。恢复检查使用的源码包含表格提取修复 `14ad3f8`，Java 代码本轮未修改。

## 固定案例执行工具

从仓库根目录运行。默认只预览清单中的冻结问题、材料身份和预算，不发HTTP请求：

```powershell
.venv-refactor/Scripts/python.exe ai-service-python/scripts/verify_deep_research_case.py H1
```

在已授权发送范围内，显式指定`--submit --attempt 1`才允许一次研究提交。同一案例和attempt已有回执时只GET查询，即使再次传入`--submit`也不会重新生成。研究POST前以独占文件写入并fsync意图；未收到确认则保持unconfirmed，后续运行拒绝重发，需要先核对服务端请求账本。不要删除不确定回执或用新attempt绕过核对。

默认回执目录为`tmp/dr-acceptance-receipts`，`CASE-vN.json`记录意图和运行身份，`CASE-vN.result.json`保存最近一次读取。不同输入不能复用同一回执；D5还需`--task-id`及`--parent-run-id`，不能创建无父运行的追问。D6/H6故障用例使用离线集成测试，不走模型提交入口。

工具不会把服务端completed标记当作质量通过，也不会把问题清单中的预期答案发送给模型。留出案例一旦用于调参，仍须按设计稿退出留出集并登记替换。


## 2026-10-18 当前开发实例

当前Java使用`tmp/dr119-java-target/backend-java-0.0.1-SNAPSHOT.jar`（源码47f94b28、PID81764），仍连接`backend-java/target/stage0-data/academic_db`。Python为`academic-dr-runtime`（.119），持久卷`academic_dr_runtime_20261012`不变。加载核对85个任务、3,210条账本、9个未知暂停记录，未发模型请求。停服H2备份在`tmp/dr119-runtime-backup-20261018`；之前的`tmp/dr118-runtime-backup-20261018`保留。

Docker启动曾被旧Unix套接字阻止，已保留运行时目录隔离副本`C:/Users/Lenovo/AppData/Local/Docker/run.quarantine-20261018-dr118`及`C:/Users/Lenovo/AppData/Local/docker-secrets-engine.quarantine-20261018-dr118`，没有删除数据卷或重置Docker。最后一次端点备份由既有WSL脚本完成。该故障不得通过重复重启或恢复无关数据来处理。

旧同项目容器`ai_service_python`原为`restart=always`，会自动抢占8000；现保持停止且`restart=no`。如需要恢复旧部署，先停止新版实例再执行`docker update --restart=always ai_service_python`；不能让两者同时争用端口。新版实例保持原`restart=no`，由明确的开发启动操作管理。其他项目容器未修改。


## 2026-10-18 依赖调度加载

Python已加载64104406（`.120`），Java/前端仍为前节`.119`。确认无活动研究后重启一次`academic-dr-runtime`，3,210条账本与9个未知暂停记录全量相等，RAG/GROBID健康。依赖契约仅作用于新运行，不能将历史unknown换编号重跑。真实案例开始后不得为文档提交再次重启；下一次源码加载仍需先检查活动研究。运行证明见`deep-research-evidence/runtime-load-dr120-dependencies-20261018.json`。


## 2026-10-18 条件身份检查加载

Python当前为92598500（`.123`）。加载前无活动研究，3262条完整账本与9个历史未知暂停记录前后一致；RAG/GROBID健康。Java/前端沿用`.119`。既有case回执与原回答不覆写，任何真实案例期间不为文档提交而重启。加载证明见`deep-research-evidence/runtime-load-dr123-condition-identity-20261018.json`。


## 2026-10-18 逐条事实核验加载

Python当前1bf96858（`.124`）；确认无活动研究及新论文解析已完成后重启一次，3,284条完整账本和9个未知暂停身份相等，RAG/GROBID健康。后续真实运行期间不再重启。证明见`deep-research-evidence/runtime-load-dr124-fact-isolation-20261018.json`。


## 2026-10-18 原生JSON路由修复加载

Python ebcf570c（`.126`），可信消息契约2；旧契约1保留原身份。确认无活动研究后重启一次，3,299条完整账本和9个未知暂停身份一致，RAG/GROBID健康。证据：`deep-research-evidence/runtime-load-dr126-routed-json-20261018.json`。


## 2026-10-18 修订进展与比较目的加载

Python 74673c96（`.128`），原生JSON契约3/修订进展契约1；旧运行规则保留。确认全部六个新验证运行已终态后重启一次，3,440条完整账本及9个历史未知暂停身份一致；没有追加Provider请求。`deep-research-evidence/runtime-load-dr128-purpose-20261018.json`。


## 2026-10-18 方法细节与中性规划加载

Python 2ee36ac2（`.130`），来源精度契约1/原生JSON契约4；旧运行保留原规则。确认无活动研究后重启一次，3,459条完整账本与9个历史未知暂停身份一致；RAG/GROBID健康。`deep-research-evidence/runtime-load-dr130-source-precision-20261018.json`。

## 2026-10-18 原PDF补查、方法前提与回答格式加载

Python先加载1e6daa48（`.133`），确认无活动研究，3,482条完整账本与9个历史未知暂停身份相等。H4F-v2/H1F-v3各执行一次，结束后3,526条账本，仅这两例追加44条已结算调用，历史行哈希保持。

随后加载4bd2a7d3（`.135`）；完整2,193项离线回归通过，加载前后3,526条账本和9个暂停身份一致，RAG/GROBID健康。H1F-v4仅执行一次，结束后3,547条账本、无活动研究，原账本全量哈希及历史暂停身份保持。上述诊断均无新unknown，原有unknown不重新发出；手动保留的旧回答不改写。Java/前端仍沿用前述`.119`源码/包，本次无数据迁移、无卷重置。

证明：`deep-research-evidence/runtime-load-dr133-original-pdf-priority-20261018.json`、`runtime-postcases-dr133-20261018.json`、`runtime-load-dr135-method-premise-format-20261018.json`、`runtime-postcases-dr135-20261018.json`。这些是加载与记录完整性证据，实际内容门槛仍见各案例人工评分；不得为文档提交再次重启服务。

## 2026-10-18 分项取证与实际语义工厂修复加载

8be225d9（`.136`）和e28e7474（`.137`）分别在无活动研究时加载，3,547条完整账本及9个历史未知暂停身份前后相等。`.137`H1F-v5执行一次，追加22条已结算记录，结束后3,569条账本；原行哈希、暂停身份保持，无新unknown。

f55df4ca（`.138`）在2,222项完整回归通过后加载；3,569条账本和9个暂停身份相等，RAG/GROBID健康。新runtimeSemanticContractVersion=1接上实际工厂的单条事实策略；旧生产批次不迁移、不改写未知请求指纹。Java/前端、数据库、持久卷和来源范围不变，未执行`.138`真实模型案例。

证明：`deep-research-evidence/runtime-load-dr136-criterion-coverage-20261018.json`、`runtime-load-dr137-criterion-budget-20261018.json`、`runtime-postcases-dr137-20261018.json`、`runtime-load-dr138-runtime-isolation-20261018.json`。真实质量仍见H1F-v5人工失败评分；旧基础组件检查不能替代实际工厂验证。

## 2026-10-18 数字词、取证顺序与修订指令加载

4a2da0e7（`.140`）通过2,264项全量回归后加载，3,569条旧账本及9个未知暂停身份前后相等。H1F-v6完成后3,591条账本；原行哈希保持。

5da25372（`.142`）通过2,294项全量回归后加载，3,591条账本及9个暂停身份前后相等，RAG/GROBID健康。H1F-v7及D1-v17各执行一次，追加39条已结算记录，总3,630条；原前缀及暂停身份保持，无活动研究。两例都partial，不能当作质量通过。事实隔离在v7实际两个单事实请求中得到确认。

证明：`deep-research-evidence/runtime-load-dr140-quantity-priority-20261018.json`、`runtime-postcases-dr140-20261018.json`、`runtime-load-dr142-revision-instructions-20261018.json`、`runtime-postcases-dr142-20261018.json`。旧契约、回执、未知预留、原文与用户成果均不迁移或改写；Java/前端/持久卷保持。

## 2026-10-18 同时反馈与原文重建修订加载

959011ea（`.144`）通过2,313项全量回归后加载，3,630条旧账本和9个暂停身份前后相等；H1F-v8、D1-v18结束后为3,666条，均未通过完整内容。

77e16747（`.146`）通过2,329项全量回归后加载，3,666条旧账本和9个暂停身份前后相等，RAG/GROBID健康。H1F-v9、D1-v19追加42条已结算记录，总3,708条；旧前缀哈希及暂停身份保持。实际图的修订输入摘要与新模式、冻结要求匹配；两例仍partial/inconclusive，不能作为质量通过。

两次低推理组件探测使用独立本地SQLite和canonical回执，原生产数据库只读，凭据留在运行容器；原生产前缀及新42行均复核不变。探测结果没有提升全局模型路由，也不代表生产路径内容验收。回退或恢复不能用改变后的提示重新生成旧的未决请求。

证明：`deep-research-evidence/runtime-load-dr144-table-condition-feedback-20261018.json`、`runtime-postcases-dr144-20261018.json`、`runtime-load-dr146-source-redraft-20261018.json`、`runtime-postcases-dr146-20261018.json`、`factual-repair-low-component-probes-20261018.json`。Java/前端和持久卷保持。
