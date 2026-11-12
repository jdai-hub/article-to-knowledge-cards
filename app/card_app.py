#!/usr/bin/env python3
"""Article to Knowledge Cards — a small macOS GUI wrapper.

Paste an article, click one button, and this app asks the local `opencode`
CLI to turn it into knowledge cards and PNG files using the skill in
`skills/make-knowledge-cards`.

The app is intentionally thin: all card logic lives in the skill. This file
only collects input, runs the agent, and surfaces the result.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:  # pragma: no cover - depends on the Python build
    print(
        "This app needs a Python build with tkinter.\n"
        "Run it with: uv run --python 3.15 --no-project python card_app.py",
        file=sys.stderr,
    )
    raise SystemExit(2)


APP_NAME = "文章转卡片"
USER_CONFIG = Path.home() / "Library/Application Support/Make Knowledge Cards/config.json"
FALLBACK_PROJECT = Path.home() / "Downloads" / "first_skill"

BG = "#F3F0E8"
CARD = "#FFFFFF"
INK = "#1F2933"
MUTED = "#667085"
ACCENT = "#0F766E"
ACCENT_DARK = "#0B5F58"
BORDER = "#E4E7EB"
DANGER = "#B42318"

UI_FONT = "PingFang SC"
MONO_FONT = "Menlo"

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*(?:\x07|\x1b\\)")
RESULT_RE = re.compile(r"RESULT_DIR\s*=\s*[`'\"]?([^\s`'\"]+)[`'\"]?")


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def load_config() -> dict:
    config = {"project_dir": str(FALLBACK_PROJECT)}
    bundle_config = Path(__file__).resolve().parent / "config.json"
    for path in (bundle_config, USER_CONFIG):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            config.update(data)
    return config


def save_config(config: dict) -> None:
    USER_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    USER_CONFIG.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def subprocess_env() -> dict:
    env = os.environ.copy()
    extra = [
        str(Path.home() / ".local/bin"),
        str(Path.home() / ".opencode/bin"),
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ]
    current = env.get("PATH", "")
    parts = [p for p in extra if p]
    for p in current.split(":"):
        if p and p not in parts:
            parts.append(p)
    env["PATH"] = ":".join(parts)
    env.setdefault("LANG", "en_US.UTF-8")
    return env


def build_prompt(project: Path) -> str:
    skill = project / "skills/make-knowledge-cards/SKILL.md"
    renderer = project / "skills/make-knowledge-cards/scripts/render_cards.py"
    return f"""请读取附件 article.md，并严格按照 {skill} 的流程生成知识卡片并导出 PNG。

必须完成：
1. 提炼 5-8 张知识卡片；原文信息不足时按 SKILL.md 的规则减少数量，不要凑数。
2. 在回复中输出卡片 Markdown，格式遵循 SKILL.md 的卡片模板。
3. 按 SKILL.md 第 6 步选择权重最高的关键词作为目录名。
4. 把卡片 Markdown 写入系统临时目录中的临时文件，然后执行：
   uv run --with pillow python "{renderer}" --keyword "<关键词>" --output-root "{project}" --input "<临时文件>"
5. 渲染成功后删除临时文件。
6. 在回复的最后单独输出一行，不要加引号或代码块：
RESULT_DIR=<输出目录的绝对路径>
7. 不要修改项目中的其他文件，不要执行任何 git 命令。

