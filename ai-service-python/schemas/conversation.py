"""Validated input to the task-scoped conversation capability adapter."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Capability = Literal['chat', 'background', 'critique', 'compare']


class ConversationCapabilityRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    taskId: str = Field(min_length=1, max_length=255)
    message: str = Field(min_length=1, max_length=20000)
    capability: Literal['chat', 'background', 'critique', 'compare', 'compose'] = 'chat'
    allowedPaperIds: list[str] = Field(max_length=128)
    primaryPaperId: str | None = None
    strictScope: bool = False
    history: list[dict[str, str]] = Field(default_factory=list, max_length=100)
    steps: list[Capability] = Field(default_factory=list, max_length=3)

    @model_validator(mode='after')
    def validate_scope_and_plan(self):
        if not self.message.strip():
            raise ValueError('问题不能为空')
        if len(set(self.allowedPaperIds)) != len(self.allowedPaperIds) or any(not value.strip() for value in self.allowedPaperIds):
            raise ValueError('材料标识无效或重复')
        if self.primaryPaperId is not None and self.primaryPaperId not in self.allowedPaperIds:
            raise ValueError('主论文不属于指定材料')
        if self.capability == 'compose':
            if len(self.steps) < 2 or len(set(self.steps)) != len(self.steps):
                raise ValueError('组合任务须指定二至三个不同能力')
        elif self.steps:
            raise ValueError('单能力请求不能附加执行步骤')
        plan = self.steps if self.capability == 'compose' else [self.capability]
        if any(step != 'chat' for step in plan) and not self.allowedPaperIds:
            raise ValueError('请先选择任务材料')
        if 'compare' in plan and len(self.allowedPaperIds) < 2:
            raise ValueError('比较至少需要两篇论文')
        return self
