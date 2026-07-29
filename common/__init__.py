"""DualGuard 公共工具库。

包含跨版本共享的基础能力：
- 路径管理（paths）
- 配置加载（config）
- AES 加密 + HMAC 防篡改的违规记录存储（audit_storage）
- 审核文件哈希校验与自动恢复（audit_hash）
- 统一风控引擎：违规计数 / 72 小时锁定 / 弹窗（risk_engine）
- 前置审核 AI 可插拔接口（pre_audit）

注意：本包不依赖任何业务规则，业务版本（sec / student）在 main 中注入规则，
保证 "公共工具库" 与 "业务" 完全解耦。
"""
