# 🎬 剪映 / CapCut 版本收集器 (CapCut Version Collector)

> **中文说明** | [**English**](./README_EN.md)

![GitHub Release](https://img.shields.io/github/v/release/canc3s/capcut-versions?style=flat-square&color=blue)
![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/canc3s/capcut-versions/destversion.yml?style=flat-square&label=构建状态)
![License](https://img.shields.io/github/license/canc3s/capcut-versions?style=flat-square)

**剪映（国内版）/ CapCut（国际版）多平台离线完整安装包自动归档工具。**

本项目自动监控官方与官方镜像通道，收集新版本并归档到 GitHub Releases，同时回填历史版本。

---

## ✨ 功能特性

- **双产品线**:
    - 🇨🇳 **剪映**（国内版）
    - 🌍 **CapCut**（国际版）
- **多平台支持**:
    - 🖥️ **Windows x64 / ARM64**
    - 🍎 **macOS**
    - 🤖 **Android**
- **🔒 完整性校验**: 优先使用官方清单提供的 SHA256，归档前再次实测校验。
- **📝 版本目录**: [versions.json](./versions.json) 记录所有已知版本、官方直链、大小与哈希。
- **📚 历史回填**: 内置 200+ 历史版本，可按批次补传安装包，支持断点续传。
- **⚙️ 自动化**: 基于 GitHub Actions 的每日增量监控与发布。

---

## 📡 数据来源

| 通道 | 覆盖范围 |
| :--- | :--- |
| `winget-pkgs` 官方清单 | 剪映 Win x64 120 个历史版本、CapCut Win x64 87 个历史版本（含官方直链与 SHA256） |
| Microsoft Store 包接口 | 两版 Win x64 / ARM64 当前版本 |
| Homebrew cask + 官方 settings 接口 | CapCut macOS 稳定版与 Beta |
| ugapk 开放目录 | 剪映 Android 历史构建 |
| 官方 CDN | CapCut Android、官方完整包直链 |
| 内置种子数据 | 清单未覆盖的历史包（剪映 macOS / ARM64、CapCut 中间构建） |

目录只收录完整安装包；早期版本的 `_0.exe`、`_split_*.exe` 与新版 `creatortool` 一样是完整包，2.8~3.8MB 的在线安装壳不收录。

---

## 📅 发布历史

> **[查看完整发布日志](./RELEASE_LOG.md)**

所有收集到的版本均记录在 **[RELEASE_LOG.md](./RELEASE_LOG.md)**，按产品与平台分类。

---

## 🛠️ 使用说明

### 手动运行

```bash
# 增量采集（日常）
./scripts/monitor.sh collect

# 全量重建历史目录（首次 / 需要补历史时）
./scripts/monitor.sh collect --deep

# 为目录中尚未发布的版本创建 Release
./scripts/monitor.sh publish

# 创建 Release 并上传安装包
./scripts/monitor.sh publish --with-asset

# 只发布本次新发现的版本
./scripts/monitor.sh publish --new-only --with-asset

# 校验直链并补全文件大小
./scripts/monitor.sh verify

# 全量复核所有直链（含已归档版本）
./scripts/monitor.sh verify --all

# 从 GitHub Releases 同步发布 / 归档状态
./scripts/monitor.sh sync

# 查看收录情况
./scripts/monitor.sh status

# 生成 RELEASE_LOG.md
./scripts/monitor.sh log
```

### 历史回填

```bash
# 查看待回填列表
./scripts/monitor.sh plan --product all --platform all

# 回填指定版本（id 见 versions.json）
./scripts/monitor.sh backfill --ids jianying-win-x64-11.7.0.14652,capcut-mac-9.5.0.4590
```

GitHub Actions 中在 `destversion.yml` 选择 `action=backfill`，按产品、平台和批次自动并发回填。

### 首次归档（新仓库）

1. Actions → **CapCut Version Collector** → Run workflow → `action=baseline`，生成完整历史目录。
2. 再次 Run workflow → `action=backfill`，分批创建 Release 并上传安装包。中断后重复运行会跳过已有附件，继续回填；结束后自动同步发布状态并更新日志。
3. 之后每天 UTC 07:00 自动增量采集并发布新版本。

---

## 📂 项目结构

```
.
├── RELEASE_LOG.md              # 📜 发布历史（自动生成）
├── README.md                   # 🇨🇳 中文说明
├── README_EN.md                # 🇺🇸 英文说明
├── versions.json               # 📦 版本目录（唯一事实来源）
├── scripts/
│   ├── monitor.sh              # 🧠 入口
│   └── capcut_versions.py      # 🔧 采集 / 校验 / 发布 / 回填
└── .github/workflows/
    └── destversion.yml         # 🤖 每日监控 + 历史回填
```

---

## 📄 许可证

本项目基于 MIT License 开源。
