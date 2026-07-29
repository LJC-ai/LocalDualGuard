# DualGuard 架构总览

DualGuard 是一套**本地端合规 / 学习诚信护栏**，分两个业务版本共享同一公共库：

| 版本 | edition | 定位 | 详细文档 |
|------|---------|------|----------|
| DualGuard-Sec | `sec` | 网络安全实训 / CTF / 授权渗透演练的合规护栏 | [DualGuard-Sec/README.md](DualGuard-Sec/README.md) |
| DualGuard-Student | `student` | K12 / 高校编程与图形化编程课堂的学习诚信护栏 | [DualGuard-Student/README.md](DualGuard-Student/README.md) |

## 设计原则

**公共库与业务完全解耦**：`common/` 不含任何业务规则，两套版本在各自 `main` 入口注入规则、构造 `AppPaths(edition)` 并加载对应 `config.yaml`。数据目录按 edition 隔离，互不污染违规计数。

## 目录结构

```
LocalDualGuard/
├── ARCHITECTURE.md                # 本文件
├── common/                        # 公共库（两版本共享）
│   ├── paths.py                   # 平台相关路径 + edition 隔离
│   ├── config.py                  # yaml 配置加载
│   ├── audit_storage.py           # AES-256 + HMAC 违规记录存储
│   ├── audit_hash.py              # 审核策略 SHA256 校验 + 自动恢复
│   ├── risk_engine.py             # 违规计数 / 72h 冻结 / 弹窗
│   └── pre_audit.py               # 可插拔前置审核 AI 接口
├── DualGuard-Sec/
│   ├── README.md
│   ├── config.yaml                # sec 配置 + 弹窗文案
│   ├── docs/packaging.md          # exe / deb 打包部署教程
│   ├── dualguard_sec/             # sec 业务入口与规则
│   └── assets/
└── DualGuard-Student/
    ├── README.md
    ├── config.yaml                # student 配置 + 弹窗文案
    ├── docs/packaging.md
    ├── dualguard_student/         # student 业务入口与规则
    └── assets/
```

## 数据目录约定（见 `common/paths.py`）

| 平台 | 路径 |
|------|------|
| Windows | `%PROGRAMDATA%\DualGuard\<edition>\` |
| Linux | `/var/lib/dualguard/<edition>/` |

每个 edition 目录下：

```
<edition>/
├── violations.enc        # AES 加密的违规记录（HMAC 防篡改）
├── audit_policy.json     # 审核策略（业务下发）
├── audit_policy.sha256   # 策略预期哈希
├── kek.bin               # 主密钥（KEK）
├── monotonic.state       # 单调计数器（防时间回拨）
├── lock.state            # 冻结状态
├── backup/               # 策略备份（篡改时自动恢复）
│   └── audit_policy.json.bak
└── logs/
```

可用环境变量 `DUALGUARD_DATA_ROOT` 覆盖根目录，便于测试与打包。

## 风控链路

```
操作 → pre_audit(可插拔规则) → 命中违规?
        ├─ 否: 放行
        └─ 是: risk_engine 计数(+monotonic 防回拨)
                ├─ 未达阈值: 弹 single_violation 警告
                └─ 达阈值: 写 lock.state → 弹 freeze → 72h 冻结
启动时: audit_hash 校验 audit_policy.json 的 SHA256
        ├─ 一致: 正常运行
        └─ 不一致: 从 backup/ 恢复 → 弹 tamper 警告
```

## 打包部署

- Windows：PyInstaller → Inno Setup 生成 exe 安装包；支持静默安装与平板批量预装。
- Linux：PyInstaller → dpkg-deb 生成 deb；注册 systemd 服务，支持开机自启。

完整教程见各版本 `docs/packaging.md`。

## 合规分层

- **安全版**：强调授权前置、禁止公共网络未授权渗透、禁止生成恶意攻击代码。
- **学生版**：强调学习思路引导、禁止抄作业 / 照搬完整积木方案、未成年人保护与温和文案。

各版本合规声明见其 README。
