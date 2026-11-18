# -*- coding: utf-8 -*-
"""
免费节点搜索器 v1.0
开发作者：mycgb
功能：
  1. 双引擎搜索：GitHub（官方 API 搜仓库） / Bing（网页搜索）
  2. 一键提取订阅链接：从 GitHub 仓库 README / 网页正文里抓出 .yaml/.yml/订阅地址
  3. 一键检测订阅：请求订阅链接，判断是否可用并估算节点数（只认 Clash YAML 等格式特征）
  4. 内置已验证源：可直接检测、复制导入 FlClash 等客户端

运行：python node_searcher.py   （或双击 run.bat）
依赖：零第三方依赖，只用 Python 标准库，Python 3.8+ 即可。
      有 tkinter 时开桌面窗口；没有 tkinter 时自动切换为浏览器界面（本地 127.0.0.1）。
"""
import base64
import http.server
import json
import re
import sys
import threading
import traceback
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from html.parser import HTMLParser

try:
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog
    HAS_TK = True
except ImportError:
    # 有些精简版 / 嵌入式 Python 不带 tkinter。这里给一个占位基类，
    # 让下面的 class App(tk.Tk) 能正常定义（HAS_TK=False 时绝不会实例化它）。
    HAS_TK = False
    class _TkStub:
        class Tk:
            pass
    tk = _TkStub()
    ttk = messagebox = filedialog = None

# 控制台输出统一用 ASCII（原因见 run.bat 顶部注释）：不强制 stdout 为 UTF-8，
# 否则中文 Windows 的 936 代码页窗口会把 UTF-8 字节显示成乱码。
# PyInstaller 的 --windowed / --noconsole 构建里 sys.stdout / sys.stderr 是 None，
# 不先补一个哑 writer，任何 print() 都会抛 AttributeError 让打包版直接崩掉。
class _NullWriter:
    def write(self, *args, **kwargs):
        return 0

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def flush(self):
        pass

    def isatty(self):
        return False


if sys.stdout is None:
    sys.stdout = _NullWriter()
if sys.stderr is None:
    sys.stderr = _NullWriter()
try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass

APP_TITLE = "免费节点搜索器 — GitHub / Bing 双引擎"
APP_AUTHOR = "mycgb"
APP_VERSION = "v1.0"

ABOUT_TEXT = f"""\
免费节点搜索器  {APP_VERSION}
开发作者：{APP_AUTHOR}

【这个工具做什么】
从 GitHub 仓库 / Bing 网页里找公开的 Clash、V2Ray 订阅链接，提取后逐条检测格式是否有效，
再把可用的订阅复制到 FlClash 等客户端导入。程序只判断订阅文件格式，不代理、不加速，
也不保证节点能连。

【快速上手】
1. 选引擎：GitHub 用官方 API 搜仓库（结果准、带星数和更新时间）；Bing 搜网页（范围广）。
2. 选一个预设关键词，或自己输入，点「开始搜索」。
3. 在结果里选中一条，点「提取订阅链接」：程序会抓 README / 网页里的订阅地址；
   带（猜测）标记的是常见文件名直链，必须检测通过才能用。
4. 点「检测全部订阅」逐条验证：
   ✅ 返回标准 Clash YAML（含 proxies 和节点）或 Base64 / 明文节点列表，并显示约多少节点；
   ❌ 会说明原因：404、返回的是网页、没识别出节点特征等。
5. 选中 ✅ 的订阅，点「复制选中订阅」，到 FlClash：配置 → 新建 → 从 URL 导入，粘贴即可。

【常用按钮】
· 双击搜索结果 = 打开链接；双击某条订阅 = 只检测这一条。
· 清空日志 / 清空搜索结果 / 清空订阅列表：各自只清对应区域，互不影响。
· 清空全部：一键清掉三者，会先弹确认框；清空订阅后点「重新载入内置源」可恢复。
· 导出订阅列表 (.txt)：把当前列表存成文本文件，方便备份或分享。
· 在浏览器打开搜索页（备用）：搜索引擎抽风时，直接去官网手动找。

【常见问题】
· GitHub 搜索报 HTTP 403：未登录限额约 10 次/分钟，等一分钟，或填自己的 GitHub Token。
· 检测结果大多是 ❌：免费源随时失效，常见是 404 或返回网页；换关键词重新搜即可。
· 检测通过不等于节点能连：只说明订阅格式对，实际速度要导入客户端后测延迟。
· .txt 的 IP 优选列表不是 Clash 订阅，导不进 FlClash；只导入检测为 ✅ 的 .yaml/.yml 订阅。
· 启动报缺少 tkinter：程序会自动换一个带 tkinter 的 Python 重启桌面窗口，
  实在没有就切换成浏览器界面（本机 127.0.0.1:8765，关闭命令行窗口即退出）。

【安全提醒】
免费节点来历不明，不要用来登录重要账号、网银等敏感操作；GitHub Token 不要发给任何人。

运行环境：Python 3.8+，零第三方依赖，只用标准库（tkinter / urllib / http.server）。
"""

UA_BROWSER = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")
UA_CLASH = "clash-verge/v2.0 (FlClash; sing-box)"

PRESET_QUERIES = [
    "clash free subscription yaml",
    "clash 免费订阅 节点",
    "get_subscribe clash",
    "free v2ray nodes subscription",
    "clash subscription daily update github",
    "免费节点 clash yaml 每日更新",
    "vless free nodes github",
    "awesome vpn clash",
]

# 内置源：此前实际验证过为标准 Clash YAML 的公开源；可用性会随时间变化，使用前请点“检测全部内置源”
BUILTIN_SOURCES = [
    # ermaozi 仓库已改版：根目录 clash.yml 已下线（404），README 公布的新地址实测可用（2026-11-16，约172节点）
    ("ermaozi/get_subscribe（新地址）", "https://blog.ermao.net/sub/clash/ermao.net"),
    ("anaer/Sub", "https://raw.githubusercontent.com/anaer/Sub/main/clash.yaml"),
    ("mahdibland/V2RayAggregator", "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/sub_merge_yaml.yml"),
]

SUB_HINT_WORDS = (".yaml", ".yml", "clash", "subscribe", "/sub", "get_subscribe",
                  "v2ray", "raw.githubusercontent", "jsdelivr", "proxies")


