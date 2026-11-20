# PaperQA2 证据组件复用评估

当前结论：已完成固定源码检查，尚未安装、接入或完成质量对照。现有研究引擎保持运行，不能把本记录算作 PaperQA2 集成完成。

## 固定来源与候选接口

官方仓库：[Future-House/paper-qa](https://github.com/Future-House/paper-qa)，检查 commit `57e89f7223b0960d5ee5ea048c69e3c47e088572`。许可证为 Apache-2.0；本次只下载源码用于评估，没有复制第三方实现到产品目录。源码及 SHA-256 清单保存在 `tmp/paperqa-evaluation-20261013/snapshot.json`。

- [`Docs.aadd_texts`](https://github.com/Future-House/paper-qa/blob/57e89f7223b0960d5ee5ea048c69e3c47e088572/src/paperqa/docs.py#L340)：可输入现有解析文本及论文身份，避免另建一套文档导入。
- [`Docs.aget_evidence`](https://github.com/Future-House/paper-qa/blob/57e89f7223b0960d5ee5ea048c69e3c47e088572/src/paperqa/docs.py#L492)：允许注入摘要模型及嵌入模型，候选复用点是证据摘要和相关性筛选；不将模型相关性分数当作事实核验。
- [`Docs.aquery`](https://github.com/Future-House/paper-qa/blob/57e89f7223b0960d5ee5ea048c69e3c47e088572/src/paperqa/docs.py#L588)：允许注入回答模型，但报告仍需经过本项目的引用、条件、权限和完整性检查。

## 必须先解决的适配问题

1. 摘要按片段并发生成，默认并发为 4。须使用本项目的原子调用预留和实际 usage 结算，控制并发与总预算，不能仅靠事后 callback 计费。
2. `aget_evidence` 在开启检索时会调用嵌入服务；材料加入阶段也可能产生嵌入。第一轮组件对照应复用已有候选片段、显式关闭内部检索并注入模型，验证没有额外网络出口后才做完整检索对照。
3. [`map_fxn_summary`](https://github.com/Future-House/paper-qa/blob/57e89f7223b0960d5ee5ea048c69e3c47e088572/src/paperqa/core.py#L383) 对可重试的上下文错误会再调用一次 `_map_fxn_summary`，其中包括 JSON 解析失败。另有可选的文本替代媒体请求。不能直接假定默认路径符合“每例一次、不自动重试”。须对所有内部调用限制、记账，并验证未知结果不会重发。
4. 注入 `LLMModel` 的完整协议以及底层依赖的重试、模型路由行为仍需检查；不能仅凭 `call_single` 调用点断言只实现一个方法就可运行。
5. 摘要必须保留对应原文与论文、版本、页码身份；候选摘要不自动成为精确原文，不覆盖现有证据。

## Qoder 审查与主代理复核

Qoder 使用 `bailian/qwen3.8-max-tp`，工具关闭，仅接收上述公开源码的部分片段与开发接口说明，没有发送论文、运行数据或凭据；进程退出码为 0。输出保存于 `tmp/qoder-paperqa-review-20261013/output.txt`。

采纳其模型注入、并发和嵌入入口分析。拒绝“只有可选媒体降级会重试，已符合不自动重试策略”的结论：所给片段未覆盖完整包装函数，主代理检查固定版本 `core.py` 后发现自动 JSON 重试。审查结果不能替代安装、离线网络拦截测试或真实回答对照。

## 下一步验证边界

在隔离环境中安装固定版本，使用合成文本和假的模型先验证依赖、协议、逐调用预算、失败与重试、证据身份。随后才对同一组已授权公开材料做单次、可比预算的组件对照，记录正确性、引用准确性、完整性和成本。有效组件通过统一接口接入；在对照完成之前不宣称比当前实现更好。
