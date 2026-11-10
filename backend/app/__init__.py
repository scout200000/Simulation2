"""Future 后端应用包。

分层结构：

* ``api``：HTTP 接口与请求/响应结构；
* ``application``：实验、会话与报告的用例编排；
* ``domain``：事件、策略、评论语义等稳定领域规则；
* ``infrastructure``：LLM、JSON 存储等外部设施；
* ``agents`` / ``comments`` / ``simulation`` / ``evaluation``：仿真引擎能力；
* ``main``：配置、异常与应用启动入口；
* ``shared``：跨层通用小工具。
"""

__version__ = "0.1.0"