# ----------------------------- 网络工具 -----------------------------
def http_get(url, ua=UA_BROWSER, timeout=15, max_bytes=3_000_000, extra_headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "*/*"})
    if extra_headers:
        for k, v in extra_headers.items():
            req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read(max_bytes)
        charset = resp.headers.get_content_charset() or "utf-8"
    try:
        return data.decode(charset, errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


def http_get_bytes(url, ua=UA_CLASH, timeout=15, max_bytes=3_000_000):
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        status = resp.status
        data = resp.read(max_bytes)
    return status, data


# ----------------------------- GitHub 搜索 -----------------------------
def search_github(query, token="", per_page=30):
    """用 GitHub 官方 API 搜索仓库，返回 [{title, info, desc, url, full_name, default_branch}]"""
    q = urllib.parse.quote(query)
    url = f"https://api.github.com/search/repositories?q={q}&sort=updated&order=desc&per_page={per_page}"
    headers = {"Accept": "application/vnd.github+json"}
    if token.strip():
        headers["Authorization"] = "Bearer " + token.strip()
    text = http_get(url, timeout=20, extra_headers=headers)
    data = json.loads(text)
    results = []
    for item in data.get("items", []):
        updated = (item.get("updated_at") or "")[:10]
        info = f"★{item.get('stargazers_count', 0)}  更新:{updated}  {item.get('language') or ''}"
        results.append({
            "title": item.get("full_name", ""),
            "info": info,
            "desc": item.get("description") or "",
            "url": item.get("html_url", ""),
            "full_name": item.get("full_name", ""),
            "default_branch": item.get("default_branch") or "main",
        })
    return results, data.get("total_count", len(results))


# ----------------------------- Bing 搜索 -----------------------------
def _decode_bing_redirect(href):
    """Bing 结果常是 /ck/a 跳转链接，u 参数里藏着真实地址（a1 + base64）"""
    try:
        parsed = urllib.parse.urlparse(href)
        if "bing.com" in parsed.netloc and "/ck/a" in parsed.path:
            qs = urllib.parse.parse_qs(parsed.query)
            u = (qs.get("u") or [""])[0]
            if u.startswith("a1") and len(u) > 10:
                b64 = u[2:]
                b64 += "=" * (-len(b64) % 4)
                return base64.urlsafe_b64decode(b64).decode("utf-8", errors="replace")
    except Exception:
        pass
    return href


class _BingParser(HTMLParser):
    """解析 Bing 结果页：每个结果在 <li class='b_algo'> 里，标题在 <h2><a>，摘要在 <p>"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results = []
        self._in_algo = False
        self._depth = 0
        self._cur = None
        self._capture = None  # 'title' | 'desc'
        self._in_h2 = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "li" and "b_algo" in (attrs.get("class") or ""):
            self._in_algo = True
            self._depth = 1
            self._cur = {"title": "", "desc": "", "url": ""}
            return
        if not self._in_algo:
            return
        if tag in ("li", "div", "ul"):
            self._depth += 1
        if tag == "h2":
            self._in_h2 = True
        if tag == "a" and self._in_h2 and self._cur is not None and not self._cur["url"]:
            # 只认 h2 里的链接为结果链接，避免抓到 cite/出处链接污染标题
            self._cur["url"] = attrs.get("href") or ""
            self._capture = "title"
        elif tag == "p" and self._cur is not None:
            self._capture = "desc"

    def handle_endtag(self, tag):
        if not self._in_algo:
            return
        if tag == "h2":
            self._in_h2 = False
        if tag == "a" and self._capture == "title":
            self._capture = None
        if tag == "p" and self._capture == "desc":
            self._capture = None
        if tag in ("li", "div", "ul"):
            self._depth -= 1
            if self._depth <= 0 and tag == "li":
                self._in_algo = False
                if self._cur and self._cur["url"]:
                    self._cur["url"] = _decode_bing_redirect(self._cur["url"])
                    self._cur["title"] = self._cur["title"].strip() or self._cur["url"]
                    self._cur["desc"] = self._cur["desc"].strip()
                    self._cur["info"] = "Bing 网页结果"
                    self._cur["full_name"] = ""
                    self.results.append(self._cur)
                self._cur = None

    def handle_data(self, data):
        if self._in_algo and self._cur is not None and self._capture:
            self._cur[self._capture] += data


def search_bing(query, count=30):
    q = urllib.parse.quote(query)
    url = f"https://www.bing.com/search?q={q}&count={count}&setlang=zh-CN"
    html = http_get(url, timeout=20)
    parser = _BingParser()
    parser.feed(html)
    # 去重
    seen, out = set(), []
    for r in parser.results:
        if r["url"] not in seen:
            seen.add(r["url"])
            out.append(r)
    return out


# ----------------------------- 订阅链接提取 -----------------------------
URL_RE = re.compile(r"https?://[^\s\"'<>\)\]\}，。；、]+")

def extract_sub_links(text, base_hint=""):
    """从一段文本里提取疑似订阅链接，去重保序"""
    found, seen = [], set()
    for m in URL_RE.finditer(text or ""):
        link = m.group(0).rstrip(".,;:)'\"")
        low = link.lower()
        is_raw_file = low.endswith((".yaml", ".yml")) or "/sub" in low
        has_hint = any(w in low for w in SUB_HINT_WORDS)
        if (is_raw_file or has_hint) and link not in seen:
            # 排除纯图片/徽章类链接
            if any(low.endswith(ext) for ext in (".png", ".jpg", ".svg", ".gif", ".md")):
                continue
            seen.add(link)
            found.append(link)
    return found


def extract_from_github_repo(full_name, default_branch="main", token=""):
    """抓仓库 README + 仓库首页，提取订阅链接；再补几个常见文件名直链猜测"""
    links = []
    headers = {"Accept": "application/vnd.github.raw+json"}
    if token.strip():
        headers["Authorization"] = "Bearer " + token.strip()
    try:
        readme = http_get(f"https://api.github.com/repos/{full_name}/readme",
                          timeout=20, extra_headers=headers)
        links += extract_sub_links(readme)
    except Exception:
        pass
    try:
        page = http_get(f"https://github.com/{full_name}", timeout=20)
        links += extract_sub_links(page)
    except Exception:
        pass
    # 常见订阅文件名直链（存在才会在检测时通过，不存在检测会报错，不会误导入）
    for fname in ("clash.yaml", "clash.yml", "Clash.yaml", "sub.yaml", "config.yaml"):
        guess = f"https://raw.githubusercontent.com/{full_name}/{default_branch}/{fname}"
        if guess not in links:
            links.append(guess + "  ←文件名猜测，需检测")
    # 去重保序
    out, seen = [], set()
    for x in links:
        key = x.split(" ")[0]
        if key not in seen:
            seen.add(key)
            out.append(x)
    return out


def extract_from_webpage(url):
    text = http_get(url, timeout=20)
    return extract_sub_links(text)


# ----------------------------- 订阅检测 -----------------------------
def check_subscription(url):
    """返回 (是否疑似可用, 说明)。判断标准：HTTP 200 + 内容含 Clash YAML 特征或节点协议头"""
    try:
        status, data = http_get_bytes(url, timeout=15)
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}（链接失效或仓库已删）"
    except Exception as e:
        return False, f"请求失败：{e.__class__.__name__} {e}"
    if status != 200:
        return False, f"HTTP {status}"
    text = data.decode("utf-8", errors="replace")
    size_kb = max(1, len(data) // 1024)
    # Clash YAML 特征（兼容 "- name:"、"- {name:"、"- {'name':" 等写法）
    name_count = len(re.findall(r"-\s*\{?\s*['\"]?name['\"]?\s*:", text))
    if "proxies:" in text and name_count > 0:
        return True, f"✓ Clash YAML，约 {name_count} 个节点，{size_kb} KB"
    if "proxies:" in text:
        server_count = len(re.findall(r"['\"]?server['\"]?\s*:", text))
        if server_count:
            return True, f"✓ Clash YAML（含 proxies 段，约 {server_count} 条 server 记录），{size_kb} KB"
        return True, f"✓ 含 proxies 段，{size_kb} KB（节点数需导入后看）"
    # Base64 订阅（v2ray 类）
    stripped = re.sub(r"\s+", "", text)
    if len(stripped) > 40 and re.fullmatch(r"[A-Za-z0-9+/=]+", stripped or " "):
        try:
            decoded = base64.b64decode(stripped).decode("utf-8", errors="replace")
            proto_count = sum(decoded.count(p) for p in ("vmess://", "vless://", "trojan://", "ss://"))
            if proto_count:
                return True, f"✓ Base64 订阅，约 {proto_count} 个节点，{size_kb} KB"
        except Exception:
            pass
    proto_count = sum(text.count(p) for p in ("vmess://", "vless://", "trojan://", "ss://"))
    if proto_count:
        return True, f"✓ 明文节点列表，约 {proto_count} 个节点，{size_kb} KB"
    if "<html" in text[:500].lower():
        return False, f"返回的是网页不是订阅（{size_kb} KB），多半是假链接/默认页"
    return False, f"已下载 {size_kb} KB，但没识别出节点特征"


# ----------------------------- 界面 -----------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1120x780")
        self.minsize(900, 640)
        self.results = []       # 当前搜索结果
        self.sub_links = []     # 已提取的订阅链接（纯链接，不含注释）
        self._build_ui()
        self._load_builtin()

    # ---------- UI 搭建 ----------
    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        top = ttk.LabelFrame(self, text="搜索设置")
        top.pack(fill="x", **pad)

        ttk.Label(top, text="搜索引擎：").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        self.engine = tk.StringVar(value="github")
        ttk.Radiobutton(top, text="GitHub（搜仓库，推荐）", variable=self.engine, value="github").grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(top, text="Bing（搜网页）", variable=self.engine, value="bing").grid(row=0, column=2, sticky="w")
        ttk.Label(top, text="GitHub Token（可选，提高限额）：").grid(row=0, column=3, sticky="e", padx=6)
        self.token_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.token_var, width=22, show="*").grid(row=0, column=4, sticky="w")
        ttk.Button(top, text="关于 / 使用帮助", command=self.show_about).grid(row=0, column=5, sticky="e", padx=6)

        ttk.Label(top, text="预设关键词：").grid(row=1, column=0, sticky="w", padx=6, pady=6)
        self.preset = ttk.Combobox(top, values=PRESET_QUERIES, width=38)
        self.preset.set(PRESET_QUERIES[0])
        self.preset.grid(row=1, column=1, columnspan=2, sticky="w")
        self.preset.bind("<<ComboboxSelected>>", lambda e: self.keyword_var.set(self.preset.get()))

        ttk.Label(top, text="关键词：").grid(row=2, column=0, sticky="w", padx=6, pady=6)
        self.keyword_var = tk.StringVar(value=PRESET_QUERIES[0])
        kw = ttk.Entry(top, textvariable=self.keyword_var, width=52)
        kw.grid(row=2, column=1, columnspan=2, sticky="w")
        kw.bind("<Return>", lambda e: self.do_search())
        self.btn_search = ttk.Button(top, text="🔍 开始搜索", command=self.do_search)
        self.btn_search.grid(row=2, column=3, sticky="w", padx=6)
        ttk.Button(top, text="在浏览器打开搜索页（备用）", command=self.open_search_in_browser).grid(row=2, column=4, sticky="w")

        # 搜索结果
        mid = ttk.LabelFrame(self, text="搜索结果（双击打开链接）")
        mid.pack(fill="both", expand=True, **pad)
        cols = ("title", "info", "desc", "url")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", height=12)
        for col, txt, w in (("title", "名称", 240), ("info", "信息", 210),
                            ("desc", "简介", 300), ("url", "链接", 330)):
            self.tree.heading(col, text=txt)
            self.tree.column(col, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, side="left")
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<Double-1>", lambda e: self.open_selected())

        btns = ttk.Frame(self)
        btns.pack(fill="x", **pad)
        ttk.Button(btns, text="打开链接", command=self.open_selected).pack(side="left", padx=4)
        ttk.Button(btns, text="复制链接", command=self.copy_selected).pack(side="left", padx=4)
        ttk.Button(btns, text="⬇ 提取订阅链接", command=self.do_extract).pack(side="left", padx=4)
        ttk.Button(btns, text="清空搜索结果", command=self.clear_results).pack(side="left", padx=4)
        ttk.Label(btns, text="← 选中一条结果后点这个，自动从 README/网页里抓订阅地址").pack(side="left", padx=6)

        # 下半区：订阅链接 + 日志
        bottom = ttk.PanedWindow(self, orient="horizontal")
        bottom.pack(fill="both", expand=True, **pad)

        left = ttk.LabelFrame(bottom, text="订阅链接（双击检测单个；可复制导入 FlClash）")
        self.sub_list = tk.Listbox(left, height=10)
        self.sub_list.pack(fill="both", expand=True, side="left")
        sb2 = ttk.Scrollbar(left, orient="vertical", command=self.sub_list.yview)
        sb2.pack(side="right", fill="y")
        self.sub_list.configure(yscrollcommand=sb2.set)
        self.sub_list.bind("<Double-1>", lambda e: self.check_one())
        bottom.add(left, weight=3)

        right = ttk.LabelFrame(bottom, text="日志 / 检测结果")
        log_bar = ttk.Frame(right)
        log_bar.pack(fill="x")
        ttk.Button(log_bar, text="清空日志", command=self.clear_log).pack(side="right", padx=4, pady=2)
        self.log_text = tk.Text(right, height=10, wrap="word")
        self.log_text.pack(fill="both", expand=True)
        bottom.add(right, weight=2)

        btns2 = ttk.Frame(self)
        btns2.pack(fill="x", **pad)
        ttk.Button(btns2, text="检测选中订阅", command=self.check_one).pack(side="left", padx=4)
        ttk.Button(btns2, text="检测全部订阅", command=self.check_all).pack(side="left", padx=4)
        ttk.Button(btns2, text="复制选中订阅", command=self.copy_sub).pack(side="left", padx=4)
        ttk.Button(btns2, text="导出订阅列表 (.txt)", command=self.export_subs).pack(side="left", padx=4)
        ttk.Button(btns2, text="清空订阅列表", command=self.clear_subs).pack(side="left", padx=4)
        ttk.Button(btns2, text="清空全部", command=self.clear_all).pack(side="left", padx=4)
        ttk.Button(btns2, text="重新载入内置源", command=self._load_builtin).pack(side="left", padx=4)

        self.status = tk.StringVar(value="就绪。选引擎 → 输关键词 → 开始搜索。内置源已载入订阅列表，可直接点“检测全部订阅”。")
        ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w").pack(fill="x", side="bottom")

    # ---------- 工具 ----------
    def log(self, msg):
        self.after(0, lambda: (self.log_text.insert("end", msg + "\n"), self.log_text.see("end")))

    def set_status(self, msg):
        self.after(0, lambda: self.status.set(msg))

    def run_thread(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    def _load_builtin(self):
        for name, url in BUILTIN_SOURCES:
            if url not in self.sub_links:
                self.sub_links.append(url)
                self.sub_list.insert("end", f"[内置] {name}  {url}")
        self.log("已载入内置已验证源（可用性会变化，请检测后再用）。")

    # ---------- 搜索 ----------
    def do_search(self):
        query = self.keyword_var.get().strip()
        if not query:
            messagebox.showwarning("提示", "先输入关键词")
            return
        engine = self.engine.get()
        self.btn_search.configure(state="disabled")
        self.set_status(f"正在用 {'GitHub' if engine == 'github' else 'Bing'} 搜索：{query} …")
        self.log(f"—— 搜索（{engine}）：{query}")

        def work():
            try:
                if engine == "github":
                    results, total = search_github(query, token=self.token_var.get())
                    note = f"共 {total} 个仓库，显示前 {len(results)} 个（按最近更新排序）"
                else:
                    results = search_bing(query)
                    note = f"Bing 返回 {len(results)} 条网页结果"
                self.results = results
                self.after(0, self._fill_results)
                self.log(note)
                self.set_status(note)
            except urllib.error.HTTPError as e:
                hint = "（GitHub 未登录限额约 10 次/分钟，稍等或填 Token）" if e.code == 403 else ""
                self.log(f"搜索失败：HTTP {e.code} {hint}")
                self.set_status(f"搜索失败：HTTP {e.code}")
            except Exception as e:
                self.log(f"搜索失败：{e}")
                self.set_status("搜索失败，看日志")
            finally:
                self.after(0, lambda: self.btn_search.configure(state="normal"))

        self.run_thread(work)

    def _fill_results(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for r in self.results:
            self.tree.insert("", "end", values=(r["title"], r["info"], r["desc"], r["url"]))

    def open_search_in_browser(self):
        query = urllib.parse.quote(self.keyword_var.get().strip() or "clash")
        if self.engine.get() == "github":
            webbrowser.open(f"https://github.com/search?q={query}&type=repositories")
        else:
            webbrowser.open(f"https://www.bing.com/search?q={query}")

    # ---------- 结果操作 ----------
    def _selected_result(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "先在搜索结果里选中一条")
            return None
        idx = self.tree.index(sel[0])
        return self.results[idx] if idx < len(self.results) else None

    def open_selected(self):
        r = self._selected_result()
        if r:
            webbrowser.open(r["url"])

    def copy_selected(self):
        r = self._selected_result()
        if r:
            self.clipboard_clear()
            self.clipboard_append(r["url"])
            self.set_status(f"已复制：{r['url']}")

    # ---------- 提取订阅 ----------
    def do_extract(self):
        r = self._selected_result()
        if not r:
            return
        self.set_status(f"正在从 {r['title']} 提取订阅链接…")
        self.log(f"—— 提取订阅：{r['title']}")

        def work():
            try:
                if r.get("full_name"):
                    links = extract_from_github_repo(r["full_name"], r.get("default_branch", "main"),
                                                     token=self.token_var.get())
                else:
                    links = extract_from_webpage(r["url"])
            except Exception as e:
                self.log(f"提取失败：{e}")
                return
            added = 0
            for item in links:
                pure = item.split(" ")[0]
                note = "（猜测）" if "猜测" in item else ""
                if pure not in self.sub_links:
                    self.sub_links.append(pure)
                    self.after(0, lambda p=pure, n=note: self.sub_list.insert("end", f"{n}{p}"))
                    added += 1
            self.log(f"提取到 {len(links)} 条候选，新增 {added} 条到订阅列表。带（猜测）的是常见文件名直链，检测通过才能用。")
            self.set_status(f"提取完成：新增 {added} 条订阅候选，点“检测全部订阅”验证")

        self.run_thread(work)

    # ---------- 订阅操作 ----------
    def _selected_sub(self):
        sel = self.sub_list.curselection()
        if not sel:
            messagebox.showinfo("提示", "先在订阅列表里选中一条")
            return None
        return self.sub_links[sel[0]]

    def copy_sub(self):
        url = self._selected_sub()
        if url:
            self.clipboard_clear()
            self.clipboard_append(url)
            self.set_status(f"已复制订阅：{url}")

    def clear_subs(self):
        self.sub_links.clear()
        self.sub_list.delete(0, "end")
        self.log("订阅列表已清空（可点“重新载入内置源”恢复内置源）。")

    def clear_log(self):
        """只清日志，不动搜索结果和订阅列表"""
        self.log_text.delete("1.0", "end")
        self.set_status("日志已清空。")

    def clear_results(self):
        """只清搜索结果，不动订阅列表和日志"""
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self.results = []
        self.log("搜索结果已清空（订阅列表和日志保留）。")
        self.set_status("搜索结果已清空。")

    def clear_all(self):
        """一键清空全部（带二次确认，防误删）"""
        if not messagebox.askyesno("确认清空", "将清空搜索结果、订阅列表和日志，确定继续？"):
            return
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self.results = []
        self.sub_links.clear()
        self.sub_list.delete(0, "end")
        self.log_text.delete("1.0", "end")
        self.set_status("已清空全部（可点“重新载入内置源”恢复内置源）。")

    def show_about(self):
        """关于窗口：作者信息 + 使用帮助（滚动文本框，避免长文本挤成一团）"""
        win = tk.Toplevel(self)
        win.title("关于 " + APP_TITLE)
        win.geometry("640x520")
        win.transient(self)
        frame = ttk.Frame(win)
        frame.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        text = tk.Text(frame, wrap="word", font=("Microsoft YaHei", 10))
        text.insert("1.0", ABOUT_TEXT)
        text.configure(state="disabled")
        sb = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=sb.set)
        text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        ttk.Button(win, text="关闭", command=win.destroy).pack(pady=(0, 12))
        win.focus_set()

    def export_subs(self):
        if not self.sub_links:
            messagebox.showinfo("提示", "订阅列表是空的")
            return
        path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("文本文件", "*.txt")],
                                            initialfile="订阅链接列表.txt")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(self.sub_links))
            self.set_status(f"已导出 {len(self.sub_links)} 条到 {path}")

    def _check_urls(self, urls):
        def work():
            ok = 0
            for url in urls:
                good, msg = check_subscription(url)
                ok += 1 if good else 0
                self.log(f"{'✅' if good else '❌'} {url}\n   {msg}")
            self.set_status(f"检测完成：{ok}/{len(urls)} 条可用")
        self.run_thread(work)

    def check_one(self):
        url = self._selected_sub()
        if url:
            self.log(f"—— 检测：{url}")
            self._check_urls([url])

    def check_all(self):
        if not self.sub_links:
            messagebox.showinfo("提示", "订阅列表是空的")
            return
        self.log(f"—— 检测全部 {len(self.sub_links)} 条订阅…")
        self._check_urls(list(self.sub_links))


# ----------------------------- 浏览器界面（tkinter 缺失时自动启用） -----------------------------
WEB_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>免费节点搜索器 — GitHub / Bing 双引擎</title>
<style>
  * { box-sizing: border-box; }
  body { margin:0; padding:18px 22px 24px; background:#f6f7f9; color:#1f2329;
         font:14px/1.6 "Microsoft YaHei","PingFang SC",system-ui,sans-serif; }
  h1 { font-size:19px; margin:0 0 2px; }
  h1 small { font-size:12px; font-weight:400; color:#6b7280; }
  .tip { color:#6b7280; font-size:12px; }
  .card { background:#fff; border:1px solid #e5e7eb; border-radius:10px; padding:13px 16px; margin-bottom:14px;
          box-shadow:0 1px 2px rgba(16,24,40,.04); }
  .card > h2 { font-size:14px; margin:0 0 10px; color:#374151; }
  .row { display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin-bottom:8px; }
  .row.last { margin-bottom:0; }
  label { color:#4b5563; }
  input[type=text], input[type=password], select { border:1px solid #d1d5db; border-radius:6px; padding:6px 9px;
          font:inherit; background:#fff; color:#1f2329; }
  #kw { width:380px; max-width:100%; }
  #custom { width:280px; max-width:100%; }
  button { border:1px solid #d1d5db; background:#fff; color:#1f2329; border-radius:6px; padding:6px 12px;
           font:inherit; cursor:pointer; }
  button:hover { background:#f3f4f6; }
  button.primary { background:#2563eb; border-color:#2563eb; color:#fff; }
  button.primary:hover { background:#1d4ed8; }
  button:disabled { opacity:.55; cursor:wait; }
  table { width:100%; border-collapse:collapse; table-layout:fixed; }
  th, td { border-bottom:1px solid #eef0f3; padding:7px 8px; text-align:left; overflow:hidden;
           text-overflow:ellipsis; white-space:nowrap; }
  th { color:#6b7280; font-weight:600; background:#fafafa; }
  tbody tr { cursor:pointer; }
  tr.sel td { background:#e8f0ff; }
  .grid { display:flex; gap:14px; flex-wrap:wrap; }
  .grid > .card { flex:1 1 400px; }
  #subs { width:100%; height:210px; border:1px solid #d1d5db; border-radius:6px; padding:4px;
          font:12px/1.5 Consolas,monospace; }
  #log { height:210px; overflow:auto; background:#fafafa; border:1px solid #eef0f3; border-radius:6px;
         padding:8px 10px; margin:0; white-space:pre-wrap; word-break:break-all;
         font:12px/1.55 Consolas,monospace; }
  #status { position:sticky; bottom:0; background:#eef2f7; border:1px solid #dbe2ea; border-radius:6px;
            padding:7px 10px; color:#374151; font-size:12px; }
  .mask { position:fixed; inset:0; background:rgba(15,23,42,.45); z-index:99;
          align-items:center; justify-content:center; }
  .modal { background:#fff; border:1px solid #e5e7eb; border-radius:10px; padding:16px 20px;
           width:min(660px,92vw); max-height:82vh; box-shadow:0 12px 32px rgba(15,23,42,.2);
           display:flex; flex-direction:column; }
  .modal h2 { font-size:16px; margin:0 0 10px; color:#1f2329; }
  .modal pre { flex:1; overflow:auto; white-space:pre-wrap; word-break:break-word; margin:0 0 12px;
               padding:10px 12px; background:#fafafa; border:1px solid #eef0f3; border-radius:6px;
               font:13px/1.7 "Microsoft YaHei","PingFang SC",sans-serif; color:#374151; }
</style>
</head>
<body>
<h1>免费节点搜索器 <small>GitHub / Bing 双引擎 · 浏览器界面</small></h1>
<div class="tip" style="margin-bottom:14px">
  当前 Python 没有 tkinter（或桌面窗口初始化失败），已自动切换为浏览器界面。功能与桌面版一致，关闭黑色命令行窗口即退出。
</div>

<div class="card">
  <h2>搜索设置</h2>
  <div class="row">
    <label><input type="radio" name="engine" value="github" checked> GitHub（搜仓库，推荐）</label>
    <label><input type="radio" name="engine" value="bing"> Bing（搜网页）</label>
    <label>GitHub Token（可选，提高限额）<input type="password" id="token" size="20"></label>
    <button onclick="showAbout()" style="margin-left:auto">关于 / 使用帮助</button>
  </div>
  <div class="row last">
    <label>预设关键词 <select id="preset"></select></label>
    <label>关键词 <input type="text" id="kw" placeholder="clash free subscription yaml"></label>
    <button class="primary" id="btnSearch">开始搜索</button>
    <button onclick="openSearchPage()">在浏览器打开搜索页（备用）</button>
  </div>
</div>

<div class="card">
  <h2>搜索结果（单击选中，双击打开链接）</h2>
  <div style="overflow:auto;max-height:250px">
    <table>
      <colgroup><col style="width:22%"><col style="width:20%"><col style="width:26%"><col style="width:32%"></colgroup>
      <thead><tr><th>名称</th><th>信息</th><th>简介</th><th>链接</th></tr></thead>
      <tbody id="rtbody"></tbody>
    </table>
  </div>
  <div class="row last" style="margin-top:10px">
    <button onclick="openResult()">打开链接</button>
    <button onclick="copyResult()">复制链接</button>
    <button onclick="doExtract()">提取订阅链接</button>
    <button onclick="clearResults()">清空搜索结果</button>
    <span class="tip">← 选中一条结果后点这个，自动从 README / 网页里抓订阅地址</span>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2>订阅链接（双击检测单个；可复制导入 FlClash）</h2>
    <select id="subs" multiple></select>
    <div class="row last" style="margin-top:8px">
      <input type="text" id="custom" placeholder="手动粘贴一条订阅链接">
      <button onclick="addCustom()">添加</button>
    </div>
  </div>
  <div class="card">
    <div class="row last" style="justify-content:space-between;align-items:center;margin-bottom:6px">
      <h2 style="font-size:14px;margin:0;color:#374151">日志 / 检测结果</h2>
      <button onclick="clearLog()">清空日志</button>
    </div>
    <pre id="log"></pre>
  </div>
</div>

<div class="card">
  <div class="row last">
    <button onclick="checkSel()">检测选中订阅</button>
    <button onclick="checkAll()">检测全部订阅</button>
    <button onclick="copySub()">复制选中订阅</button>
    <button onclick="exportSubs()">导出订阅列表 (.txt)</button>
    <button onclick="clearSubs()">清空订阅列表</button>
    <button onclick="clearAll()">清空全部</button>
    <button onclick="loadBuiltin(false)">重新载入内置源</button>
  </div>
</div>
<div id="aboutMask" class="mask" style="display:none" onclick="if(event.target===this) hideAbout()">
  <div class="modal">
    <h2>关于 免费节点搜索器</h2>
    <pre id="aboutText"></pre>
    <div style="text-align:right"><button onclick="hideAbout()">关闭</button></div>
  </div>
</div>
<div id="status">正在初始化…</div>

<script>
const $ = id => document.getElementById(id);
let results = [], sel = -1, builtin = [], busy = false;

async function api(path, body) {
  const r = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'},
                              body: JSON.stringify(body || {})});
  return r.json();
}
function log(s) { $('log').textContent += s + '\n'; $('log').scrollTop = $('log').scrollHeight; }
function status(s) { $('status').textContent = s; }
function engine() { return document.querySelector('input[name=engine]:checked').value; }
function allSubs() { return Array.from($('subs').options).map(o => o.value); }
function selectedSubs() { return Array.from($('subs').selectedOptions).map(o => o.value); }
function addSubs(list, tag) {
  const exist = new Set(allSubs()); let n = 0;
  list.forEach(u => {
    if (!u || exist.has(u)) return;
    const o = document.createElement('option');
    o.value = u; o.textContent = (tag || '') + u;
    $('subs').appendChild(o); exist.add(u); n++;
  });
  return n;
}
async function copyText(t) {
  if (!t) return alert('请先选中一条');
  try { await navigator.clipboard.writeText(t); status('已复制：' + t); }
  catch (e) { window.prompt('手动复制：', t); }
}
function renderResults() {
  const tb = $('rtbody'); tb.innerHTML = '';
  results.forEach((r, i) => {
    const tr = document.createElement('tr');
    if (i === sel) tr.className = 'sel';
    [r.title, r.info, r.desc, r.url].forEach(v => {
      const td = document.createElement('td');
      td.textContent = v || ''; td.title = v || ''; tr.appendChild(td);
    });
    tr.onclick = () => { sel = i; renderResults(); };
    tr.ondblclick = () => window.open(r.url, '_blank');
    tb.appendChild(tr);
  });
}
async function doSearch() {
  const keyword = $('kw').value.trim();
  if (!keyword) return alert('先输入关键词');
  $('btnSearch').disabled = true;
  const eng = engine();
  status('正在用 ' + (eng === 'github' ? 'GitHub' : 'Bing') + ' 搜索：' + keyword + ' …');
  log('—— 搜索（' + eng + '）：' + keyword);
  try {
    const d = await api('/api/search', {engine: eng, keyword: keyword, token: $('token').value.trim()});
    if (d.error) { log('搜索失败：' + d.error); status('搜索失败：' + d.error); }
    else { results = d.results; sel = -1; renderResults(); log(d.note); status(d.note); }
  } catch (e) { log('搜索失败：' + e); status('搜索失败'); }
  $('btnSearch').disabled = false;
}
function openSearchPage() {
  const q = encodeURIComponent($('kw').value.trim() || 'clash');
  window.open(engine() === 'github'
    ? 'https://github.com/search?q=' + q + '&type=repositories'
    : 'https://www.bing.com/search?q=' + q, '_blank');
}
function openResult() {
  if (sel < 0 || !results[sel]) return alert('先在搜索结果里选中一条');
  window.open(results[sel].url, '_blank');
}
function copyResult() {
  if (sel < 0 || !results[sel]) return alert('先在搜索结果里选中一条');
  copyText(results[sel].url);
}
async function doExtract() {
  if (sel < 0 || !results[sel]) return alert('先在搜索结果里选中一条');
  const r = results[sel];
  status('正在从 ' + r.title + ' 提取订阅链接…');
  log('—— 提取订阅：' + r.title);
  try {
    const d = await api('/api/extract', {result: r, token: $('token').value.trim()});
    if (d.error) { log('提取失败：' + d.error); status('提取失败'); return; }
    let n = 0;
    d.links.forEach(x => { n += addSubs([x.url], x.guess ? '（猜测）' : ''); });
    log('提取到 ' + d.links.length + ' 条候选，新增 ' + n + ' 条；带（猜测）的是文件名直链，检测通过才能用。');
    status('提取完成：新增 ' + n + ' 条，点「检测全部订阅」验证');
  } catch (e) { log('提取失败：' + e); status('提取失败'); }
}
function loadBuiltin(clear) {
  if (clear) $('subs').innerHTML = '';
  builtin.forEach(s => addSubs([s.url], '[内置] ' + s.name + '  '));
  log('已载入内置源（可用性会变化，请检测后再用）。');
}
function addCustom() {
  const v = $('custom').value.trim();
  if (!v) return;
  const n = addSubs([v], '');
  $('custom').value = '';
  log(n ? '已添加订阅：' + v : '该链接已在列表里');
}
function clearSubs() {
  $('subs').innerHTML = '';
  log('订阅列表已清空（可点「重新载入内置源」恢复）。');
}
function clearLog() {
  $('log').textContent = '';
  status('日志已清空。');
}
function clearResults() {
  results = []; sel = -1; renderResults();
  log('搜索结果已清空（订阅列表和日志保留）。');
  status('搜索结果已清空。');
}
function clearAll() {
  if (busy) return alert('正在检测中，请稍候');
  if (!window.confirm('将清空搜索结果、订阅列表和日志，确定继续？')) return;
  results = []; sel = -1; renderResults();
  $('subs').innerHTML = '';
  $('log').textContent = '';
  status('已清空全部（可点「重新载入内置源」恢复内置源）。');
}
function exportSubs() {
  const list = allSubs();
  if (!list.length) return alert('订阅列表是空的');
  const blob = new Blob([list.join('\n')], {type:'text/plain;charset=utf-8'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = '订阅链接列表.txt'; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  status('已导出 ' + list.length + ' 条');
}
async function checkUrls(urls) {
  if (!urls.length) return alert('先在订阅列表里选中一条');
  if (busy) return alert('正在检测中，请稍候');
  busy = true; let ok = 0;
  try {
    for (const url of urls) {
      status('检测中：' + url);
      try {
        const d = await api('/api/check', {urls: [url]});
        if (d.error) { log('❌ ' + url + '\n   ' + d.error); continue; }
        const it = d.items[0];
        if (it.ok) ok++;
        log((it.ok ? '✅ ' : '❌ ') + url + '\n   ' + it.msg);
      } catch (e) { log('❌ ' + url + '\n   请求失败：' + e); }
    }
    status('检测完成：' + ok + '/' + urls.length + ' 条可用');
  } finally { busy = false; }
}
function checkSel() { checkUrls(selectedSubs().slice(0, 1)); }
function checkAll() { checkUrls(allSubs()); }
function copySub() { copyText(selectedSubs()[0]); }

async function showAbout() {
  try {
    const d = await (await fetch('/api/about')).json();
    $('aboutText').textContent = d.text;
  } catch (e) { $('aboutText').textContent = 'Failed to load help: ' + e; }
  $('aboutMask').style.display = 'flex';
}
function hideAbout() { $('aboutMask').style.display = 'none'; }
document.addEventListener('keydown', e => { if (e.key === 'Escape') hideAbout(); });

async function init() {
  try {
    const c = await (await fetch('/api/config')).json();
    c.presets.forEach(p => {
      const o = document.createElement('option'); o.value = p; o.textContent = p;
      $('preset').appendChild(o);
    });
    $('preset').onchange = () => { $('kw').value = $('preset').value; };
    $('kw').value = c.presets[0] || '';
    builtin = c.sources;
    loadBuiltin(false);
    log('浏览器界面已就绪。内置源已载入，可直接点「检测全部订阅」。');
    status('就绪。选引擎 → 输关键词 → 开始搜索。');
  } catch (e) { log('初始化失败：' + e); status('初始化失败'); }
}
$('btnSearch').onclick = doSearch;
$('kw').onkeydown = e => { if (e.key === 'Enter') doSearch(); };
$('custom').onkeydown = e => { if (e.key === 'Enter') addCustom(); };
$('subs').ondblclick = () => checkUrls(selectedSubs().slice(0, 1));
init();
</script>
</body>
</html>
"""


class _WebHandler(http.server.BaseHTTPRequestHandler):
    """只监听 127.0.0.1 的最小后端，复用上面的搜索 / 提取 / 检测函数"""

    def log_message(self, fmt, *args):
        pass

    def _write(self, body, ctype="application/json; charset=utf-8", code=200):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _local_only(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            self.send_error(403)
            return False
        return True

    def do_GET(self):
        if not self._local_only():
            return
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._write(WEB_HTML, "text/html; charset=utf-8")
        elif path == "/api/config":
            self._write({
                "presets": PRESET_QUERIES,
                "sources": [{"name": n, "url": u} for n, u in BUILTIN_SOURCES],
            })
        elif path == "/api/about":
            self._write({"author": APP_AUTHOR, "version": APP_VERSION, "text": ABOUT_TEXT})
        else:
            self.send_error(404)

    def do_POST(self):
        if not self._local_only():
            return
        path = self.path.split("?", 1)[0]
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except Exception as e:
            self._write({"error": "请求解析失败：%s" % e})
            return
        try:
            if path == "/api/search":
                eng = payload.get("engine") or "github"
                keyword = (payload.get("keyword") or "").strip()
                token = payload.get("token") or ""
                if not keyword:
                    raise ValueError("关键词为空")
                if eng == "github":
                    rs, total = search_github(keyword, token=token)
                    out = {"results": rs,
                           "note": "共 %s 个仓库，显示前 %s 个（按最近更新排序）" % (total, len(rs))}
                else:
                    rs = search_bing(keyword)
                    out = {"results": rs, "note": "Bing 返回 %s 条网页结果" % len(rs)}
            elif path == "/api/extract":
                r = payload.get("result") or {}
                token = payload.get("token") or ""
                if r.get("full_name"):
                    links = extract_from_github_repo(r["full_name"],
                                                     r.get("default_branch") or "main", token=token)
                elif r.get("url"):
                    links = extract_from_webpage(r["url"])
                else:
                    raise ValueError("没有可抓取的链接")
                out = {"links": [{"url": x.split(" ")[0], "guess": "猜测" in x} for x in links]}
            elif path == "/api/check":
                items = []
                for u in (payload.get("urls") or [])[:100]:
                    good, msg = check_subscription(u)
                    items.append({"url": u, "ok": good, "msg": msg})
                out = {"items": items}
            else:
                self._write({"error": "未知接口"}, code=404)
                return
        except urllib.error.HTTPError as e:
            hint = "（GitHub 未登录限额约 10 次/分钟，稍等或填 Token）" if e.code == 403 else ""
            out = {"error": "HTTP %s %s" % (e.code, hint)}
        except Exception as e:
            out = {"error": "%s: %s" % (e.__class__.__name__, e)}
        self._write(out)


def run_web_ui(start_port=8765):
    """tkinter 不可用时启动本地网页服务，并自动打开浏览器"""
    import http.server

    class _Server(http.server.ThreadingHTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    server = None
    for port in range(start_port, start_port + 20):
        try:
            server = _Server(("127.0.0.1", port), _WebHandler)
            break
        except OSError:
            continue
    if server is None:
        print("ERROR: ports 8765-8784 are all in use. Close other programs and retry.")
        return

    url = "http://127.0.0.1:%d/" % port
    print("=" * 66)
    print("No tkinter available (or desktop window failed); starting browser UI instead.")
    print("Open this URL in your browser: " + url)
    print("Same features as the desktop UI. Press Ctrl+C or close this window to quit.")
    print("=" * 66, flush=True)
    opener = threading.Timer(0.6, lambda: webbrowser.open(url))
    opener.daemon = True
    opener.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


def _candidate_pythons():
    """收集本机可能的其它 Python 解释器（排除当前这个）"""
    import glob
    import os
    import subprocess

    found = []
    # PATH 上的解释器优先（通常是用户主动装的最新版）
    for d in (os.environ.get("PATH") or "").split(os.pathsep):
        p = os.path.join(d, "python.exe")
        if os.path.isfile(p):
            found.append(p)
    patterns = [
        r"D:\Python\python.exe",
        r"C:\Python*\python.exe",
        r"C:\Program Files\Python*\python.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python*\python.exe"),
    ]
    for pat in patterns:
        try:
            found.extend(glob.glob(pat))
        except Exception:
            pass
    # 最后再用 py 启动器登记的版本兜底
    try:
        out = subprocess.run(["py", "-0p"], capture_output=True, text=True,
                             timeout=6).stdout or ""
        for line in out.splitlines():
            m = re.search(r"[A-Za-z]:\\.*?python\.exe", line, re.I)
            if m:
                found.append(m.group(0))
    except Exception:
        pass

    cur = os.path.normcase(os.path.abspath(sys.executable))
    out, seen = [], set()
    for p in found:
        try:
            ap = os.path.normcase(os.path.abspath(p))
            if not os.path.isfile(p) or ap == cur or ap in seen:
                continue
            seen.add(ap)
            out.append(p)
        except Exception:
            continue
    return out


def _relaunch_with_tk():
    """当前 Python 无 tkinter 时，用另一个带 tkinter 的 Python 重启桌面版"""
    import os
    import subprocess

    if os.environ.get("NODE_SEARCHER_RELAUNCH") == "1":
        return False
    # PyInstaller 打包版没有可复用的 .py 入口，且 tkinter 已随包打进去；
    # 这里若 HAS_TK=False 说明打包时缺 Tk，直接交给浏览器界面兜底即可。
    if getattr(sys, "frozen", False):
        return False
    for exe in _candidate_pythons():
        try:
            r = subprocess.run([exe, "-c", "import tkinter"], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=10)
            if r.returncode != 0:
                continue
        except Exception:
            continue
        print("Found a tkinter-capable Python: %s - restarting desktop window..." % exe,
              flush=True)
        env = dict(os.environ)
        env["NODE_SEARCHER_RELAUNCH"] = "1"   # 防止无限重启
        try:
            return subprocess.call([exe, os.path.abspath(__file__)], env=env) == 0
        except Exception as e:
            print("Restart failed: %s" % e)
            return False
    return False


def main():
    if not HAS_TK:
        if _relaunch_with_tk():
            return
        print("No Python with tkinter found; starting browser UI instead.")
        run_web_ui()
        return
    try:
        app = App()
    except Exception as e:
        print("Desktop GUI failed to start (%s: %s); starting browser UI instead."
              % (e.__class__.__name__, e))
        traceback.print_exc()
        run_web_ui()
        return
    try:
        app.mainloop()
    except Exception:
        print("Desktop GUI crashed; starting browser UI instead.")
        traceback.print_exc()
        try:
            app.destroy()
        except Exception:
            pass
        run_web_ui()


if __name__ == "__main__":
    main()
