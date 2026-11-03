#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
剪映(国内版) / CapCut(国际版) 多平台版本收集器
================================================================
目录(versions.json)驱动：先把所有已知版本收进目录，再按目录创建 GitHub Release。

命令
  collect     汇总各官方/官方镜像通道，合并进 versions.json；--deep 抓全量历史
  verify      Range 探测直链，补全大小并标记失效条目
  publish     为目录中尚未发布的版本创建 Release；--with-asset 同时上传安装包
  backfill    按 id 批量上传历史安装包（可断点续传）
  plan        输出 backfill 的 GitHub Actions matrix
  log         由 versions.json 生成 RELEASE_LOG.md
  sync        从 GitHub Releases 回填发布/归档状态
  status      打印各产品/平台的收录情况

退出码
  0  成功；非 0 表示有命令失败（采集源单独失败只记录，不中断其它源）
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSIONS = ROOT / "versions.json"
CACHE = ROOT / ".cache"
NEW_IDS = CACHE / "new_ids.json"
TEMP = ROOT / "temp"
RELEASE_LOG = ROOT / "RELEASE_LOG.md"

REPO = os.environ.get("GITHUB_REPOSITORY") or "canc3s/capcut-versions"
UA = "capcut-versions/1.0"
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")

PRODUCTS = {"jianying": "剪映", "capcut": "CapCut"}
PLATFORMS = {
    "win-x64": "Windows x64",
    "win-arm64": "Windows ARM64",
    "mac": "macOS",
    "android": "Android",
}
P_ORDER = {"jianying": 0, "capcut": 1}
F_ORDER = {"win-x64": 0, "win-arm64": 1, "mac": 2, "android": 3}
SOURCE_RANK = {
    "winget": 90, "official-cdn": 80, "msstore": 70, "ugapk": 60,
    "brew": 50, "capcut-settings": 45, "seed": 30,
}

CDN = {
    ("jianying", "win-x64"): [
        "https://lf3-package.vlabstatic.com/obj/faceu-packages/Jianying_{v}_jianyingpro_0_creatortool.exe",
        "https://lf6-package.vlabstatic.com/obj/faceu-packages/Jianying_{v}_jianyingpro_0_creatortool.exe",
    ],
    ("jianying", "win-arm64"): [
        "https://lf3-package.vlabstatic.com/obj/faceu-packages/Jianying_{v}_jianyingpro_msstore_arm64ec_arm64ec.exe",
    ],
    ("jianying", "mac"): [
        "https://lf3-package.vlabstatic.com/obj/faceu-packages/Jianying_{v}_jianyingpro_0_creatortool.dmg",
    ],
    ("capcut", "win-x64"): [
        "https://sf16-web-tos-buz.capcutstatic.com/obj/capcut-web-buz-sg/packages/CapCut_{v}_capcutpc_0_creatortool.exe",
        "https://sf16-web-tos-buz.capcutcdn-us.com/obj/capcut-web-buz-tx/packages/CapCut_{v}_capcutpc_0_creatortool.exe",
    ],
    ("capcut", "win-arm64"): [
        "https://sf16-web-tos-buz.capcutstatic.com/obj/capcut-web-buz-sg/packages/CapCut_{v}_capcutpc_msstore_arm64ec_arm64ec.exe",
    ],
    ("capcut", "mac"): [
        "https://sf16-web-tos-buz.capcutstatic.com/obj/capcut-web-buz-sg/packages/CapCut_{v}_capcutpc_0_creatortool.dmg",
    ],
}

WINGET_TREE = "https://github.com/microsoft/winget-pkgs/tree/master/manifests/b/ByteDance/{pkg}"
WINGET_RAW = ("https://raw.githubusercontent.com/microsoft/winget-pkgs/master/"
              "manifests/b/ByteDance/{pkg}/{ver}/ByteDance.{pkg}.installer.yaml")
STORE_MANIFEST = "https://storeedgefd.dsx.mp.microsoft.com/v9.0/packageManifests/{pid}?market={mkt}&locale={loc}"
CAPCUT_SETTINGS = ("https://editor-api-sg.capcutapi.com/service/settings/v3/?aid=359289"
                   "&device_platform=mac&channel=capcutpc_0&version_code=1&os_version=26.4"
                   "&region=GB&traffic_type=release")
CAPCUT_APK = ("https://sf16-web-tos-buz.capcutstatic.com/obj/eden-sg/nupkuhs_yvojuh_jj/"
              "ljhwZthlaukjlkulzlp/capcut_apk/cc_website_download.apk")
UGAPK_INDEX = "https://lf9-apk.ugapk.cn/package/apk/videocut/"
UGAPK_BASE = "https://lf9-apk.ugapk.cn/package/apk/"

# 清单/接口无法覆盖的历史版本（来源：官方 CDN 与官方 Store 实测）
SEED_ENTRIES = [
    {"product": "jianying", "platform": "mac", "version": "5.5.0.9965",
     "url": "https://lf3-package.vlabstatic.com/obj/faceu-packages/Jianying_5_5_0_9965_jianyingpro_0_creatortool.dmg",
     "size": 877711892, "source": "official-cdn"},
    {"product": "jianying", "platform": "mac", "version": "4.2.0-beta-nvidia",
     "url": "https://lf3-package.vlabstatic.com/obj/faceu-packages/Jianying_4_2_0_jianyingpro_beta_nvidia_creatortool.dmg",
     "size": 946553872, "source": "official-cdn"},
    {"product": "jianying", "platform": "win-arm64", "version": "11.6.0.14555",
     "url": "https://lf3-package.vlabstatic.com/obj/faceu-packages/Jianying_11_6_0_14555_jianyingpro_msstore_arm64ec_arm64ec.exe",
     "size": 905606864, "source": "official-cdn"},
    {"product": "capcut", "platform": "win-x64", "version": "9.5.0.4051",
     "url": "https://sf16-web-tos-buz.capcutstatic.com/obj/capcut-web-buz-sg/packages/CapCut_9_5_0_4051_capcutpc_0_creatortool.exe",
     "size": 600600744, "release_date": "2026-09-14", "source": "official-cdn"},
    {"product": "capcut", "platform": "win-x64", "version": "9.6.0.4097",
     "url": "https://sf16-web-tos-buz.capcutstatic.com/obj/capcut-web-buz-sg/packages/CapCut_9_6_0_4097_capcutpc_0_creatortool.exe",
     "size": 611677808, "release_date": "2026-10-08", "source": "official-cdn"},
    {"product": "capcut", "platform": "win-arm64", "version": "9.7.0.4156",
     "url": "https://sf16-web-tos-buz.capcutstatic.com/obj/capcut-web-buz-sg/packages/CapCut_9_7_0_4156_capcutpc_msstore_arm64ec_arm64ec.exe",
     "size": 631087704, "source": "official-cdn"},
]


