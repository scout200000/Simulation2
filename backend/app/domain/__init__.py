"""仿真领域层：稳定数据契约、事件语义与策略证据规则。

本层只包含与运行方式无关的业务规则；文件读写、LLM 请求等副作用
位于 ``app.application`` 与 ``app.infrastructure``。
"""

from app.domain.contracts import (
    AgentDecisionInput,
    AgentDecisionResult,
    SimulationContext,
)

__all__ = [
    "AgentDecisionInput",
    "AgentDecisionResult",
    "SimulationContext",
]
