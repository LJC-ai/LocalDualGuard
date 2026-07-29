"""DualGuard-Student 学生业务版。

风控目标（硬性规则 2 - 学生版）：
- 拦截完整作业答案
- 拦截全套 Scratch 图形化搭建流程
- 仅提供知识点、局部逻辑讲解

与 DualGuard-Sec 共用同一套 common 引擎与风控机制，
但规则集完全独立，互不影响违规计数（数据目录按 edition 隔离）。
"""