# ============================================================ 基础工具
def log(msg):
    print(msg, flush=True)


def warn(msg):
    print("⚠ " + msg, file=sys.stderr, flush=True)


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def http_get(url, headers=None, timeout=30, retries=3):
    """返回 (status, headers, body)。4xx 不抛异常。"""
    h = {"User-Agent": UA, "Accept": "*/*"}
    if headers:
        h.update(headers)
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token and "api.github.com" in url:
        h.setdefault("Authorization", "Bearer " + token)
    last = (0, {}, b"")
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            body = e.read() if e.fp else b""
            last = (e.code, dict(e.headers or {}), body)
            if e.code in (404, 410):
                return last
            if attempt < retries - 1:
                time.sleep(0.8 * (attempt + 1))
        except Exception as e:
            last = (0, {}, str(e).encode())
            if attempt < retries - 1:
                time.sleep(0.8 * (attempt + 1))
    return last


def http_text(url, **kw):
    st, hd, body = http_get(url, **kw)
    return st, hd, body.decode("utf-8", "ignore")


def probe(url, timeout=15):
    """Range 探测真实字节数，不整包下载。返回 (status, size)。"""
    cmd = ["curl", "-sS", "-L", "--max-time", str(timeout), "-A", UA,
           "-r", "0-0", "-D", "-", "-o", "/dev/null", "--max-filesize", "1048576", url]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout + 15)
    except Exception:
        return 0, None
    text = (p.stdout or b"").decode("latin1", "ignore")
    blocks = [b for b in re.split(r"(?=^HTTP/)", text, flags=re.M) if b.strip().startswith("HTTP/")]
    block = blocks[-1] if blocks else ""
    m = re.search(r"^HTTP/\S+\s+(\d{3})", block, re.M)
    status = int(m.group(1)) if m else 0
    cr = re.search(r"(?im)^content-range:\s*bytes\s+\d+-\d+/(\d+)", block)
    if cr:
        return status, int(cr.group(1))
    cl = re.search(r"(?im)^content-length:\s*(\d+)", block)
    if cl and status != 206 and int(cl.group(1)) > 1024:
        return status, int(cl.group(1))
    return status, None


def download(url, dest, expected_size=None, expected_sha=None):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["curl", "-L", "--fail", "--connect-timeout", "20",
           "--retry", "5", "--retry-delay", "5",
           "--retry-all-errors", "-C", "-", "--speed-limit", "1024", "--speed-time", "60",
           "-A", UA, "-o", str(dest), url]
    p = subprocess.run(cmd, capture_output=True, timeout=7200)
    if p.returncode != 0:
        raise RuntimeError("curl %d: %s" % (p.returncode, (p.stderr or b"").decode("latin1")[:300]))
    size = dest.stat().st_size
    if expected_size and size != expected_size:
        raise RuntimeError("大小不符: %d != %d" % (size, expected_size))
    sha = sha256(dest)
    if expected_sha and sha.lower() != expected_sha.lower():
        raise RuntimeError("SHA256 不符: %s != %s" % (sha, expected_sha))
    return size, sha


def fetch_asset(e, tempdir):
    """按 主链接 → 同 SHA 镜像 → 其它镜像 的顺序下载，成功后把实际使用的
    链接写回条目。超时/404 都只是换下一个候选，不会丢包。"""
    primary = {"source": e.get("source"), "url": e.get("url"), "sha256": e.get("sha256"),
               "size": e.get("size"), "asset_name": e.get("asset_name")}
    seen, alts = set(), []
    for a in e.get("alternates") or []:
        if a.get("url") and a["url"] not in seen and a["url"] != e.get("url"):
            seen.add(a["url"])
            alts.append(dict(a))
    same_sha = lambda c: bool(c.get("sha256")) and \
        c["sha256"].lower() == (e.get("sha256") or "").lower()
    cands = [primary] + [c for c in alts if same_sha(c)] + [c for c in alts if not same_sha(c)]

    errs = []
    for c in cands:
        if not c.get("url"):
            continue
        name = c.get("asset_name") or default_asset_name(
            e.get("product"), e.get("platform"), e.get("version"), c["url"])
        dest = Path(tempdir) / name
        try:
            dest.unlink(missing_ok=True)
            size, sha = download(c["url"], dest, expected_size=c.get("size"),
                                 expected_sha=c.get("sha256"))
        except Exception as ex:
            errs.append("%s: %s" % (c["url"], str(ex)[:160]))
            continue
        if c["url"] != e.get("url"):
            alts = e.setdefault("alternates", [])
            if not any(a.get("url") == primary["url"] for a in alts):
                alts.append(primary)
            e["url"] = c["url"]
            e["source"] = c.get("source") or e.get("source")
            e["asset_name"] = name
        e["size"], e["sha256"] = size, sha
        return dest, size, sha
    raise RuntimeError("所有下载地址均失败: " + " | ".join(errs)[:600])


def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def vkey(v):
    return [int(x) for x in re.findall(r"\d+", v or "")] or [0]


def safe(v):
    return re.sub(r"[^0-9A-Za-z._-]+", "-", str(v)).strip("-")


def human_size(n):
    if not n:
        return "-"
    x = float(n)
    for u in ("B", "KiB", "MiB", "GiB"):
        if x < 1024 or u == "GiB":
            return "%d B" % n if u == "B" else "%.1f %s" % (x, u)
        x /= 1024
    return str(n)


