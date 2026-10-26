# 元信息26：基线前奏与适应阶段的角色边界

## 代码核对

预算契约已有独立的budget.baseline：train模式保存unit/maxBudget/stoppingRule，existing模式保存资产选择规则；budget.recovery保存各组适应预算。工作流已有baselineMode、baselineInitialization和独立的适应phases。渲染先说明基线拟合，再呈现适应阶段；最终绑定检查两类角色的模式一致性，并按适应phases计算recovery预算。

E1-v79却再次把15000步基线训练放入setup步骤。修正仅改标签或清空预算都可能掩盖重复训练或丢失必要训练；必须在所属角色中保留真实选择。

## 实现

只对新契约26的plan_workflow_meta和repair_workflow_meta使用专用私有系统消息。明确基线前奏位于steps之外，由budget.baseline与后续baselineInitialization分别保存预算/选择及拟合前状态；保留的baseline句柄代表共同已拟合结果。适应步骤从它开始，真实适应拟合使用fit与有限预算，不重复训练同一基线，也不能通过清空预算过检查。未知条件仍须保留。

不改变模型输出格式、解码、初始化单元、公开回答、科学审查或任何预算/来源门槛。新系统消息814字节，加封装预留128共942，在原1024预留内。输入材料和用户提示完整不变，当前E1-v79的完整修正输入仍为31179字节。

## 检查点

定向24项通过（6.47秒）：角色隔离、旧版本逐字保持、完整组装/恢复、实际HTTP携带同一系统消息、预算预留、未知请求不重发，以及错误setup预算不被自动改类或置零。E1-v58至v79共22个旧失败只读恢复，0调用/0写入。尚未启用默认或新增模型请求；这不证明模型会正确分配基线与适应训练，更不代表完整科学交付通过。

关联检查扩大至structured_output/prospective_transport/scientific_outline，876项通过（136.06秒，外部140.69秒）；研究/LLM源码、依赖声明及测试哈希前后一致。计数范围比前一轮更广，不表示本轮新增159项功能。证据见`deep-research-evidence/workflow-metadata26-20261026.json`。
