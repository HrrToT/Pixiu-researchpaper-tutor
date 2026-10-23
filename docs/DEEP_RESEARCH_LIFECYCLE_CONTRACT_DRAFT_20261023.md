# Workflow5 生命周期契约草案

状态：设计待实现，不改变已冻结的 Workflow1—4，不授予任何科学验收通过。

## 已确认的问题与范围

Workflow4 的组件字段没有生命周期或创建时点，展示层固定为“每次重复先创建，再配对”。E1 要求第1阶段之后逐帧创建附加高斯，并在评估、记录后丢弃。审计见 `deep-research-evidence/workflow-initialization-order-audit-20261023.json`。

分段引擎仅解决生成粒度、恢复和预算，不能弥补这一类型表示缺口。所有初值、状态、数据、引用、完整预算及独立科学检查继续保留。

## 新版本的执行含义

1. 每个重复先锁定数据划分、初始化并按原基线预算拟合共同基线，或核查已有资产。基线步骤保持原预算契约，不在下面的恢复阶段重复计费。
2. 组件初始化定义是完整的创建配方；实际实例何时创建由生命周期确定。不能在渲染时一律提前创建。
3. `phases` 列表给出执行顺序；每阶段另以 `after` 声明依赖。连续的 `per_frame` 阶段组成一个循环块，在每次重复中对 `frameIterations` 个帧依次执行。其余阶段为 `per_repeat`，可位于循环前或后。
4. 每阶段根据组件生命周期，在依赖阶段完成后、首次使用前创建实例；在指定阶段完成且全部消费者结束后销毁。

## 类型草案

Workflow5 保留 Workflow4 的字段，增加 `frameIterations` 和 `phases`。组件增加必填 `lifecycle`：

```text
lifecycle = {scope:per_repeat|per_frame, createAfter:[phaseId], disposeAfter:phaseId|null}
phase = {phaseId,scope:per_repeat|per_frame,kind:fit|setup|evaluate|record,
         groups:[actual group ID],sharing:shared|per_group,after:[earlier phaseId],
         reads:[input],outputs:[unique outputId],action:operation,budget:phaseBudget|null}
input = {state:baseline|training_data|earlier componentId,selector}
     OR {phaseId,outputId,selector}
phaseBudget = {unit:optimizer_steps|epochs|wall_seconds,perExecution:nonnegative finite number}
```

初始化的 `inputs` 使用同一输入联合类型。维度仍为正整数或显式 `inputIndex/axis`，每个必需状态仍提供实际初值或操作规则，不允许符号维度、空规则或用训练过程冒充初值。

`shared` 表示同一次阶段结果供列出的组共用；`per_group` 表示各组分别执行。阶段结果只能被所属组或其子集读取，不能把只在处理组产生的结果泄漏给控制组。

`per_frame` 组件必须在同帧的明确阶段后销毁，不可携带到下一帧；`per_repeat` 组件只创建一次，可在循环中更新，或在重复结束时销毁。若要对两组固定同一个第1阶段结果，应显式表达共享阶段与后续分支。

## 硬检查

- 阶段、组件和输出标识唯一；所有引用真实存在。`after` 只能指向列表中的先前阶段。
- 创建点、输入生产点、阶段读取与销毁构成有向图。拒绝依赖环、初始化前读取、未来输出以及销毁后使用。
- 初始化引用的阶段输出必须在该组件创建点之前产生；组件输入仍不能指向尚未创建的后续组件。
- 逐帧阶段必须连续；有循环时 `frameIterations` 为正整数，无循环时为零。逐帧对象不能直接成为按重复创建对象的输入。
- 每个临时组件必须在指定销毁点之前完成全部消费，包括评估、记录和其他初始化。只写“评估后丢弃”不能掩盖记录尚未完成。
- 每个拟合阶段有预算，其他阶段预算为 null。steps/epochs 使用非布尔整数；所有数值有限，禁止公式字符串。
- 原恢复预算按每次重复、整个组核对：将各拟合阶段的 `perExecution` 乘以循环次数（逐帧为 `frameIterations`，按重复为1），分别累计到该阶段所属组，必须与预算声明逐组一致，单位一致。共享阶段计入每个比较组的归属预算，不冒充多次实际执行。
- 对照/处理的预算不等时，仍须遵守原 unmatched 规则；不由新契约自动改变归因或科学结论。
- 最终核对阶段组ID、组件应用组、实际预算/分组声明及评估记录覆盖；不能用局部合法代替完整方案通过。

## 生成与兼容

计划使用独立的新执行生成版本承载 Workflow5，保留已提交的契约6/Workflow4分段原型语义。新元信息单元选择阶段、生命周期和分组；初始化单元按依赖获得完整上下文。服务端只组装模型已经选择的值、固定契约常量和可核对的数学累计，不猜测数值或补充资产。

每个实际请求单独冻结 schema、消息、选项、来源权限及摘要。容量不足保留完整失败输入；未知请求不重发；未完成全部单元不得进入公开正文。整轮仍限18调用、100k Token、360秒。

展示、原文/解释边界、事实与拟议选择分类、数值审核、独立语义检查、成果发布与版本化均继续适用。新版本只在实现和验收完成后启用。

## 下一步验收

实现静态图检查与逐组预算累计；用按帧阶段1/新增/评估/记录/销毁夹具及故障反例验证。覆盖未来引用、生命周期环、组泄漏、少计帧数预算、记录前销毁、恢复与旧请求身份。随后接入分段生成、渲染和完整审核，再执行一次固定真实案例。夹具通过不能算科学方案通过。