# ============================================================ 目录
def load_versions():
    if VERSIONS.exists():
        with open(VERSIONS, encoding="utf-8") as f:
            d = json.load(f)
    else:
        d = {"schema": 1, "entries": []}
    d.setdefault("schema", 1)
    d.setdefault("entries", [])
    return d


class Catalog:
    def __init__(self, data=None):
        self.data = data or load_versions()
        self.entries = {e["id"]: e for e in self.data["entries"]}
        self.new_ids = []
        if NEW_IDS.exists():
            try:
                with open(NEW_IDS, encoding="utf-8") as f:
                    self.new_ids = json.load(f)
            except Exception:
                pass

    def get(self, eid):
        return self.entries.get(eid)

    def has_sha(self, eid):
        e = self.entries.get(eid)
        return bool(e and e.get("sha256"))

    def add(self, entry):
        eid = entry["id"]
        old = self.entries.get(eid)
        if old is None:
            entry.setdefault("first_seen", TODAY)
            entry.setdefault("released", False)
            entry.setdefault("archived", False)
            entry.setdefault("dead", False)
            entry.setdefault("alternates", [])
            self.entries[eid] = entry
            self.new_ids.append(eid)
            return
        same = (entry.get("sha256") or "").lower() == (old.get("sha256") or "").lower()
        same_url = bool(entry.get("url")) and entry["url"] == old.get("url")
        # 只有同一个文件（同 URL 或同 SHA）才能互补字段。同一版本的不同安装形态
        # （例如 Store 包与普通包）SHA 不同，混用会得到错误的 size / 哈希。
        if same or same_url or not old.get("sha256"):
            for k in ("size", "sha256", "release_date", "asset_name", "build", "note"):
                if not old.get(k) and entry.get(k):
                    old[k] = entry[k]
        old_rank = SOURCE_RANK.get(old.get("source"), 0)
        new_rank = SOURCE_RANK.get(entry.get("source"), 0)
        if new_rank > old_rank and entry.get("url") and not same and not same_url:
            self._add_alt(old, old)
            for k in ("url", "sha256", "size", "source", "release_date", "asset_name"):
                if entry.get(k):
                    old[k] = entry[k]
        elif entry.get("url") and entry["url"] != old.get("url"):
            self._add_alt(old, entry)
        old["last_seen"] = TODAY

    @staticmethod
    def _add_alt(owner, e):
        if not e.get("url"):
            return
        alts = owner.setdefault("alternates", [])
        if any(a.get("url") == e["url"] for a in alts):
            return
        alts.append({"source": e.get("source"), "url": e["url"],
                     "sha256": e.get("sha256"), "size": e.get("size")})

    def save(self):
        self.data["entries"] = sorted(self.entries.values(), key=lambda e: (
            P_ORDER.get(e.get("product"), 9), F_ORDER.get(e.get("platform"), 9),
            [-x for x in vkey(e.get("version"))], e.get("id", "")))
        self.data["updated_at"] = now_iso()
        tmp = VERSIONS.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)
            f.write("\n")
        tmp.replace(VERSIONS)
        CACHE.mkdir(exist_ok=True)
        with open(NEW_IDS, "w", encoding="utf-8") as f:
            json.dump(self.new_ids, f, indent=1)

    def missing_size(self):
        return [e for e in self.entries.values() if e.get("url") and not e.get("size") and not e.get("dead")]

    def select(self, products=None, platforms=None, new_only=False, ids=None,
               missing_assets=False, state=None):
        out = []
        wanted = set(ids or [])
        for e in self.entries.values():
            if wanted and e["id"] not in wanted:
                continue
            if not wanted and products and e.get("product") not in products:
                continue
            if not wanted and platforms and e.get("platform") not in platforms:
                continue
            if new_only and e["id"] not in self.new_ids:
                continue
            if missing_assets:
                if e.get("dead") or not e.get("url"):
                    continue
                if (state or {}).get(tag_of(e)):
                    continue
            out.append(e)
        out.sort(key=lambda e: (P_ORDER.get(e.get("product"), 9), F_ORDER.get(e.get("platform"), 9),
                                vkey(e.get("version"))))
        return out


def make_entry(product, platform, version, url, **kw):
    e = {"id": "", "product": product, "platform": platform, "version": str(version),
         "url": url, "size": kw.get("size"), "sha256": kw.get("sha256"),
         "release_date": kw.get("release_date"), "source": kw.get("source", "unknown"),
         "asset_name": kw.get("asset_name") or default_asset_name(product, platform, version, url)}
    if kw.get("build"):
        e["build"] = str(kw["build"])
    e["id"] = "%s-%s-%s" % (product, platform, safe(version))
    if kw.get("build") and safe(str(kw["build"])) not in e["id"]:
        e["id"] += "-" + safe(str(kw["build"]))
    if kw.get("id"):
        e["id"] = kw["id"]
    if kw.get("note"):
        e["note"] = kw["note"]
    return e


def default_asset_name(product, platform, version, url):
    base = os.path.basename((url or "").split("?")[0])
    if base and base != "file" and "." in base:
        return base
    ext = {"win-x64": ".exe", "win-arm64": ".exe", "mac": ".dmg", "android": ".apk"}.get(platform, ".bin")
    tag = "%s_%s_%s" % (product, platform.replace("-", "_"), safe(version))
    return tag + ext


def tag_of(e):
    if e.get("tag"):
        return e["tag"]
    tag = "v%s-%s-%s" % (safe(e.get("version")), e.get("product"), e.get("platform"))
    if e.get("build"):
        tag += "-" + safe(str(e["build"]))
    return tag


