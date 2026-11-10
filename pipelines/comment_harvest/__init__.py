# -*- coding: utf-8 -*-
"""事件评论采集 Agent（B 站）。

本包只做研究/命令行侧的采集与分析；服务端运行时走
``backend/app/comments/web_harvest.py``，两者共用 ``bili`` 与 ``score``。

为避免 ``import pipelines.comment_harvest`` 时连带加载 CLI，这里不做任何导入。
"""

__all__: list[str] = []
