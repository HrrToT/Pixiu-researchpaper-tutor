# 解析修复后的当前完整离线回归

4bcb7306代码状态下，413个Deep Research模块、7,433项全部通过；0失败、0错误、0跳过，只有一条既有PyPDF2弃用警告。pytest约376秒，包含记录及源码复核的总耗时约383秒。测试期间前后源码摘要相同。

原411模块完整保留，新增PDF Form解析9项及H6故障链5项，合计比此前7,419项增加14项。本次完整证据对应解析修复后的代码，不再以旧完整结果加局部检查推断当前全套通过。

## 执行与证据

入口为 `scripts/verify-deep-research-offline.py`，本次使用run-id `current-full-after-pdf-20261112`，baseline为此前411模块JUnit。运行器在测试前保存参数、精确模块清单、基线摘要和所有相关Python源码摘要；收集钩子拒绝清单变化。每次运行创建独占目录，既有目录/证据存在则拒绝，避免清空先前证据或覆盖结果。原前后源码核对、JUnit及日志在结果文件中分别留摘要。

正式结果：`deep-research-evidence/current-full-after-pdf-20261112.json`。原始日志、输入清单及JUnit在 `tmp/research-offline-current-full-after-pdf-20261112/`。本次记录器正常完成，没有重复测试或证据恢复步骤。

命令供当前工作区复核使用；再次运行应换一个未使用的run-id，不能重用本次目录：

```powershell
.venv-refactor/Scripts/python.exe -X utf8 scripts/verify-deep-research-offline.py --run-id <新的唯一编号> --baseline-junit tmp/research-offline-current-full-after-pdf-20261112/junit.xml
```

测试排除live_llm，既有离线护栏生效。H6此次作为完整回归中的五项重复检查，不改其首次执行记录，也不新增独立信用。没有调用真实模型或运行五个内容留出。

## 生产与剩余门槛

完成后只读确认生产仍为365研究、9,226调用：244完成、106失败、15暂停未决，0活动运行。没有将隔离测试资料写入生产库或改动历史暂停记录。

官方余额查询仍为-0.19 CNY、is_available=false，证据 `provider-balance-current-full-20261112.json`。账户未恢复前不发送必然被拒的生成请求，也不消耗五个新内容留出。既有验证授权保持，不需要再次批准。

当前已经完成的是本次完整自动回归、H1—H5定义准备与H6离线工程故障验收；DR0—DR5整体仍未完成。下一步为当前原问题的新手机制解释、完整多论文比较和完整实验开发验证，开发质量达标后再执行H1—H5、逐条原文人工核查、真实报告交互及最终发布核对。旧失败、未知、退休材料、用户省略项和原预算保持；自动通过与定义齐备均不能代替内容质量。