# ============================================================ 数据源
def winget_versions(pkg):
    api = "https://api.github.com/repos/microsoft/winget-pkgs/contents/manifests/b/ByteDance/%s" % pkg
    st, _, body = http_get(api)
    if st == 200:
        try:
            items = json.loads(body)
            names = {i["name"] for i in items if i.get("type") == "dir"}
            if names:
                return sorted(names, key=vkey)
        except Exception:
            pass
    st, _, txt = http_text(WINGET_TREE.format(pkg=pkg))
    pat = r'"name":"([^"]+)","path":"manifests/b/ByteDance/' + re.escape(pkg) + r'/[^"]+","contentType":"directory"'
    names = set(re.findall(pat, txt))
    if not names:
        raise RuntimeError("winget %s 版本列表获取失败 (HTTP %d)" % (pkg, st))
    return sorted(names, key=vkey)


def parse_winget_manifest(txt):
    rel = re.search(r"^ReleaseDate:\s*(\S+)", txt, re.M)
    release_date = rel.group(1) if rel else None
    out = []
    for m in re.finditer(r"- Architecture:\s*(\S+)(.*?)(?=\n- Architecture:|\nManifestType:|\Z)", txt, re.S):
        arch, block = m.group(1), m.group(2)
        u = re.search(r"InstallerUrl:\s*(\S+)", block)
        s = re.search(r"InstallerSha256:\s*(\S+)", block)
        if u:
            out.append((arch, u.group(1), s.group(1) if s else None))
    return release_date, out


def collect_winget(cat, product, pkg, deep=False):
    versions = winget_versions(pkg)
    todo = []
    for v in versions:
        if not deep and cat.has_sha("%s-win-x64-%s" % (product, safe(v))):
            continue
        todo.append(v)
    log("  winget %-12s %3d 个版本, 待抓取 %d" % (pkg, len(versions), len(todo)))

    def fetch(v):
        st, _, txt = http_text(WINGET_RAW.format(pkg=pkg, ver=v))
        if st != 200:
            return v, None
        rd, installers = parse_winget_manifest(txt)
        return v, (rd, installers)

    ok, fail = 0, 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        for v, res in ex.map(fetch, todo):
            if not res:
                fail += 1
                continue
            rd, installers = res
            for arch, url, sha in installers:
                platform = {"x64": "win-x64", "arm64": "win-arm64"}.get(arch)
                if not platform:
                    continue
                cat.add(make_entry(product, platform, v, url, sha256=sha,
                                   release_date=rd, source="winget"))
                for alt, same in winget_mirrors(product, platform, v, url):
                    cat.add(make_entry(product, platform, v, alt, sha256=(sha if same else None),
                                       release_date=rd, source="winget"))
                ok += 1
    return {"ok": ok, "fail": fail, "total": len(versions)}


def winget_mirrors(product, platform, version, url):
    """返回 [(url, same_file)]。same_file=True 表示只是换了官方桶、文件名不变，
    可以沿用官方 SHA256；False 表示同版本的不同安装形态，必须实测哈希。"""
    base = url.split("?")[0].rsplit("/", 1)[-1]
    v = version.replace(".", "_")
    out = []
    if product == "capcut" and platform == "win-x64":
        for prefix in ("https://sf16-web-tos-buz.capcutstatic.com/obj/capcut-web-buz-sg/packages/",
                       "https://sf16-web-tos-buz.capcutcdn-us.com/obj/capcut-web-buz-tx/packages/"):
            out.append((prefix + base, True))
        # 同版本的其它打包形态：官方 CDN 上常见 _0.exe / _0_creatortool.exe / split
        variants = [
            "CapCut_%s_capcutpc_0.exe" % v,
            "CapCut_%s_capcutpc_0_creatortool.exe" % v,
            "CapCut_split_%s_capcutpc_0.exe" % v,
        ]
        for name in variants:
            if name != base:
                out.append(("https://sf16-web-tos-buz.capcutcdn-us.com/obj/capcut-web-buz-tx/packages/" + name, False))
    elif product == "jianying" and platform == "win-x64":
        out.append((url.replace("lf3-package.vlabstatic.com", "lf6-package.vlabstatic.com"), True))
        out.append((url.replace("lf6-package.vlabstatic.com", "lf3-package.vlabstatic.com"), True))
    seen, res = set(), []
    for u, same in out:
        if u != url and u not in seen:
            seen.add(u)
            res.append((u, same))
    return res


def collect_store(cat, product, pid, market, locale):
    st, _, body = http_get(STORE_MANIFEST.format(pid=pid, mkt=market, loc=locale))
    if st != 200:
        raise RuntimeError("Store %s HTTP %d" % (pid, st))
    data = json.loads(body)["Data"]["Versions"][0]
    ver = data["PackageVersion"]
    seen = set()
    for inst in data.get("Installers") or []:
        arch = inst.get("Architecture")
        platform = {"x64": "win-x64", "arm64": "win-arm64"}.get(arch)
        url = inst.get("InstallerUrl")
        sha = inst.get("InstallerSha256")
        if not platform or not url or platform in seen:
            continue
        seen.add(platform)
        # 优先用官方 CDN 的 creatortool 完整包，Store 链接作为备用
        primary, size = url, None
        for tmpl in CDN.get((product, platform), []):
            cand = tmpl.format(v=ver.replace(".", "_"))
            pst, psize = probe(cand)
            if pst in (200, 206) and psize:
                primary, size = cand, psize
                break
        cat.add(make_entry(product, platform, ver, primary, sha256=sha, source="msstore",
                           size=size, release_date=None))
        if primary != url:
            cat.add(make_entry(product, platform, ver, url, sha256=sha, source="msstore"))
    return {"version": ver, "installers": sorted(seen)}


def collect_brew_latest(cat, product="capcut"):
    st, _, body = http_get("https://formulae.brew.sh/api/cask/capcut.json")
    if st != 200:
        raise RuntimeError("brew HTTP %d" % st)
    d = json.loads(body)
    cat.add(make_entry(product, "mac", d["version"], d["url"], sha256=d.get("sha256"),
                       source="brew"))
    return d["version"]


