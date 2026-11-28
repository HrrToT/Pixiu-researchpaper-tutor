# 计费拒绝的保全与可见错误

带完整生成上下文的 `.321` 隔离核查已执行 4 次请求：3 次成功结算，共 16,337 Token；第 4 次明确返回 HTTP 402，没有待定或未知请求，没有重试，也未进入修订。原始响应与原 payload 保留，另追加 terminal-payload.json 将仅 `/tmp` 中的隔离诊断标为 failed。生产 7,465 条账本与全部研究 payload 精确保持。

当前服务主机确认为 api.deepseek.com。官方错误码文档将 402 定义为余额不足；一次仅向官方 `/user/balance` 发出的只读查询返回 HTTP 200、is_available=false。未发送论文或模型请求；具体余额仅保留在本地私有诊断，不提交仓库。真实内容验证尚未完成，不能把此次服务拒绝记为科学内容失败或通过。证据为 `deep-research-evidence/consistent-premises-321-checkpoint-provider-stop-20261028.json`。参考：[DeepSeek 官方错误码](https://api-docs.deepseek.com/quick_start/error_codes/)。

离线集成测试发现：应用已有计费提示，但语义核查包装异常后 errorCode 变为 invalid_verification_response，GET 的通用提示覆盖了计费原因。现将最后一条明确失败的模型调用为 provider_error/402 的运行分类为 provider_payment_rejected，保留已有安全计费提示。未知调用仍优先暂停；较早的 402 不能覆盖更新的成功、其他失败或非模型错误。不修改模型请求、预算、科学通过门槛或旧记录。

集成测试通过真实 Facade／LangGraph／账本路径注入一次 402：仅发送一次失败请求，状态 failed，保留生成草稿和证据，无发布；重启恢复和反复 GET 不增加调用，不泄露原始私有诊断。18 项初步相关检查通过，最终关联回归另行记录。

固定源码的 9 文件、84 项关联回归通过，pytest 56.22 秒、外部 60.312 秒，源码与测试哈希前后一致，无模型调用。覆盖已知支付拒绝、未知优先、较早错误不误报、运行工厂、外部失败、增量研究与检查点保全。证据为 `deep-research-evidence/provider-payment-recovery-regression-20261028.json`。

源码 `1bc48c4f` 已按空闲快照流程重启原 Python 容器一次加载，模型提示仍为 `.321`，没有改变模型请求协议。RAG/GROBID 健康，前端 HTTP 200；7,465 条账本、全部旧研究 payload、五组任务及完整索引/嵌入哈希精确保持，0 活跃、13 暂停保持，无新增模型或余额查询。证据为 `deep-research-evidence/runtime-load-provider-payment-20261028.json`。完整开发、内容与独立验收仍未完成；恢复真实验证需要模型账户恢复可用，已有验证授权保持。
