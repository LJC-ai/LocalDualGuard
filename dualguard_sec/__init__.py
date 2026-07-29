"""DualGuard-Sec 安全业务版。

风控目标（硬性规则 2 - 安全版）：
- 拦截漏洞攻击脚本
- 拦截 Winlink 利用代码
- 拦截公共网络渗透实操内容
- 仅输出理论思路

本包不直接调用任何主模型 API，而是定义规则与复核器，
由 main.py 把它们注入 common.risk_engine.RiskEngine，
实现业务规则与公共引擎的解耦。
"""