def collect_brew_history(cat, product="capcut"):
    st, _, body = http_get("https://api.github.com/repos/Homebrew/homebrew-cask/commits"
                           "?path=Casks/c/capcut.rb&per_page=100")
    if st != 200:
        raise RuntimeError("brew history HTTP %d" % st)
    commits = json.loads(body)
    seen = set()
    for c in commits:
        sha = c["sha"]
        st, _, txt = http_text("https://raw.githubusercontent.com/Homebrew/homebrew-cask/%s/Casks/c/capcut.rb" % sha)
        if st != 200:
            continue
        mv = re.search(r'version\s+"([^"]+)"', txt)
        mu = re.search(r'url\s+"([^"]+)"', txt)
        mh = re.search(r'sha256\s+"([^"]+)"', txt)
        if not (mv and mu):
            continue
        ver, url = mv.group(1), mu.group(1)
        url = url.replace('#{version.dots_to_underscores}', ver.replace(".", "_"))
        url = url.replace('#{version}', ver)
        if ver in seen or vkey(ver) < [9, 0, 0]:
            continue
        seen.add(ver)
        cat.add(make_entry(product, "mac", ver, url,
                           sha256=(mh.group(1) if mh and len(mh.group(1)) == 64 else None),
                           source="brew"))
    return len(seen)


def collect_capcut_mac_settings(cat, product="capcut"):
    st, _, txt = http_text(CAPCUT_SETTINGS)
    if st != 200:
        raise RuntimeError("settings HTTP %d" % st)
    try:
        rem = json.loads(txt)["data"]["settings"]["update_reminder"]
    except Exception:
        raise RuntimeError("settings 中未找到 update_reminder")
    urls = {v for v in rem.values() if isinstance(v, str) and v.startswith("http") and ".dmg" in v}
    got = []
    for u in sorted(urls):
        v = parse_capcut_dmg_version(u)
        if v:
            cat.add(make_entry(product, "mac", v, u, source="capcut-settings"))
            got.append(v)
    if not got:
        raise RuntimeError("settings 中未解析到 DMG 版本")
    return got


def parse_capcut_dmg_version(url):
    fn = os.path.basename(url)
    m = re.search(r"CapCut_(\d+)_(\d+)_(\d+)-beta(\d+)_(\d+)_", fn)
    if m:
        return "%s.%s.%s-beta%s.%s" % m.groups()
    m = re.search(r"CapCut_(\d+)_(\d+)_(\d+)_(\d+)_", fn)
    if m:
        return ".".join(m.groups())
    return None


def collect_jianying_android(cat, deep=False):
    st, _, body = http_text(UGAPK_INDEX)
    if st != 200:
        raise RuntimeError("ugapk HTTP %d" % st)
    dirs = re.findall(r'href="[^"]*?/videocut/([^"/]+)" class="dir">', body)
    if not dirs:
        raise RuntimeError("ugapk 目录解析为空")
    # versionCode 后缀（9 位）优先，其它目录按原目录名收录
    coded = []
    for d in dirs:
        m = re.search(r"_(\d{9})$", d)
        if m:
            coded.append((int(m.group(1)), d))
    by_vc = {}
    for vc, d in coded:
        by_vc.setdefault(vc, []).append(d)
    plan = []
    for vc in sorted(by_vc, reverse=True):
        same = sorted(by_vc[vc], key=lambda d: (0 if d.startswith("18076_") else
                                                1 if d.startswith("4903_") else 2, d))
        plan.append((vc, same[0]))
    for d in sorted(dirs):
        if not re.search(r"_\d{9}$", d):
            plan.append((None, d))

    added = 0
    for vc, d in plan:
        ver, build = (decode_jianying_vc(vc) if vc else (d, None))
        eid = "%s-android-%s" % ("jianying", safe(ver))
        if build:
            eid += "-" + safe(build)
        if not deep and cat.get(eid):
            continue
        st, _, listing = http_text(UGAPK_INDEX + d + "/")
        if st != 200:
            continue
        apks = re.findall(r'href="([^"]+\.apk)"[^>]*>[^<]*</a>, file, (\d+) bytes', listing)
        full = [(u, int(sz)) for u, sz in apks if int(sz) >= 100 * 1024 * 1024]
        if not full:
            continue
        u, sz = max(full, key=lambda x: x[1])
        url = u.replace("/mnt/cephfs_hl/apk/", UGAPK_BASE)
        cat.add(make_entry("jianying", "android", ver, url, size=sz, source="ugapk",
                           build=build, id=eid))
        added += 1
    return {"dirs": len(dirs), "added": added}


def decode_jianying_vc(vc):
    s = str(vc)
    if len(s) == 9:
        return "%s.%s.%s" % (s[0:2], s[2], s[3]), s
    return str(vc), None


def collect_capcut_android(cat):
    st, size = probe(CAPCUT_APK)
    if st not in (200, 206) or not size:
        raise RuntimeError("CapCut APK HTTP %d" % st)
    existing = [e for e in cat.entries.values()
                if e.get("product") == "capcut" and e.get("platform") == "android"]
    if any(e.get("size") == size for e in existing):
        return {"changed": False, "size": size}
    # 体积变了才下载整包，解析版本号后入库
    TEMP.mkdir(exist_ok=True)
    path = TEMP / "capcut_android.apk"
    got_size, sha = download(CAPCUT_APK, path)
    ver = apk_version(path) or "build-%s" % sha[:8]
    mtime = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cat.add(make_entry("capcut", "android", ver, CAPCUT_APK, size=got_size, sha256=sha,
                       release_date=mtime, source="official-cdn"))
    path.unlink(missing_ok=True)
    return {"changed": True, "version": ver, "size": got_size}


