# 🎬 CapCut Version Collector

> [**中文说明**](./README.md) | **English**

![GitHub Release](https://img.shields.io/github/v/release/canc3s/capcut-versions?style=flat-square&color=blue)
![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/canc3s/capcut-versions/destversion.yml?style=flat-square&label=build)
![License](https://img.shields.io/github/license/canc3s/capcut-versions?style=flat-square)

**Automated archive of Jianying (China) and CapCut (International) offline installers.**

The project watches official and official-mirror channels, archives every new version as a GitHub Release, and backfills the full version history.

---

## ✨ Features

- **Two product lines**: 剪映 (Jianying, China) and CapCut (International)
- **Platforms**: Windows x64 / ARM64, macOS, Android
- **Integrity**: official SHA256 when available, verified again before upload
- **Catalog**: [versions.json](./versions.json) stores every known version with its official URL, size and hash
- **History backfill**: 200+ historical versions, batched and resumable
- **Automation**: daily incremental collection via GitHub Actions

---

## 📡 Sources

| Channel | Coverage |
| :--- | :--- |
| `winget-pkgs` manifests | Jianying Win x64 (120 versions), CapCut Win x64 (87 versions), with official URL + SHA256 |
| Microsoft Store package API | current Windows x64 / ARM64 builds |
| Homebrew cask + official settings API | CapCut macOS stable and beta |
| ugapk open directory | Jianying Android builds |
| Official CDN | CapCut Android and verified full-package URLs |
| Built-in seeds | gaps not covered by the channels above |

---

## 📅 Release history

> **[Full release log](./RELEASE_LOG.md)**

---

## 🛠️ Usage

```bash
./scripts/monitor.sh collect                 # incremental
./scripts/monitor.sh collect --deep          # rebuild full history
./scripts/monitor.sh publish --with-asset    # create releases and upload installers
./scripts/monitor.sh verify                  # probe URLs and fill sizes
./scripts/monitor.sh verify --all            # re-probe every URL
./scripts/monitor.sh sync                    # sync release/archive state from GitHub
./scripts/monitor.sh status                  # catalog summary
./scripts/monitor.sh plan                    # list pending backfill
./scripts/monitor.sh backfill --ids <id,...> # upload historical assets
```

**First-time archive (new repository):**

1. Actions → **CapCut Version Collector** → Run workflow → `action=baseline` to build the full history catalog.
2. Run it again with `action=backfill` to create releases and upload installers in batches. Re-running resumes and skips assets that already exist; the workflow syncs release state and regenerates the log when the run finishes.
3. Afterwards the workflow collects and publishes new versions daily at 07:00 UTC.

---

## 📂 Structure

```
.
├── RELEASE_LOG.md
├── README.md
├── README_EN.md
├── versions.json
├── scripts/
│   ├── monitor.sh
│   └── capcut_versions.py
└── .github/workflows/
    └── destversion.yml
```

---

## 🔗 Related Projects

- [wechat-versions](https://github.com/canc3s/wechat-versions) — archive of WeChat installers for Windows, macOS and Android

---

## 📄 License

MIT
