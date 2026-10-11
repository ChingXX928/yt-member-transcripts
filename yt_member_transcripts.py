#!/usr/bin/env python3
"""
YouTube 會員片字幕 → Markdown / TXT / JSON。

餵 NotebookLM 或其他 AI：上傳 out/md/ 入面逐個 .md。
JSON 會把鍵名都算進字數，一條片一個 Markdown 更穩。

例子：
  .\\.venv\\Scripts\\python.exe yt_member_transcripts.py --self-test
  .\\.venv\\Scripts\\python.exe yt_member_transcripts.py --members-of UCxxxx --dry-run
  .\\.venv\\Scripts\\python.exe yt_member_transcripts.py "播放清單URL" --limit 2
  .\\.venv\\Scripts\\python.exe yt_member_transcripts.py "播放清單URL" --out .\\laoyu_txt
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path


PAUSE_MS = 1600
MAX_CUE_SPAN_MS = 15000
MIN_TRANSCRIPT_CHARS = 5

SUB_EXTS = {".json3", ".vtt", ".srt", ".ttml"}
FORMAT_RANK = {".json3": 0, ".vtt": 1, ".srt": 2, ".ttml": 3}
MEMBERS_PREFIX = {
    "all": "UUMO",
    "videos": "UUMF",
    "shorts": "UUMS",
    "live": "UUMV",
}
NOISE_WORDS = {
    "music",
    "applause",
    "laughter",
    "cheering",
    "silence",
    "singing",
    "音樂",
    "掌聲",
    "笑聲",
    "鼓掌",
    "背景音樂",
    "背景音乐",
    "音樂播放",
}
TAG_RE = re.compile(r"<[^>]+>")
TS_RE = re.compile(r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})[.,](\d{3})")
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
SINGLE_VIDEO_RE = re.compile(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})")

COOKIE_HINT = (
    "登入提示：Windows 上 Chrome 經常因為 app-bound encryption 讀唔到 cookie。\n"
    "改試 --browser firefox 或 --browser edge。\n"
    "或者開一個無痕視窗登入 YouTube，去 https://www.youtube.com/robots.txt ，\n"
    "用擴充功能匯出 Netscape 格式 cookies.txt，再加 --cookies cookies.txt。\n"
    "匯出後關掉個無痕視窗，唔好再喺瀏覽器開 YouTube，否則 cookie 會被輪換。\n"
    "帳號一定要已經加入咗該頻道會員。"
)
JS_HINT = (
    "yt-dlp 提示未找到 JavaScript runtime。字幕多數仍可下載。\n"
    "如果之後抽取失敗，先升級 yt-dlp，或者按佢嘅說明裝 deno：\n"
    "https://github.com/yt-dlp/yt-dlp/wiki/EJS"
)


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def child_env() -> dict[str, str]:
    env = dict(**{k: v for k, v in __import__("os").environ.items()})
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def is_cjk_char(ch: str) -> bool:
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0xF900 <= code <= 0xFAFF
    )


def contains_cjk(text: str) -> bool:
    return any(is_cjk_char(ch) for ch in text)


def is_nonverbal(text: str) -> bool:
    token = text.strip().lower()
    token = token.strip("[]【】()（）♪♫♬ ")
    token = re.sub(r"\s+", "", token)
    if not token:
        return True
    return token in NOISE_WORDS


def clean_inline_keep_space(text: str) -> str:
    text = html.unescape(text)
    text = TAG_RE.sub("", text)
    return text.replace("\u200b", "").replace("\ufeff", "").replace("\xa0", " ")


def normalize_cue(text: str) -> str:
    text = clean_inline_keep_space(text).replace("\n", " ")
    return re.sub(r"[ \t]+", " ", text).strip()


def append_text(buf: str, text: str) -> str:
    if not buf:
        return text
    if not text:
        return buf
    if buf[-1].isspace() or text[0].isspace():
        return buf + text
    if text[0] in "。！？!?…，,、；;：:」』）)]}":
        return buf + text
    if buf[-1] in "「『（([{":
        return buf + text
    left_cjk = is_cjk_char(buf[-1])
    right_cjk = is_cjk_char(text[0])
    if left_cjk and right_cjk:
        return buf + text
    if buf[-1] in "。！？!?…，,、；;：:" and right_cjk:
        return buf + text
    return buf + " " + text


def unwrap_caption_breaks(text: str) -> str:
    """json3 的單行換行是字幕換行，不是新的一句。人手字幕的換行要保留。"""

    def unwrap(match: re.Match[str]) -> str:
        left, right = match.group(1), match.group(2)
        if is_cjk_char(left) and is_cjk_char(right):
            return left + right
        return left + " " + right

    for _ in range(20):
        updated = re.sub(r"(\S)\n(?!\n)(\S)", unwrap, text)
        if updated == text:
            break
        text = updated
    return text


def tidy_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(
        r"\[(?:music|applause|laughter|cheering|singing|音樂|掌聲|笑聲|鼓掌)\]",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" +([。！？，、；：])", r"\1", text)
    return text.strip()


def json3_to_text(data: dict) -> str:
    """YouTube json3 自動字幕係逐段新字，唔係 VTT 那種滾動重複。"""
    buf = ""
    prev_end: int | None = None
    for event in data.get("events") or []:
        if not isinstance(event, dict):
            continue
        segs = event.get("segs")
        if not segs:
            continue
        parts = []
        for seg in segs:
            if isinstance(seg, dict):
                parts.append(str(seg.get("utf8", "")))
        text = clean_inline_keep_space("".join(parts))
        if text.strip() == "":
            if "\n" in text:
                buf += "\n"
            continue
        start = int(event.get("tStartMs") or 0)
        duration = event.get("dDurationMs")
        end = start + min(int(duration), MAX_CUE_SPAN_MS) if duration else start
        if is_nonverbal(text):
            prev_end = end if prev_end is None else max(prev_end, end)
            continue
        if prev_end is not None and start - prev_end >= PAUSE_MS and buf.strip():
            buf = buf.rstrip() + "\n\n"
        buf = append_text(buf, text)
        prev_end = end if prev_end is None else max(prev_end, end)
    return tidy_text(unwrap_caption_breaks(buf))


def parse_ts(value: str) -> int | None:
    match = TS_RE.search(value)
    if not match:
        return None
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    millis = int(match.group(4))
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis


def parse_vtt_srt(raw: str) -> list[tuple[int, int, str]]:
    raw = raw.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    cues: list[tuple[int, int, str]] = []
    for block in re.split(r"\n\s*\n", raw):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        timing_at = None
        start = end = None
        for index, line in enumerate(lines):
            if "-->" not in line:
                continue
            timing_at = index
            left, right = line.split("-->", 1)
            start = parse_ts(left)
            end = parse_ts(right)
            break
        if timing_at is None or start is None:
            continue
        text = normalize_cue(" ".join(lines[timing_at + 1 :]))
        if not text or is_nonverbal(text):
            continue
        cues.append((start, end if end is not None else start, text))
    return cues


def overlap_k(acc: str, text: str) -> int:
    if not acc or not text:
        return 0
    folded_acc = acc.casefold()
    folded_text = text.casefold()
    if len(folded_acc) != len(acc) or len(folded_text) != len(text):
        folded_acc, folded_text = acc, text
    limit = min(len(folded_acc), len(folded_text))
    for size in range(limit, 0, -1):
        if folded_acc.endswith(folded_text[:size]):
            return size
    return 0


def detect_rolling(cues: list[tuple[int, int, str]]) -> bool:
    if len(cues) < 4:
        return False
    hits = 0
    for (_, _, left), (_, _, right) in zip(cues, cues[1:]):
        if overlap_k(left, right) >= 2:
            hits += 1
    return hits / (len(cues) - 1) >= 0.3


def render_rolling(cues: list[tuple[int, int, str]]) -> str:
    acc = ""
    blocks: list[str] = []
    current = ""
    prev_end: int | None = None

    def push() -> None:
        nonlocal current
        if current.strip():
            blocks.append(current.strip())
        current = ""

    for start, end, text in cues:
        gap = 0 if prev_end is None else start - prev_end
        if not acc:
            acc = text
            current = text
            prev_end = end
            continue
        size = overlap_k(acc, text)
        min_size = 1 if (contains_cjk(text) or contains_cjk(acc[-40:])) else 4
        if size >= len(text) and size > 0:
            prev_end = max(prev_end or 0, end)
            continue
        tail = acc[-(len(text) + 20) :]
        if size == 0 and len(text) >= 8 and text.casefold() in tail.casefold():
            prev_end = max(prev_end or 0, end)
            continue
        piece = text[size:] if size > 0 else text
        if not piece.strip():
            prev_end = max(prev_end or 0, end)
            continue
        if size >= min_size:
            current = append_text(current, piece)
            acc = append_text(acc, piece)
        else:
            if current and gap >= PAUSE_MS:
                push()
                current = piece.strip()
            elif current:
                current = current.rstrip() + "\n" + piece.strip()
            else:
                current = piece.strip()
            acc = append_text(acc, piece)
        prev_end = max(prev_end or 0, end)
    push()
    return "\n\n".join(blocks)


def render_manual(cues: list[tuple[int, int, str]]) -> str:
    paragraphs: list[list[str]] = [[]]
    prev_end: int | None = None
    for start, end, text in cues:
        silence = 0 if prev_end is None else start - prev_end
        if paragraphs[-1] and silence >= PAUSE_MS:
            paragraphs.append([])
        bucket = paragraphs[-1]
        if bucket and text == bucket[-1]:
            prev_end = max(prev_end or 0, end)
            continue
        if bucket and text.startswith(bucket[-1]) and len(text) > len(bucket[-1]):
            bucket[-1] = text
        elif bucket and overlap_k(bucket[-1], text) >= 6:
            extra = text[overlap_k(bucket[-1], text) :].strip()
            if extra:
                bucket[-1] = append_text(bucket[-1], extra)
        else:
            bucket.append(text)
        prev_end = end if prev_end is None else max(prev_end, end)
    rendered = []
    for bucket in paragraphs:
        lines = [line.strip() for line in bucket if line.strip()]
        if lines:
            rendered.append("\n".join(lines))
    return "\n\n".join(rendered)


def render_cues(cues: list[tuple[int, int, str]]) -> str:
    if not cues:
        return ""
    if detect_rolling(cues):
        return tidy_text(render_rolling(cues))
    return tidy_text(render_manual(cues))


def clean_raw(raw: str, suffix: str) -> str:
    stripped = raw.lstrip("\ufeff")
    if suffix.lower() == ".json3" or stripped.lstrip().startswith("{"):
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict) and "events" in data:
            return json3_to_text(data)
    return render_cues(parse_vtt_srt(stripped))


def is_subtitle_file(path: Path, video_id: str) -> bool:
    name = path.name
    if not name.startswith(video_id + "."):
        return False
    if name.endswith(".info.json"):
        return False
    return path.suffix.lower() in SUB_EXTS


def parse_lang_ext(path: Path, video_id: str) -> tuple[str, str]:
    ext = path.suffix.lower()
    rest = path.name[len(video_id) + 1 :]
    if ext and rest.endswith(ext):
        lang = rest[: -len(ext)].strip(".")
    else:
        lang = rest
    return lang, ext


def base_lang(lang: str) -> str:
    if lang.lower().endswith("-orig"):
        return lang[: -len("-orig")]
    return lang


def is_translation_track(lang: str) -> bool:
    if lang.lower().endswith("-orig"):
        return False
    parts = lang.split("-")
    if len(parts) >= 3 and parts[-1].lower() not in {"hant", "hans", "orig", "hk", "tw", "cn"}:
        return True
    return False


def lang_index(lang: str, preferred: str) -> int:
    base = base_lang(lang).lower()
    order: list[str] = []
    for item in (
        preferred,
        "zh-Hant",
        "zh-HK",
        "zh-TW",
        "yue",
        "yue-HK",
        "zh-Hans",
        "zh-CN",
        "zh",
        "en",
        "en-US",
        "en-GB",
    ):
        if item and item.lower() not in order:
            order.append(item.lower())
    if base in order:
        return order.index(base)
    for index, item in enumerate(order):
        if base.startswith(item):
            return 20 + index
    if base.startswith("zh") or base.startswith("yue"):
        return 40
    if base.startswith("en"):
        return 50
    return 80


def score_subtitle(path: Path, video_id: str, preferred: str) -> tuple:
    lang, ext = parse_lang_ext(path, video_id)
    return (
        1 if is_translation_track(lang) else 0,
        lang_index(lang, preferred),
        FORMAT_RANK.get(ext, 9),
        1 if lang.lower().endswith("-orig") else 0,
        path.name,
    )


def choose_subtitle(
    directory: Path,
    video_id: str,
    preferred: str,
    *,
    fallback: bool = True,
) -> Path | None:
    files = [path for path in directory.glob(f"{video_id}.*") if is_subtitle_file(path, video_id)]
    ranked = sorted(files, key=lambda path: score_subtitle(path, video_id, preferred))
    if not fallback:
        ranked = [
            path
            for path in ranked
            if lang_index(parse_lang_ext(path, video_id)[0], preferred) == 0
        ]
    return ranked[0] if ranked else None


def subtitle_kind(info: dict, lang: str) -> str:
    if lang.lower().endswith("-orig"):
        return "auto"
    subs = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    base = base_lang(lang)
    if lang in subs or base in subs:
        return "manual"
    if lang in auto or base in auto:
        return "auto"
    saved = info.get("subtitle_kind")
    if saved in {"manual", "auto"}:
        return saved
    return "unknown"


def members_playlist_url(channel_id: str, kind: str = "all") -> str:
    channel_id = channel_id.strip()
    if not CHANNEL_ID_RE.fullmatch(channel_id):
        raise ValueError(f"唔係 channel id（應為 UC 加 22 個字）：{channel_id}")
    try:
        prefix = MEMBERS_PREFIX[kind]
    except KeyError as exc:
        raise ValueError(f"未知會員清單類型：{kind}") from exc
    return f"https://www.youtube.com/playlist?list={prefix}{channel_id[2:]}"


def channel_id_from_info(info: dict) -> str | None:
    for key in ("channel_id", "uploader_id"):
        value = info.get(key) or ""
        if isinstance(value, str) and CHANNEL_ID_RE.fullmatch(value):
            return value
    value = info.get("id") or ""
    if isinstance(value, str) and CHANNEL_ID_RE.fullmatch(value):
        return value
    if isinstance(value, str) and value.startswith("UU") and len(value) == 24:
        candidate = "UC" + value[2:]
        if CHANNEL_ID_RE.fullmatch(candidate):
            return candidate
    for entry in info.get("entries") or []:
        if isinstance(entry, dict):
            found = channel_id_from_info(entry)
            if found:
                return found
    return None


def one_line(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def fmt_date(upload_date: str | None) -> str:
    if not upload_date or len(upload_date) != 8 or not upload_date.isdigit():
        return upload_date or ""
    return f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"


def fmt_duration(seconds: int | float | None) -> str:
    if not seconds:
        return ""
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def render_md(meta: dict) -> str:
    title = one_line(meta.get("title") or meta["id"])
    kind = {"manual": "人手", "auto": "自動", "unknown": "未知"}.get(
        meta.get("subtitle_kind") or "", "未知"
    )
    rows = []
    if meta.get("channel"):
        rows.append(f"- 頻道：{one_line(meta['channel'])}")
    if meta.get("date"):
        rows.append(f"- 日期：{meta['date']}")
    duration = fmt_duration(meta.get("duration"))
    if duration:
        rows.append(f"- 片長：{duration}")
    rows.append(f"- 連結：{meta.get('url') or watch_url(meta['id'])}")
    rows.append(f"- 字幕：{meta.get('language') or '?'}（{kind}）")
    body = (meta.get("transcript") or "").strip()
    return f"# {title}\n\n" + "\n".join(rows) + "\n\n" + body + "\n"


def render_txt(meta: dict) -> str:
    title = one_line(meta.get("title") or meta["id"])
    url = meta.get("url") or watch_url(meta["id"])
    body = (meta.get("transcript") or "").strip()
    return f"{title}\n{url}\n\n{body}\n"


def md_cell(text: str) -> str:
    return one_line(text).replace("|", "\\|")


def ytdlp_cmd() -> list[str]:
    found = shutil.which("yt-dlp")
    if found:
        return [found]
    return [sys.executable, "-m", "yt_dlp"]


def ensure_ytdlp() -> list[str]:
    command = ytdlp_cmd()
    probe = subprocess.run(
        command + ["--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=child_env(),
    )
    if probe.returncode != 0:
        print("未找到 yt-dlp。先喺呢個資料夾執行：", file=sys.stderr)
        print(r"  .\.venv\Scripts\python.exe -m pip install -U -r requirements.txt", file=sys.stderr)
        raise SystemExit(2)
    print(f"yt-dlp {probe.stdout.strip()}")
    return command


def auth_args(args: argparse.Namespace) -> list[str]:
    if args.no_cookies:
        return []
    if args.cookies:
        return ["--cookies", str(args.cookies)]
    spec = args.browser
    if args.browser_profile:
        spec = f"{args.browser}:{args.browser_profile}"
    return ["--cookies-from-browser", spec]


def base_cmd(ytdlp: list[str], args: argparse.Namespace) -> list[str]:
    return ytdlp + auth_args(args) + [
        "--ignore-errors",
        "--no-progress",
        "--retries",
        "10",
        "--fragment-retries",
        "10",
        "--extractor-retries",
        "3",
        "--retry-sleep",
        "http:exp=1:20",
        "--sleep-requests",
        "0.75",
        "--socket-timeout",
        "30",
    ]


def run_capture(command: list[str]) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(command), flush=True)
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=child_env(),
    )


def run_stream(command: list[str], log_path: Path) -> tuple[int, str]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print("+", " ".join(command), flush=True)
    proc = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=child_env(),
    )
    chunks: list[str] = []
    size = 0
    assert proc.stdout is not None
    with log_path.open("w", encoding="utf-8", newline="\n") as log:
        log.write("+ " + " ".join(command) + "\n")
        for line in proc.stdout:
            print(line, end="", flush=True)
            log.write(line)
            chunks.append(line)
            size += len(line)
            if size > 200_000:
                chunks = chunks[-30:]
                size = sum(len(item) for item in chunks)
    return proc.wait(), "".join(chunks)


def load_ytdlp_json(stdout: str) -> dict:
    start = stdout.find("{")
    end = stdout.rfind("}")
    if start == -1 or end <= start:
        raise RuntimeError("yt-dlp 冇返回 JSON")
    data = json.loads(stdout[start : end + 1])
    if not isinstance(data, dict):
        raise RuntimeError("yt-dlp JSON 唔係物件")
    return data


def is_single_video_url(url: str) -> bool:
    if "list=" in url:
        return False
    return SINGLE_VIDEO_RE.search(url) is not None


def video_id_from_url(url: str) -> str | None:
    match = SINGLE_VIDEO_RE.search(url)
    return match.group(1) if match else None


def walk_videos(node: dict) -> list[dict]:
    found: list[dict] = []

    def visit(item: dict) -> None:
        entries = item.get("entries")
        if entries:
            for entry in entries:
                if isinstance(entry, dict):
                    visit(entry)
            return
        found.append(item)

    visit(node)
    return found


def list_videos(url: str, ytdlp: list[str], args: argparse.Namespace) -> tuple[str, list[dict]]:
    if "/membership" in url or url.rstrip("/").endswith("/join"):
        print(
            "注意：會員專區頁而家通常只顯示最近幾條。"
            "要全套會員片，用 --members-of，或者播放清單 UUMO / UUMF。"
        )
    command = base_cmd(ytdlp, args) + ["--flat-playlist", "--dump-single-json"]
    if is_single_video_url(url) and not args.yes_playlist:
        command.append("--no-playlist")
    command.append(url)
    result = run_capture(command)
    hint_from_log(result.stderr or "")
    data = None
    if result.stdout and "{" in result.stdout:
        try:
            data = load_ytdlp_json(result.stdout)
        except (json.JSONDecodeError, RuntimeError):
            data = None
    if data is None:
        detail = (result.stderr or result.stdout or "yt-dlp 失敗")[-2000:]
        raise RuntimeError(detail)
    title = one_line(str(data.get("title") or ""))
    videos = []
    for entry in walk_videos(data):
        video_id = str(entry.get("id") or "")
        if not VIDEO_ID_RE.fullmatch(video_id):
            continue
        entry_title = one_line(str(entry.get("title") or ""))
        if entry_title in {"[Private video]", "[Deleted video]", "[Unavailable video]"}:
            print(f"跳過 {video_id}：{entry_title}")
            continue
        live_status = entry.get("live_status")
        if live_status in {"is_live", "is_upcoming"} or entry.get("is_live") is True:
            print(f"跳過 {video_id}：直播未完，完咗再跑")
            continue
        videos.append(
            {
                "id": video_id,
                "title": entry_title or video_id,
                "url": watch_url(video_id),
            }
        )
    if not videos and is_single_video_url(url):
        video_id = video_id_from_url(url)
        if video_id:
            videos.append({"id": video_id, "title": video_id, "url": watch_url(video_id)})
    return title, videos


def pick_subtitle_lang(info: dict, preferred: str, *, fallback: bool) -> str | None:
    """從已抽出的影片資料揀一種字幕。只會下載這一種，避免把翻譯軌全部抓下來。"""
    manual = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    languages = [lang for lang in list(manual) + list(auto) if isinstance(lang, str)]
    languages = list(dict.fromkeys(languages))
    if not languages:
        return None

    def score(lang: str) -> tuple:
        return (
            1 if is_translation_track(lang) else 0,
            lang_index(lang, preferred),
            0 if lang in manual else 1,
            1 if lang.lower().endswith("-orig") else 0,
            lang,
        )

    ranked = sorted(languages, key=score)
    if not fallback:
        ranked = [lang for lang in ranked if lang_index(lang, preferred) == 0]
        return ranked[0] if ranked else None
    best = ranked[0]
    if lang_index(best, preferred) >= 80:
        return None
    return best


def hint_from_log(text: str) -> None:
    lowered = text.lower()
    if any(token in lowered for token in ("cookie", "dpapi", "decrypt", "app-bound", "sign in", "members-only", "join this channel")):
        if not getattr(hint_from_log, "cookie_shown", False):
            print(COOKIE_HINT)
            hint_from_log.cookie_shown = True
    if "no supported javascript runtime" in lowered and not getattr(hint_from_log, "js_shown", False):
        print(JS_HINT)
        hint_from_log.js_shown = True


def auth_failure(text: str) -> bool:
    lowered = text.lower()
    return any(
        token in lowered
        for token in (
            "join this channel",
            "members-only",
            "sign in to confirm",
            "private video",
            "login required",
            "this video is available to this channel's members",
        )
    )


def no_subtitle_message(text: str) -> bool:
    lowered = text.lower()
    return "there are no subtitles" in lowered or "no subtitles" in lowered


class _YtdlpLog:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def debug(self, message: str) -> None:
        if str(message).startswith("[debug]"):
            return
        self._add(message)

    def info(self, message: str) -> None:
        self._add(message)

    def warning(self, message: str) -> None:
        self._add("WARNING: " + str(message))

    def error(self, message: str) -> None:
        self._add("ERROR: " + str(message))

    def _add(self, message: str) -> None:
        text = str(message)
        print(text, flush=True)
        self.lines.append(text)
        if len(self.lines) > 400:
            self.lines = self.lines[-400:]

    def text(self) -> str:
        return "\n".join(self.lines)


def ytdlp_library_options(raw_dir: Path, args: argparse.Namespace, logger: _YtdlpLog) -> dict:
    options: dict = {
        "skip_download": True,
        "outtmpl": str(raw_dir / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "ignoreerrors": False,
        "ignore_no_formats_error": True,
        "retries": 10,
        "fragment_retries": 10,
        "extractor_retries": 3,
        "socket_timeout": 30,
        "sleep_interval_requests": 0.75,
        "sleep_interval_subtitles": 1,
        "overwrites": False,
        "quiet": False,
        "noprogress": True,
        "writeinfojson": True,
        "logger": logger,
    }
    if not args.no_cookies:
        if args.cookies:
            options["cookiefile"] = str(args.cookies)
        else:
            options["cookiesfrombrowser"] = (args.browser, args.browser_profile, None, None)
    return options


def download_subtitles(
    video: dict,
    raw_dir: Path,
    ytdlp: list[str],
    args: argparse.Namespace,
    log_path: Path,
) -> tuple[dict, str]:
    import yt_dlp

    del ytdlp  # 單條片改用內建函式庫，先揀一種語言再下載
    raw_dir.mkdir(parents=True, exist_ok=True)
    logger = _YtdlpLog()
    info: dict = {}
    for attempt in range(1, 4):
        try:
            with yt_dlp.YoutubeDL(ytdlp_library_options(raw_dir, args, logger)) as ydl:
                extracted = ydl.extract_info(video["url"], download=False)
                if not isinstance(extracted, dict):
                    raise RuntimeError("抽取影片資料失敗")
                if extracted.get("entries"):
                    entries = [entry for entry in extracted["entries"] if isinstance(entry, dict)]
                    if entries:
                        extracted = entries[0]
                info = extracted
                lang = pick_subtitle_lang(info, args.lang, fallback=not args.no_fallback)
                if not lang:
                    logger._add("There are no subtitles for the requested languages")
                    break
                print(f"  字幕語言：{lang}", flush=True)
                ydl.params["writesubtitles"] = True
                ydl.params["writeautomaticsub"] = True
                ydl.params["subtitleslangs"] = [lang]
                ydl.params["subtitlesformat"] = "json3/vtt/srt/best"
                ydl.process_ie_result(info, download=True)
        except Exception as exc:
            logger.error(str(exc))
            if auth_failure(str(exc)):
                break
        log_text = logger.text()
        hint_from_log(log_text)
        if choose_subtitle(raw_dir, video["id"], args.lang, fallback=not args.no_fallback):
            read_info(raw_dir, video["id"])
            _write_log(log_path, log_text)
            return info, log_text
        if auth_failure(log_text) or no_subtitle_message(log_text):
            break
        if attempt < 3:
            wait = 8 * attempt
            print(f"  重試 {video['id']}（{attempt}/3），等 {wait} 秒", flush=True)
            time.sleep(wait)
    log_text = logger.text()
    hint_from_log(log_text)
    read_info(raw_dir, video["id"])
    _write_log(log_path, log_text)
    return info, log_text


def _write_log(log_path: Path, text: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(text + "\n", encoding="utf-8", newline="\n")


def read_info(raw_dir: Path, video_id: str) -> dict:
    path = raw_dir / f"{video_id}.info.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    try:
        path.unlink()
    except OSError:
        pass
    return data if isinstance(data, dict) else {}


def build_meta(video: dict, info: dict, subtitle: Path, transcript: str, index: int) -> dict:
    lang, _ext = parse_lang_ext(subtitle, video["id"])
    upload_date = str(info.get("upload_date") or "")
    duration = info.get("duration") or 0
    return {
        "id": video["id"],
        "title": one_line(str(info.get("title") or video.get("title") or video["id"])),
        "upload_date": upload_date,
        "date": fmt_date(upload_date),
        "url": watch_url(video["id"]),
        "channel": one_line(str(info.get("channel") or info.get("uploader") or "")),
        "channel_id": str(info.get("channel_id") or ""),
        "duration": int(duration) if duration else 0,
        "language": lang,
        "subtitle_kind": subtitle_kind(info, lang),
        "subtitle_file": subtitle.name,
        "playlist_index": index,
        "transcript": transcript,
    }


def write_video_outputs(out_dir: Path, meta: dict) -> None:
    video_id = meta["id"]
    (out_dir / "meta").mkdir(parents=True, exist_ok=True)
    (out_dir / "md").mkdir(parents=True, exist_ok=True)
    (out_dir / "txt").mkdir(parents=True, exist_ok=True)
    (out_dir / "meta" / f"{video_id}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (out_dir / "md" / f"{video_id}.md").write_text(render_md(meta), encoding="utf-8", newline="\n")
    (out_dir / "txt" / f"{video_id}.txt").write_text(render_txt(meta), encoding="utf-8", newline="\n")


def load_metas(out_dir: Path) -> list[dict]:
    metas = []
    meta_dir = out_dir / "meta"
    if not meta_dir.exists():
        return metas
    for path in meta_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("id") and data.get("transcript"):
            metas.append(data)
    metas.sort(key=lambda item: (int(item.get("playlist_index") or 10**9), item.get("upload_date") or "", item["id"]))
    return metas


def write_indexes(out_dir: Path, playlist_title: str = "") -> int:
    metas = load_metas(out_dir)
    jsonl_path = out_dir / "transcripts.jsonl"
    with jsonl_path.open("w", encoding="utf-8", newline="\n") as handle:
        for meta in metas:
            handle.write(json.dumps(meta, ensure_ascii=False) + "\n")
    all_path = out_dir / "all.json"
    all_path.write_text(
        json.dumps(metas, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    lines = ["# 字幕索引", ""]
    if playlist_title:
        lines.append(playlist_title)
        lines.append("")
    lines.append(f"共 {len(metas)} 條。餵 AI 請上傳 `md/` 入面逐個檔。")
    lines.append("")
    lines.append("| 序 | 日期 | 標題 |")
    lines.append("| --- | --- | --- |")
    for meta in metas:
        title = md_cell(meta.get("title") or meta["id"])
        lines.append(
            f"| {meta.get('playlist_index') or ''} | {meta.get('date') or ''} | [{title}](md/{meta['id']}.md) |"
        )
    lines.append("")
    (out_dir / "index.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")

    combined_parts = [
        "# 字幕合集",
        "",
        "餵 NotebookLM 或其他 AI 時，優先上傳 `md/` 入面逐個檔。",
        "一個來源大約 50 萬字，合集太大就會被拒。",
        "",
    ]
    total_chars = 0
    for meta in metas:
        combined_parts.append(render_md(meta).rstrip())
        combined_parts.append("\n---\n")
        total_chars += len(meta.get("transcript") or "")
    (out_dir / "combined.md").write_text("\n".join(combined_parts).rstrip() + "\n", encoding="utf-8", newline="\n")
    return total_chars


def meta_is_done(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return isinstance(data, dict) and len((data.get("transcript") or "").strip()) >= MIN_TRANSCRIPT_CHARS


def process_video(
    video: dict,
    index: int,
    total: int,
    out_dir: Path,
    ytdlp: list[str],
    args: argparse.Namespace,
) -> dict:
    label = f"[{index}/{total}] {video['title']} ({video['id']})"
    meta_path = out_dir / "meta" / f"{video['id']}.json"
    if meta_is_done(meta_path) and not args.redo and not args.rebuild:
        try:
            saved = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(saved, dict) and saved.get("playlist_index") != index:
                saved["playlist_index"] = index
                meta_path.write_text(
                    json.dumps(saved, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
        except json.JSONDecodeError:
            pass
        print(f"{label} 已有，跳過")
        return {"id": video["id"], "title": video["title"], "status": "skip"}
    raw_dir = out_dir / "raw" / video["id"]
    if args.redo and raw_dir.exists():
        shutil.rmtree(raw_dir, ignore_errors=True)
    print(label)
    log_path = out_dir / "logs" / f"{video['id']}.log"
    try:
        if not args.rebuild:
            info, log = download_subtitles(video, raw_dir, ytdlp, args, log_path)
        else:
            info, log = read_info(raw_dir, video["id"]), ""
            if not info and meta_path.exists():
                try:
                    info = json.loads(meta_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    info = {}
        subtitle = choose_subtitle(raw_dir, video["id"], args.lang, fallback=not args.no_fallback)
        if subtitle is None:
            message = "冇字幕"
            if auth_failure(log):
                message = "登入後先睇到，或者 cookie 無效"
            elif no_subtitle_message(log):
                message = "這條片沒有可下載字幕"
            print(f"! {video['id']} {message}")
            print(whisper_hint(video["id"]))
            return {"id": video["id"], "title": video["title"], "status": "fail", "error": message}
        raw = subtitle.read_text(encoding="utf-8-sig", errors="replace")
        transcript = clean_raw(raw, subtitle.suffix)
        if len(transcript) < MIN_TRANSCRIPT_CHARS:
            print(f"! {video['id']} 字幕是空的")
            return {"id": video["id"], "title": video["title"], "status": "fail", "error": "字幕是空的"}
        if args.rebuild and meta_path.exists():
            try:
                previous = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                previous = {}
            if isinstance(previous, dict):
                info = {**previous, **{k: v for k, v in info.items() if v}}
        meta = build_meta(video, info, subtitle, transcript, index)
        write_video_outputs(out_dir, meta)
        kind = meta["subtitle_kind"]
        print(f"  用 {meta['language']} {kind} {subtitle.suffix.lstrip('.')}，{len(transcript)} 字")
        return {"id": video["id"], "title": meta["title"], "status": "ok"}
    except Exception as exc:
        print(f"! {video['id']} 失敗：{exc}")
        return {"id": video["id"], "title": video["title"], "status": "fail", "error": str(exc)}


def whisper_hint(video_id: str) -> str:
    if getattr(whisper_hint, "shown", False):
        return "  冇字幕。本地 whisper 後備見上面第一次提示，或 README。"
    whisper_hint.shown = True
    return (
        "  如果要本地轉錄，先落音訊再跑 whisper（要另外裝，唔會自動跑）：\n"
        f'  yt-dlp --cookies-from-browser chrome -x --audio-format mp3 -o "{video_id}.%(ext)s" "{watch_url(video_id)}"\n'
        f"  whisper {video_id}.mp3 --model medium --language zh --output_format txt"
    )


def rebuild_from_raw(out_dir: Path, args: argparse.Namespace) -> list[dict]:
    raw_root = out_dir / "raw"
    if not raw_root.exists():
        print("冇 raw 字幕可重建。")
        return []
    videos = []
    for raw_dir in sorted(path for path in raw_root.iterdir() if path.is_dir()):
        videos.append({"id": raw_dir.name, "title": raw_dir.name, "url": watch_url(raw_dir.name)})
    results = []
    total = len(videos)
    for index, video in enumerate(videos, start=1):
        results.append(process_video(video, index, total, out_dir, [], args))
    return results


def read_batch(path: Path) -> list[str]:
    urls = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    return urls


def resolve_channel_id(target: str, ytdlp: list[str], args: argparse.Namespace) -> str:
    if CHANNEL_ID_RE.fullmatch(target.strip()):
        return target.strip()
    if target.startswith("http://") or target.startswith("https://"):
        url = target
    elif target.startswith("@"):
        url = "https://www.youtube.com/" + target
    else:
        url = "https://www.youtube.com/@" + target
    command = base_cmd(ytdlp, args) + [
        "--flat-playlist",
        "--playlist-end",
        "1",
        "--dump-single-json",
        url,
    ]
    result = run_capture(command)
    hint_from_log(result.stderr or "")
    if not result.stdout or "{" not in result.stdout:
        detail = (result.stderr or result.stdout or "")[-1500:]
        raise RuntimeError(f"搵唔到 channel id。\n{detail}")
    found = channel_id_from_info(load_ytdlp_json(result.stdout))
    if not found:
        raise RuntimeError(f"搵唔到 channel id：{target}")
    return found


def collect_targets(args: argparse.Namespace, ytdlp: list[str]) -> list[str]:
    targets: list[str] = []
    if args.members_of:
        channel_id = resolve_channel_id(args.members_of, ytdlp, args)
        playlist = members_playlist_url(channel_id, args.members_kind)
        print(f"頻道 {channel_id}")
        print(f"會員播放清單：{playlist}")
        targets.append(playlist)
    if args.url:
        targets.append(args.url)
    if args.batch_file:
        targets.extend(read_batch(args.batch_file))
    return targets


def dedupe_videos(videos: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique = []
    for video in videos:
        if video["id"] in seen:
            continue
        seen.add(video["id"])
        unique.append(video)
    return unique


def write_report(out_dir: Path, results: list[dict], playlist_title: str) -> None:
    counts = {"ok": 0, "skip": 0, "fail": 0}
    failures = []
    for item in results:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
        if item["status"] == "fail":
            failures.append(item)
    report = {
        "playlist_title": playlist_title,
        "ok": counts["ok"],
        "skip": counts["skip"],
        "fail": counts["fail"],
        "failures": failures,
    }
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def print_summary(out_dir: Path, results: list[dict], total_chars: int) -> None:
    counts = {"ok": 0, "skip": 0, "fail": 0}
    for item in results:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    print("")
    print(f"完成：成功 {counts['ok']}，跳過 {counts['skip']}，失敗 {counts['fail']}")
    print(f"餵 AI：上傳 {out_dir / 'md'} 入面逐個 .md")
    print(f"純文字：{out_dir / 'txt'}")
    print(f"程式用：{out_dir / 'all.json'} 同 {out_dir / 'transcripts.jsonl'}")
    print(f"索引：{out_dir / 'index.md'}")
    print(f"合集約 {total_chars} 字：{out_dir / 'combined.md'}")
    if total_chars > 400_000:
        print("合集超過約 40 萬字。NotebookLM 一個來源上限大約 50 萬字，請改傳 md/ 入面逐個檔。")
    if counts["fail"]:
        print(f"失敗清單：{out_dir / 'report.json'}")
        print("再跑同一條指令會跳過已完成的片，只重試未成功的。")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="下載你已經可以睇到的 YouTube 會員片字幕，轉成 Markdown / TXT / JSON。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "例子：\n"
            "  python yt_member_transcripts.py --members-of UCxxxx --dry-run\n"
            "  python yt_member_transcripts.py \"https://www.youtube.com/playlist?list=UUMOxxxx\" --limit 2\n"
            "  python yt_member_transcripts.py \"播放清單URL\" --out .\\laoyu_txt --browser firefox\n"
            "  python yt_member_transcripts.py --batch-file urls.txt --cookies cookies.txt\n"
            "\n"
            "頻道 ID UCxxxx 的會員清單：\n"
            "  全部 UUMO + xxxx    長片 UUMF + xxxx\n"
            "  Shorts UUMS + xxxx  直播 UUMV + xxxx\n"
            "會員專區頁通常只得最近幾條，唔好靠嗰個頁面攞全套。"
        ),
    )
    parser.add_argument("url", nargs="?", help="播放清單、單條片，或頻道 URL")
    parser.add_argument("--batch-file", type=Path, help="每行一條 URL，# 開頭是註解")
    parser.add_argument("--members-of", help="頻道 URL、@handle，或 UC 開頭的 channel id")
    parser.add_argument(
        "--members-kind",
        choices=sorted(MEMBERS_PREFIX),
        default="all",
        help="all=UUMO，videos=UUMF 長片，shorts=UUMS，live=UUMV",
    )
    parser.add_argument("--out", type=Path, default=Path("out"))
    parser.add_argument("--browser", default="chrome", help="chrome / edge / firefox / brave")
    parser.add_argument("--browser-profile", help="例如 Default 或 \"Profile 1\"")
    parser.add_argument("--cookies", type=Path, help="Netscape cookies.txt。有這個就不用讀瀏覽器")
    parser.add_argument("--no-cookies", action="store_true", help="不使用登入，只適用於公開片")
    parser.add_argument("--lang", default="zh-Hant", help="優先字幕語言")
    parser.add_argument("--no-fallback", action="store_true", help="只接受 --lang，沒有就當失敗")
    parser.add_argument("--limit", type=int, help="只處理清單最前面 N 條，用來先試")
    parser.add_argument("--sleep", type=float, default=2, help="每條片之間暫停幾秒，預設 2")
    parser.add_argument("--dry-run", action="store_true", help="只列出影片，不下載字幕")
    parser.add_argument("--redo", action="store_true", help="已完成的片都重新下載")
    parser.add_argument("--rebuild", action="store_true", help="用已下載的 raw 字幕重新產生 md/txt/json，不再上網")
    parser.add_argument("--yes-playlist", action="store_true", help="網址同時有 v= 和 list= 時跟播放清單")
    parser.add_argument("--self-test", action="store_true", help="跑內建測試，不用網路")
    args = parser.parse_args(argv)
    if not args.self_test and not args.rebuild and not args.url and not args.batch_file and not args.members_of:
        parser.error("請提供 URL、--batch-file、--members-of，或 --rebuild")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit 至少是 1")
    return args


def run_self_test() -> int:
    root = Path(__file__).resolve().parent
    suite = unittest.defaultTestLoader.discover(str(root / "tests"), top_level_dir=str(root))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def main(argv: list[str] | None = None) -> int:
    configure_stdio()
    args = parse_args(argv)
    if args.self_test:
        return run_self_test()
    if args.cookies and not args.no_cookies and not args.cookies.exists():
        print(f"搵唔到 cookies 檔：{args.cookies}", file=sys.stderr)
        return 2
    if args.batch_file and not args.batch_file.exists():
        print(f"搵唔到 batch 檔：{args.batch_file}", file=sys.stderr)
        return 2
    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in ("md", "txt", "meta", "raw", "logs"):
        (out_dir / name).mkdir(parents=True, exist_ok=True)

    if args.rebuild:
        results = rebuild_from_raw(out_dir, args)
        total_chars = write_indexes(out_dir) or 0
        print_summary(out_dir, results, total_chars)
        return 1 if any(item["status"] == "fail" for item in results) else 0

    ytdlp = ensure_ytdlp()
    try:
        targets = collect_targets(args, ytdlp)
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    videos: list[dict] = []
    playlist_names: list[str] = []
    for target in targets:
        try:
            title, found = list_videos(target, ytdlp, args)
        except RuntimeError as exc:
            print(f"列舉失敗 {target}\n{exc}", file=sys.stderr)
            return 2
        if title:
            playlist_names.append(title)
        videos.extend(found)
    videos = dedupe_videos(videos)
    if args.limit:
        videos = videos[: args.limit]
    playlist_title = " + ".join(playlist_names)
    (out_dir / "playlist.json").write_text(
        json.dumps(
            {"title": playlist_title, "count": len(videos), "videos": videos},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"清單 {len(videos)} 條" + (f"：{playlist_title}" if playlist_title else ""))
    if not videos:
        print("清單是空的。會員片要登入，而且會員專區頁通常不是全套清單。", file=sys.stderr)
        return 2
    if args.dry_run:
        for index, video in enumerate(videos, start=1):
            print(f"{index:4d}  {video['id']}  {video['title']}")
        print(f"清單已寫入 {out_dir / 'playlist.json'}")
        return 0

    results: list[dict] = []
    try:
        for index, video in enumerate(videos, start=1):
            results.append(process_video(video, index, len(videos), out_dir, ytdlp, args))
            if index < len(videos) and args.sleep > 0 and results[-1]["status"] != "skip":
                time.sleep(args.sleep)
    except KeyboardInterrupt:
        print("\n已停。再跑同一條指令會由未完成的片續傳。")
        total_chars = write_indexes(out_dir, playlist_title) or 0
        write_report(out_dir, results, playlist_title)
        print_summary(out_dir, results, total_chars)
        return 130

    total_chars = write_indexes(out_dir, playlist_title) or 0
    write_report(out_dir, results, playlist_title)
    print_summary(out_dir, results, total_chars)
    return 1 if any(item["status"] == "fail" for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