def apk_version(path):
    """尽量从 APK 里取 versionName：aapt > 常见属性文件 > 扫描字符串。"""
    try:
        p = subprocess.run(["aapt", "dump", "badging", str(path)],
                           capture_output=True, timeout=60)
        m = re.search(r"versionName='([^']+)'", (p.stdout or b"").decode("utf-8", "ignore"))
        if m:
            return m.group(1)
    except Exception:
        pass
    import zipfile
    try:
        with zipfile.ZipFile(path) as z:
            for name in ("META-INF/com/android/build/gradle/app-metadata.properties",
                         "assets/app-metadata.properties"):
                if name in z.namelist():
                    txt = z.read(name).decode("utf-8", "ignore")
                    m = re.search(r"(?im)^appMetadataVersionName=(.+)$", txt)
                    if m:
                        return m.group(1).strip()
    except Exception:
        pass
    try:
        with zipfile.ZipFile(path) as z:
            blob = z.read("AndroidManifest.xml")
        found = []
        i = 0
        while i + 1 < len(blob):
            j = i
            chars = []
            while j + 1 < len(blob):
                c = blob[j] | (blob[j + 1] << 8)
                if 32 <= c < 127:
                    chars.append(chr(c))
                    j += 2
                else:
                    break
            if len(chars) >= 5:
                found.append("".join(chars))
            i = j + 2
        vers = [x for x in found if re.fullmatch(r"\d+\.\d+\.\d+(?:[.-][\w.]+)?", x)]
        if vers:
            return max(vers, key=vkey)
    except Exception:
        pass
    return None



def collect_seeds(cat):
    for e in SEED_ENTRIES:
        e = dict(e)
        cat.add(make_entry(e.pop("product"), e.pop("platform"), e.pop("version"),
                           e.pop("url"), **e))
    return len(SEED_ENTRIES)


# ============================================================ 校验 / 发布
def verify_entries(cat, entries, workers=24, quiet=False):
    def one(e):
        cands = [(e.get("url"), None)] + [(a.get("url"), a) for a in (e.get("alternates") or [])]
        seen = set()
        statuses = []
        for u, alt in cands:
            if not u or u in seen:
                continue
            seen.add(u)
            st, size = probe(u)
            statuses.append(st)
            if st in (200, 206) and size:
                return e["id"], st, size, u, alt, statuses
        return e["id"], (statuses[-1] if statuses else 0), None, None, None, statuses

    dead = promoted = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for eid, st, size, good_url, alt, statuses in ex.map(one, entries):
            e = cat.entries[eid]
            e["http_status"] = st
            if good_url:
                same_sha = False
                if good_url != e.get("url"):
                    alt_sha = ((alt or {}).get("sha256") or "").lower()
                    same_sha = bool(alt_sha) and alt_sha == (e.get("sha256") or "").lower()
                    # 主链接明确失效，或镜像与主链接是同一文件时才切换。
                    # 超时（状态 0）不代表链接失效，不能因此覆盖官方主链接。
                    primary_dead = bool(statuses) and statuses[0] in (404, 410, 500)
                    if same_sha or primary_dead:
                        old = {"source": e.get("source"), "url": e.get("url"),
                               "sha256": e.get("sha256"), "size": e.get("size")}
                        e["url"] = good_url
                        if not same_sha:
                            # 不同安装形态：官方 SHA256 属于原文件，不能沿用
                            e["sha256"] = (alt or {}).get("sha256")
                        if alt and alt.get("source"):
                            e["source"] = alt["source"]
                        e.setdefault("alternates", [])
                        if not any(a.get("url") == old["url"] for a in e["alternates"]):
                            e["alternates"].append(old)
                        e["asset_name"] = default_asset_name(
                            e.get("product"), e.get("platform"), e.get("version"), good_url)
                        promoted += 1
                # 只有主链接本身、或与主链接同 SHA 的镜像，才能用探测到的长度。
                # 不同 SHA 的备用包大小不同，不能写进当前条目。
                if size and (good_url == e.get("url") or same_sha):
                    e["size"] = size
                e["dead"] = False
            elif statuses and all(x in (404, 410, 500) for x in statuses):
                e["dead"] = True
                e["dead_reason"] = "HTTP %s" % "/".join(str(x) for x in statuses)
                dead += 1
    if not quiet:
        log("  校验 %d 条, 新增失效 %d, 切换镜像 %d" % (len(entries), dead, promoted))
    return dead


def release_state():
    """tag -> set(asset names)。用 Releases API 分页，避免 N 次调用。"""
    state = {}
    page = 1
    while True:
        p = gh(["api", "repos/%s/releases?per_page=100&page=%d" % (REPO, page)], check=False)
        if p.returncode != 0:
            raise RuntimeError("获取 Releases 失败: " + (p.stderr or b"").decode("utf-8", "ignore")[:300])
        batch = json.loads(p.stdout.decode("utf-8", "ignore") or "[]")
        for r in batch:
            state[r["tag_name"]] = {a["name"] for a in (r.get("assets") or []) if a.get("name")}
        if len(batch) < 100:
            break
        page += 1
    return state


def gh(args, check=True, timeout=1800):
    p = subprocess.run(["gh"] + args, capture_output=True, timeout=timeout)
    if check and p.returncode != 0:
        raise RuntimeError("gh %s 失败: %s" % (" ".join(args), (p.stderr or b"").decode("utf-8", "ignore")[:500]))
    return p


def release_title(e):
    return "%s %s · %s" % (PRODUCTS.get(e["product"], e["product"]),
                           e.get("version"), PLATFORMS.get(e.get("platform"), e.get("platform")))


def release_notes(e):
    size = ("%s B (%s)" % (format(e["size"], ","), human_size(e["size"]))) if e.get("size") else "未知"
    lines = [
        "## %s · %s" % (PRODUCTS.get(e["product"], e["product"]),
                        PLATFORMS.get(e.get("platform"), e.get("platform"))),
        "",
        "| 项目 | 值 |",
        "| :--- | :--- |",
        "| **版本** | `%s` |" % e.get("version"),
    ]
    if e.get("build"):
        lines.append("| **构建号** | `%s` |" % e["build"])
    lines += [
        "| **平台** | %s |" % PLATFORMS.get(e.get("platform"), e.get("platform")),
        "| **发布日期** | %s |" % (e.get("release_date") or "未知"),
        "| **文件大小** | %s |" % size,
        "| **SHA256** | `%s` |" % (e.get("sha256") or "未知"),
        "| **数据来源** | `%s` |" % (e.get("source") or "-"),
    ]
    if e.get("url"):
        lines.append("| **官方直链** | [下载](%s) |" % e["url"])
    lines.append("")
    if e.get("note"):
        lines.append("> ℹ️ %s" % e["note"])
    if e.get("dead"):
        lines.append("> ⚠️ **官方直链已失效**，本 Release 仅保留版本记录。")
    else:
        lines.append("> 📦 离线完整安装包见 Release 附件；若附件暂缺，可先使用上方官方直链。")
    lines += ["", "---", "由 [capcut-versions](https://github.com/%s) 自动归档。" % REPO]
    if e.get("alternates"):
        lines += ["", "<details><summary>其它分发形态</summary>", ""]
        for a in e["alternates"]:
            lines.append("- `%s`: %s" % (a.get("source") or "-", a.get("url") or "-"))
        lines += ["", "</details>"]
    return "\n".join(lines)