项目根目录：{project}
"""


class CardApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.config_data = load_config()
        self.project_dir = Path(self.config_data["project_dir"]).expanduser()
        self.running = False
        self.proc: subprocess.Popen | None = None
        self.cancelled = False
        self.started_at = 0.0
        self.output_dir: Path | None = None

        self.title(APP_NAME)
        self.configure(bg=BG)
        self.geometry("880x760")
        self.minsize(640, 520)

        self._build_ui()
        self._center()
        self._bring_to_front()

    # ---------- UI ----------

    def _build_ui(self) -> None:
        outer = tk.Frame(self, bg=BG, padx=28, pady=22)
        outer.pack(fill="both", expand=True)

        header = tk.Frame(outer, bg=BG)
        header.pack(fill="x")
        tk.Label(
            header,
            text="文章转知识卡片",
            bg=BG,
            fg=INK,
            font=(UI_FONT, 24, "bold"),
            anchor="w",
        ).pack(side="left")
        tk.Label(
            header,
            text="粘贴文章 → 一键生成卡片和 PNG",
            bg=BG,
            fg=MUTED,
            font=(UI_FONT, 12),
            anchor="w",
        ).pack(side="left", padx=(14, 0), pady=(8, 0))

        project_row = tk.Frame(outer, bg=BG)
        project_row.pack(fill="x", pady=(10, 0))
        tk.Label(
            project_row,
            text="项目目录",
            bg=BG,
            fg=MUTED,
            font=(UI_FONT, 11),
        ).pack(side="left")
        self.project_label = tk.Label(
            project_row,
            text=str(self.project_dir),
            bg=BG,
            fg=MUTED,
            font=(MONO_FONT, 10),
            anchor="w",
        )
        self.project_label.pack(side="left", padx=(8, 0), fill="x", expand=True)
        tk.Button(
            project_row,
            text="更改",
            command=self._choose_project,
            font=(UI_FONT, 10),
            bg=BG,
            fg=ACCENT,
            activebackground=BG,
            activeforeground=ACCENT_DARK,
            relief="flat",
            bd=0,
            cursor="pointinghand",
        ).pack(side="right")

        hint = tk.Label(
            outer,
            text="把文章粘贴到下面（⌘V），然后点击「一键生成卡片」",
            bg=BG,
            fg=MUTED,
            font=(UI_FONT, 11),
            anchor="w",
        )
        hint.pack(fill="x", pady=(16, 6))

        text_frame = tk.Frame(
            outer,
            bg=CARD,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        text_frame.pack(fill="both", expand=True)
        self.text = tk.Text(
            text_frame,
            wrap="word",
            undo=True,
            bg=CARD,
            fg=INK,
            insertbackground=INK,
            selectbackground="#CDE7E2",
            font=(UI_FONT, 15),
            padx=16,
            pady=14,
            relief="flat",
            bd=0,
            highlightthickness=0,
        )
        scroll = ttk.Scrollbar(text_frame, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.text.focus_set()
        self.text.bind("<Command-Return>", lambda _e: self.start())

        actions = tk.Frame(outer, bg=BG)
        actions.pack(fill="x", pady=(16, 0))

        self.btn_generate = tk.Button(
            actions,
            text="一键生成卡片",
            command=self.start,
            font=(UI_FONT, 14, "bold"),
            bg=ACCENT,
            fg="white",
            activebackground=ACCENT_DARK,
            activeforeground="white",
            relief="flat",
            bd=0,
            padx=26,
            pady=10,
            cursor="pointinghand",
        )
        self.btn_generate.pack(side="left")

        self.btn_cancel = tk.Button(
            actions,
            text="取消",
            command=self.cancel,
            font=(UI_FONT, 12),
            bg="#E7E2D6",
            fg=INK,
            activebackground="#DAD3C3",
            relief="flat",
            bd=0,
            padx=16,
            pady=10,
            cursor="pointinghand",
        )

        tk.Button(
            actions,
            text="粘贴",
            command=self.paste,
            font=(UI_FONT, 12),
            bg=BG,
            fg=ACCENT,
            activebackground=BG,
            activeforeground=ACCENT_DARK,
            relief="flat",
            bd=0,
            padx=12,
            pady=10,
            cursor="pointinghand",
        ).pack(side="left", padx=(10, 0))

        tk.Button(
            actions,
            text="清空",
            command=self.clear,
            font=(UI_FONT, 12),
            bg=BG,
            fg=MUTED,
            activebackground=BG,
            activeforeground=INK,
            relief="flat",
            bd=0,
            padx=12,
            pady=10,
            cursor="pointinghand",
        ).pack(side="left")

        status_frame = tk.Frame(outer, bg=BG)
        status_frame.pack(fill="x", pady=(14, 0))
        self.status = tk.Label(
            status_frame,
            text="就绪",
            bg=BG,
            fg=MUTED,
            font=(UI_FONT, 11),
            anchor="w",
        )
        self.status.pack(side="left")
        self.progress = ttk.Progressbar(
            status_frame,
            mode="indeterminate",
            length=140,
        )

        self.result_frame = tk.Frame(outer, bg=BG)
        self.result_label = tk.Label(
            self.result_frame,
            text="",
            bg=BG,
            fg=ACCENT_DARK,
            font=(UI_FONT, 12),
            anchor="w",
            justify="left",
        )
        self.result_label.pack(side="left")
        self.btn_open = tk.Button(
            self.result_frame,
            text="在 Finder 中打开",
            command=self.open_output,
            font=(UI_FONT, 12, "bold"),
            bg="#E6F4F1",
            fg=ACCENT_DARK,
            activebackground="#D3EBE6",
            activeforeground=ACCENT_DARK,
            relief="flat",
            bd=0,
            padx=16,
            pady=8,
            cursor="pointinghand",
        )
        self.btn_open.pack(side="right")

        self.bind("<Command-q>", lambda _e: self.destroy())

    def _center(self) -> None:
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() - width) // 2
        y = max(0, (self.winfo_screenheight() - height) // 2 - 40)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _bring_to_front(self) -> None:
        self.lift()
        try:
            self.attributes("-topmost", True)
            self.after(400, lambda: self.attributes("-topmost", False))
        except tk.TclError:
            pass

    # ---------- actions ----------

    def _choose_project(self) -> None:
        chosen = filedialog.askdirectory(
            title="选择包含 skills/make-knowledge-cards 的项目目录",
            initialdir=str(self.project_dir),
        )
        if not chosen:
            return
        candidate = Path(chosen)
        if not (candidate / "skills/make-knowledge-cards/SKILL.md").exists():
            messagebox.showwarning(
                "目录不匹配",
                "这个目录里没有 skills/make-knowledge-cards/SKILL.md。\n"
                "请选择 first_skill 项目根目录。",
            )
            return
        self.project_dir = candidate
        self.config_data["project_dir"] = str(candidate)
        save_config(self.config_data)
        self.project_label.config(text=str(candidate))

    def paste(self) -> None:
        try:
            data = self.clipboard_get()
        except tk.TclError:
            return
        if data:
            self.text.insert("insert", data)

    def clear(self) -> None:
        if self.running:
            return
        self.text.delete("1.0", "end")
        self.result_frame.pack_forget()
        self.status.config(text="就绪", fg=MUTED)
        self.output_dir = None

    def open_output(self) -> None:
        if self.output_dir and self.output_dir.exists():
            subprocess.run(["open", str(self.output_dir)], check=False)

    # ---------- generation ----------

    def start(self) -> None:
        if self.running:
            return
        article = self.text.get("1.0", "end").strip()
        if not article:
            messagebox.showwarning("没有内容", "请先粘贴文章内容。")
            return
        if not (self.project_dir / "skills/make-knowledge-cards/SKILL.md").exists():
            messagebox.showerror(
                "项目目录无效",
                f"找不到 {self.project_dir}/skills/make-knowledge-cards/SKILL.md",
            )
            return

        self.running = True
        self.cancelled = False
        self.started_at = time.time()
        self.output_dir = None
        self.result_frame.pack_forget()
        self.btn_generate.config(state="disabled", text="正在生成…")
        self.btn_cancel.pack(side="left", padx=(10, 0))
        self.progress.pack(side="right")
        self.progress.start(12)
        self.status.config(text="正在调用模型生成卡片… 0s", fg=ACCENT_DARK)
        self._tick()

        threading.Thread(target=self._worker, args=(article,), daemon=True).start()

    def _tick(self) -> None:
        if not self.running:
            return
        elapsed = int(time.time() - self.started_at)
        self.status.config(text=f"正在调用模型生成卡片… {elapsed}s")
        self.after(500, self._tick)

    def _snapshot_dirs(self) -> set[str]:
        try:
            return {
                p.name
                for p in self.project_dir.iterdir()
                if p.is_dir() and not p.name.startswith(".")
            }
        except OSError:
            return set()

    def _worker(self, article: str) -> None:
        tmpdir = Path(tempfile.mkdtemp(prefix="mkc-"))
        article_path = tmpdir / "article.md"
        article_path.write_text(article, encoding="utf-8")
        before = self._snapshot_dirs()

        prompt = build_prompt(self.project_dir)
        cmd = [
            "opencode",
            "run",
            "--auto",
            "--title",
            f"知识卡片 {datetime.datetime.now():%Y-%m-%d %H:%M}",
            "--file",
            str(article_path),
            prompt,
        ]

        output = ""
        error = ""
        try:
            self.proc = subprocess.Popen(
                cmd,
                cwd=str(self.project_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=subprocess_env(),
                start_new_session=True,
            )
            try:
                output, _ = self.proc.communicate(timeout=900)
            except subprocess.TimeoutExpired:
                self._kill_proc()
                error = "生成超时（15 分钟），已终止。"
        except FileNotFoundError:
            error = "找不到 opencode 命令。请确认已安装并登录 OpenCode CLI。"
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            error = f"{type(exc).__name__}: {exc}"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
            self.proc = None

        output = strip_ansi(output or "")
        result_dir = self._parse_result_dir(output)
        if result_dir is None and not error:
            result_dir = self._detect_new_dir(before)
        if error and not result_dir:
            self.after(0, self._finish_error, error, output)
            return
        if result_dir is None:
            self.after(
                0,
                self._finish_error,
                "模型已返回，但没有找到输出目录。",
                output,
            )
            return
        count = len(list(result_dir.glob("card-*.png")))
        self.after(0, self._finish_ok, result_dir, count, output)

    def _kill_proc(self) -> None:
        proc = self.proc
        if proc is None:
            return
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            try:
                proc.terminate()
            except OSError:
                pass

    def _parse_result_dir(self, output: str) -> Path | None:
        matches = RESULT_RE.findall(output)
        for raw in reversed(matches):
            candidate = Path(raw).expanduser()
            if candidate.is_dir():
                return candidate
        return None

    def _detect_new_dir(self, before: set[str]) -> Path | None:
        after = self._snapshot_dirs()
        new_names = after - before
        candidates: list[Path] = []
        for name in new_names:
            path = self.project_dir / name
            if list(path.glob("card-*.png")):
                candidates.append(path)
        if not candidates:
            return None
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return candidates[0]

    def _finish_ok(self, result_dir: Path, count: int, output: str) -> None:
        self._reset_running()
        self.output_dir = result_dir
        if count:
            text = f"完成：{count} 张卡片\n{result_dir}"
        else:
            text = f"完成，但没有找到 PNG。\n{result_dir}"
        self.result_label.config(text=text)
        self.result_frame.pack(fill="x", pady=(12, 0))
        self.status.config(text=f"完成，用时 {int(time.time() - self.started_at)}s", fg=ACCENT_DARK)

    def _finish_error(self, message: str, output: str) -> None:
        self._reset_running()
        self.status.config(text="生成失败", fg=DANGER)
        tail = "\n".join(output.strip().splitlines()[-12:])
        detail = f"{message}\n\n{tail}" if tail else message
        messagebox.showerror("生成失败", detail[:2000])

    def _reset_running(self) -> None:
        self.running = False
        self.progress.stop()
        self.progress.pack_forget()
        self.btn_cancel.pack_forget()
        self.btn_generate.config(state="normal", text="一键生成卡片")

    def cancel(self) -> None:
        if not self.running:
            return
        self.cancelled = True
        self.status.config(text="正在取消…", fg=MUTED)
        self._kill_proc()


def main() -> int:
    app = CardApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
