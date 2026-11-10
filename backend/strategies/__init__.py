"""官方回应策略代码包。

回应方案的内容（公告正文、声明状态、证据维度）维护在
``configs/strategies/official_response_options.json``；本包负责方案的结构
定义、注册表与校验。``base`` 放稳定契约，``registry`` 放加载与校验，
``strategy_a`` ~ ``strategy_c`` 保留给后续以代码实现的策略插件。
"""

__all__ = ["base", "registry"]