def refresh_notes(e):
    gh(["release", "edit", tag_of(e), "-n", release_notes(e)], timeout=120)


def do_publish(cat, entries, with_asset=False, dry_run=False, max_count=None):
    state = {} if dry_run else release_state()
    todo = [e for e in entries if tag_of(e) not in state]
    if max_count:
        todo = todo[:max_count]
    log("待创建 Release: %d 个%s" % (len(todo), "（dry-run）" if dry_run else ""))
    created = archived = failed = 0
    for e in todo:
        tag = tag_of(e)
        try:
            if dry_run:
                log("  [dry-run] %s  %s" % (tag, e["url"]))
            else:
                cmd = ["release", "create", tag, "-t", release_title(e), "-n", release_notes(e), "--latest=false"]
                gh(cmd, timeout=300)
                created += 1
            e["released"] = True
            if with_asset and e.get("url") and not e.get("dead"):
                if dry_run:
                    log("  [dry-run] 下载 %s" % e["url"])
                    continue
                TEMP.mkdir(exist_ok=True)
                dest, size, sha = fetch_asset(e, TEMP)
                name = dest.name
                gh(["release", "upload", tag, str(dest), "--clobber"], timeout=1800)
                refresh_notes(e)
                archived += 1
                dest.unlink(missing_ok=True)
                e["archived"] = True

        except Exception as ex:
            failed += 1
            e["last_error"] = str(ex)[:300]
            warn("%s: %s" % (tag, ex))
        time.sleep(1.0)
    return {"created": created, "archived": archived, "failed": failed, "total": len(todo)}


def do_backfill(cat, ids, dry_run=False, force=False):
    state = {} if dry_run else release_state()
    entries = [cat.entries[i] for i in ids if i in cat.entries]
    ok = skip = fail = 0
    for e in entries:
        tag = tag_of(e)
        if e.get("dead") or not e.get("url"):
            skip += 1
            continue
        assets = state.get(tag) or set()
        if assets and not force:
            skip += 1
            continue
        try:
            if dry_run:
                log("[dry-run] %s <- %s" % (tag, e["url"]))
                ok += 1
                continue
            if tag not in state:
                gh(["release", "create", tag, "-t", release_title(e),
                    "-n", release_notes(e), "--latest=false"], timeout=300)
            TEMP.mkdir(exist_ok=True)
            dest, size, sha = fetch_asset(e, TEMP)
            gh(["release", "upload", tag, str(dest), "--clobber"], timeout=1800)
            refresh_notes(e)
            dest.unlink(missing_ok=True)
            e["archived"] = True
            e["released"] = True
            e["last_error"] = None
            ok += 1
            log("  ✓ %s %s" % (tag, human_size(size)))
        except Exception as ex:
            fail += 1
            e["last_error"] = str(ex)[:300]
            warn("%s: %s" % (tag, ex))
    return {"uploaded": ok, "skipped": skip, "failed": fail}


# ============================================================ 日志
def render_log(cat, path=RELEASE_LOG):
    state = {}
    try:
        state = release_state()
    except Exception:
        pass
    lines = [
        "# 剪映 / CapCut Release Log",
        "",
        "> 由 `scripts/capcut_versions.py log` 自动生成，请勿手工编辑。",
        "> 国际版 = CapCut，国内版 = 剪映。所有版本均来自官方或官方镜像通道。",
        "",
    ]
    for product in ("jianying", "capcut"):
        lines += ["## %s (%s)" % (PRODUCTS[product], "国内版" if product == "jianying" else "国际版"), ""]
        for platform in ("win-x64", "win-arm64", "mac", "android"):
            entries = [e for e in cat.entries.values()
                       if e.get("product") == product and e.get("platform") == platform]
            if not entries:
                continue
            entries.sort(key=lambda e: vkey(e.get("version")), reverse=True)
            lines += ["### %s (%d)" % (PLATFORMS[platform], len(entries)), "",
                      "| 日期 | 版本 | 大小 | SHA256 | 归档 | 下载 |",
                      "| :--- | :--- | :--- | :--- | :--- | :--- |"]
            for e in entries:
                assets = state.get(tag_of(e)) or set()
                if e.get("dead"):
                    status = "链接失效"
                elif assets:
                    status = "已归档"
                elif e.get("released"):
                    status = "待上传"
                else:
                    status = "待发布"
                link = ("https://github.com/%s/releases/tag/%s" % (REPO, tag_of(e))) if e.get("released") or tag_of(e) in state else ""
                lines.append("| %s | **%s** | %s | `%s` | %s | %s |" % (
                    e.get("release_date") or e.get("first_seen") or "-",
                    e.get("version"),
                    human_size(e.get("size")),
                    (e.get("sha256") or "")[:8] or "-",
                    status,
                    "[Release](%s)" % link if link else "-",
                ))
            lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")
    return len(cat.entries)


# ============================================================ 命令
def parse_selection(args):
    products = None
    platforms = None
    for i, a in enumerate(args):
        if a == "--product" and i + 1 < len(args):
            v = args[i + 1]
            products = [x for x in ("jianying", "capcut")] if v == "all" else [v]
        if a == "--platform" and i + 1 < len(args):
            v = args[i + 1]
            platforms = list(PLATFORMS) if v == "all" else [v]
    return products, platforms


