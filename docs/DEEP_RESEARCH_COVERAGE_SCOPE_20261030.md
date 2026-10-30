# 章节定位与覆盖字段目录修复

代码提交 `52f4a864`，提示版本 `dr-v2.20261030.366`。完整 DR0—DR5 尚未验收，独立验收仍为 0。本轮没有新增真实模型调用。

## 修复与验证

- 新运行的 identificationLocatorContractVersion=1 区分“第5节中”的来源定位与真正要求回答的数值对象。只对明确的章节定位表达生效；实际数量、显式章节编号问题与旧运行保持原有检查。
- coverageDiagnosticsContractVersion=3 按每项固定检查提供允许引用的答案字段。普通正文讲解不提供 sourceAccessSummary；明确要求访问情况的检查仍可使用它。返回后的非法绑定仍被拒绝，不通过删除错误字段改判通过。
- 相同字段目录共享存储，展开后与原目录完全一致。既有实验案例目录从 4,496 字节降至 1,125 字节，保留每项检查的范围与绑定身份。
- 最终关联回归为 126 文件、2,343 项通过，221.53 秒，1 项 PyPDF2 弃用警告。聚焦检查与该范围重叠。Java 未变化，沿用此前 612c324e 的 164 项测试，不宣称本轮重跑。
- 原 X4G-v2 响应离线回放：3 项缺口减少到 1 项；两项章节数字误判消除，额外的 sourceAccessSummary 绑定仍失败。原始模型响应及旧运行结果没有改写；这不是新的真实模型验收。

证据见 `deep-research-evidence/coverage-366-shared-confirmed-associated-regression-20261030.json`、`coverage-366-shared-catalog-original-response-replay-20261030.json` 和 `coverage-366-catalog-capacity-20261030.json`。

## 一次授权的 WSL 恢复结果

确认没有运行中的 WSL 发行版后，执行一次 `wsl --shutdown`，退出码 0；随后正常 `docker desktop start --detach --timeout 30`，命令退出码 0。引擎没有恢复，Docker API 管道不存在。未再次关闭 WSL，未重置、删除数据卷或重建容器。

启动日志明确报错：Inference manager 无法移除 `C:\Users\Lenovo\AppData\Local\Docker\run\dockerInference`，Windows 返回系统无法访问此文件。只读文件检查显示它是零字节 ReparsePoint，fsutil 同样返回错误 1920。日志随后记录 Quit 并关闭后端；该 Quit 不是本轮助手通过 UI 执行的动作。只读窗口枚举没有 Docker 窗口。

Docker 官方仓库 issue 15044 中有相同端点报错和将端点所在目录改名保留的用户报告：<https://github.com/docker/for-win/issues/15044>。报告涉及其他版本和硬件，因此只能用于制定可逆排查方案，不能证明本机最初故障由 Resource Saver 或磁盘损坏引起。

下一步候选修复是在确认 Docker 全部退出后，将 `Docker\run` 改名为唯一备份目录，保留原端点，再正常启动一次。这涉及项目目录之外的 Docker 运行目录，需要另外确认；尚未执行。不得触及 Docker 的 wsl、容器、镜像或数据卷目录。

## 恢复后的验收顺序

先核对原持久化数据：最后捕获 8,061 条账本、0 活动、13 条历史待核对记录；11 个任务；1,102 个索引片段及完整索引哈希 `1e91bfa73ba4a374a6cea68be25639c269fac493d5eda61162448bf500ff6118`。这些是停机前的最后证据，不代表已经完成恢复后复读。

数据核对后确认实际加载 .366，再提交一次固定开发复测 X4G-v3，保持每例 18 次调用、10 万 Token、6 分钟上限，不重发已结算的旧案例。数值比较、实验方案、证据不足、增量继续、恢复发布、产品审计及新的独立案例仍待完成。
