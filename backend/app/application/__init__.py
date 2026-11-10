"""应用层：实验编排、会话控制与报告用例。

本层负责把领域规则、仿真引擎和基础设施组合成可执行的用例；HTTP 传输
和 CLI 解析分别位于 ``app.api``、``app.main`` 与 ``backend/scripts``。
"""

__all__ = [
    "announcement_drafts",
    "batch_manager",
    "experiment_audit",
    "experiment_runner",
    "input_compat",
    "round_results",
    "runtime_config",
    "scenario_state",
    "session_facade",
    "session_service",
    "state_manager",
    "step_executor",
]