def cmd_collect(args):
    deep = "--deep" in args
    cat = Catalog()
    cat.new_ids = []          # 每次采集重新计数，供同一次运行的 publish --new-only 使用
    log("采集开始%s" % ("（全量历史）" if deep else ""))
    failures = {}
    steps = [
        ("winget-jianying", lambda: collect_winget(cat, "jianying", "JianyingPro", deep)),
        ("winget-capcut", lambda: collect_winget(cat, "capcut", "CapCut", deep)),
        ("store-jianying", lambda: collect_store(cat, "jianying", "XPDM5FWDZZVHBX", "CN", "zh-cn")),
        ("store-capcut", lambda: collect_store(cat, "capcut", "XP9KN75RRB9NHS", "US", "en-us")),
        ("brew-latest", lambda: collect_brew_latest(cat)),
        ("capcut-mac-settings", lambda: collect_capcut_mac_settings(cat)),
        ("jianying-android", lambda: collect_jianying_android(cat, deep)),
        ("capcut-android", lambda: collect_capcut_android(cat)),
        ("seeds", lambda: collect_seeds(cat)),
    ]
    if deep:
        steps.insert(5, ("brew-history", lambda: collect_brew_history(cat)))
    for name, fn in steps:
        try:
            r = fn()
            log("  ✓ %-22s %s" % (name, json.dumps(r, ensure_ascii=False) if r is not None else ""))
        except Exception as ex:
            failures[name] = str(ex)[:200]
            warn("%-22s %s" % (name, ex))
    if deep:
        new = cat.missing_size()
    else:
        new = [cat.entries[i] for i in cat.new_ids
               if i in cat.entries and not cat.entries[i].get("size")]
    if new:
        verify_entries(cat, new)
    cat.save()
    log("目录: %d 条, 新增 %d 条" % (len(cat.entries), len(cat.new_ids)))
    if failures:
        log("失败源 %d 个（不影响其它源）: %s" % (len(failures), ", ".join(failures)))
    return 0


def cmd_verify(args):
    cat = Catalog()
    only_missing = "--all" not in args
    entries = cat.missing_size() if only_missing else list(cat.entries.values())
    verify_entries(cat, entries)
    cat.save()
    return 0


def cmd_publish(args):
    cat = Catalog()
    products, platforms = parse_selection(args)
    ids = arg_value(args, "--ids")
    entries = cat.select(products=products, platforms=platforms,
                         new_only=("--new-only" in args),
                         ids=ids.split(",") if ids else None)
    if "--new-only" in args and not NEW_IDS.exists():
        warn("没有 .cache/new_ids.json，请先运行 collect")
        return 0
    result = do_publish(cat, entries, with_asset=("--with-asset" in args),
                        dry_run=("--dry-run" in args),
                        max_count=int(arg_value(args, "--max") or 0) or None)
    if "--dry-run" not in args:
        cat.save()
        render_log(cat)
    log(json.dumps(result, ensure_ascii=False))
    return 0 if result["failed"] == 0 else 1


def cmd_backfill(args):
    cat = Catalog()
    ids = (arg_value(args, "--ids") or "").split(",")
    ids = [i for i in ids if i]
    if not ids:
        warn("需要 --ids")
        return 1
    result = do_backfill(cat, ids, dry_run=("--dry-run" in args), force=("--force" in args))
    if "--save" in args:
        cat.save()
    log(json.dumps(result, ensure_ascii=False))
    return 0 if result["failed"] == 0 else 1


def cmd_plan(args):
    cat = Catalog()
    products, platforms = parse_selection(args)
    batch = int(arg_value(args, "--batch-size") or 6)
    state = release_state()
    entries = cat.select(products=products, platforms=platforms,
                         missing_assets=True, state=state)
    batches = []
    for i in range(0, len(entries), batch):
        batches.append({"ids": ",".join(e["id"] for e in entries[i:i + batch])})
    if not batches:
        batches = [{"ids": ""}]
    out = {"include": batches}
    if "--json" in args:
        print(json.dumps(out))
    else:
        log("待回填 %d 条, 分 %d 批" % (len(entries), len(batches) if entries else 0))
        for e in entries:
            log("  %s  %s" % (tag_of(e), human_size(e.get("size"))))
    return 0


def cmd_sync(args):
    cat = Catalog()
    state = release_state()
    released = archived = 0
    for e in cat.entries.values():
        tag = tag_of(e)
        if tag in state:
            e["released"] = True
            if state[tag]:
                e["archived"] = True
                archived += 1
            elif not e.get("dead"):
                e["archived"] = False
            released += 1
    cat.save()
    log("同步 Releases: %d 个已发布, %d 个含附件" % (released, archived))
    return 0


def cmd_status(args):
    cat = Catalog()
    log("目录更新时间: %s" % cat.data.get("updated_at", "-"))
    for product in ("jianying", "capcut"):
        log("\n%s" % PRODUCTS[product])
        for platform in PLATFORMS:
            es = [e for e in cat.entries.values()
                  if e.get("product") == product and e.get("platform") == platform]
            if not es:
                continue
            released = sum(1 for e in es if e.get("released"))
            archived = sum(1 for e in es if e.get("archived"))
            dead = sum(1 for e in es if e.get("dead"))
            log("  %-13s %3d 条  已发布 %3d  已归档 %3d  失效 %3d  %s" % (
                PLATFORMS[platform], len(es), released, archived, dead,
                "最新 " + max((e.get("version") for e in es), key=vkey)))
    return 0


def cmd_log(args):
    cat = Catalog()
    n = render_log(cat)
    log("已生成 %s（%d 条）" % (RELEASE_LOG.name, n))
    return 0


def arg_value(args, name):
    if name in args:
        i = args.index(name)
        if i + 1 < len(args):
            return args[i + 1]
    return None


USAGE = __doc__


def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(USAGE)
        return 0 if len(argv) > 1 else 1
    cmd, args = argv[1], argv[2:]
    handlers = {
        "collect": cmd_collect, "verify": cmd_verify, "publish": cmd_publish,
        "backfill": cmd_backfill, "plan": cmd_plan, "log": cmd_log, "status": cmd_status,
        "sync": cmd_sync,
    }
    if cmd not in handlers:
        print(USAGE)
        return 1
    return handlers[cmd](args)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
