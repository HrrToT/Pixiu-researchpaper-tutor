# 有界事实草稿的直接生成（.391）

G1N-v2 已读取正文和表格材料，但初始综合finishReason=length，output_tokens=8192，rawContent仅2516字符/2850字节，JSON在第三条主张处结束。六次调用均结算，未进入事实审核或发布。原始失败记录保持；没有重复JSON，也没有保存推理Token细分，不能回填一个推理用量数值。

## 配置与边界

已核对[DeepSeek思考模式文档](https://api-docs.deepseek.com/guides/thinking_mode/)和[Chat Completions接口](https://api-docs.deepseek.com/api/create-chat-completion/)。接口支持显式thinking.type=disabled与reasoning_effort=none；finish_reason=length仍须作为截断处理。接口提供reasoning_tokens细分，但本项目该历史调用只保留总体输入/输出/总Token，官方文档不能补造历史实际用量。

新运行factualReasoning10，仅在原有资格范围内将初始synthesize改为直接写出证据草稿：单篇事实至多300字，明确多来源比较至多700字，仍须有人类显式篇幅要求。上限保持8192，不更换问题、提示、证据、最大调用/Token/时间额度；实际省下的用量不能先假定为已发生。

研究规划、取证、科学/范围/完整性审核和已有修订配置保持。新内部标记必须是真布尔且与短事实资格配套，不能混入实验/审核配置；标记发送前移除，实际模式参数在预约Token和输入指纹计算前确定。相同输入的新旧草稿模式有不同指纹，已结算请求仍复用一次，未知请求不换版本重发。旧9及以下不改变，持久化策略不可更新切换。

## 验证

真实保存G1N-v2的实际综合节点回放：输入24000字节，提示SHA和前提分配逐项相同；max_tokens=8192、temperature与JSON格式相同。唯一模式差异为enabled/low→disabled/none。0网络/模型调用，旧payload哈希保持。这只证明配置和输入传递，不能当作模型内容通过。

单元/集成覆盖实际TrackedLLMInvoker的预约、完整发送参数、预算相等与不同指纹、结算缓存；正式综合节点的截断仍一次调用后拒绝，不拼接、不发布、不自动fallback。其他输出类别、审核与修订角色、旧策略、字数资格及固定编辑范围保持。新真实复测须保持原G1N开发回归定义，不能升级为独立留出。
