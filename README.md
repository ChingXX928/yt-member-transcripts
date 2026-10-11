# YouTube 會員片字幕

把你已經可以睇到的 YouTube 會員片字幕下載成 Markdown、TXT、JSON。唔會下載影片。

餵 NotebookLM、Claude、GPT：上傳 `md/` 入面逐個 `.md`。

Markdown 比一個大 JSON 適合 AI。每條片有標題、日期、連結同分段字幕。JSON 的鍵名都會佔字數，而且幾百條片合成一個檔，容易超過 NotebookLM 一個來源大約 50 萬字的上限。`all.json` 同 `transcripts.jsonl` 留俾程式用。

## 點解唔好直接用會員專區個頁

YouTube 會員專區而家通常只顯示最近幾條。全套會員片要用系統播放清單。頻道 ID 是 `UC` 加 22 個字，去掉 `UC` 之後：

| 想要 | 播放清單 |
| --- | --- |
| 全部會員片 | `https://www.youtube.com/playlist?list=UUMO` + 餘下 22 字 |
| 長片 | `UUMF` + 餘下 22 字 |
| Shorts | `UUMS` + 餘下 22 字 |
| 直播 | `UUMV` + 餘下 22 字 |

頻道 ID：頻道頁 → 簡介更多 → 分享頻道 → 複製頻道 ID。或者直接：

```powershell
.\.venv\Scripts\python.exe yt_member_transcripts.py --members-of "https://www.youtube.com/@頻道" --dry-run
```

`--dry-run` 只列片，不下載。

## 安裝

這個資料夾已經有 `.venv`，yt-dlp 已裝好。換電腦就：

```powershell
cd C:\Users\ching\yt-member-transcripts
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U -r requirements.txt
.\.venv\Scripts\python.exe yt_member_transcripts.py --self-test
```

## 先試兩條

```powershell
cd C:\Users\ching\yt-member-transcripts
.\.venv\Scripts\python.exe yt_member_transcripts.py "https://www.youtube.com/playlist?list=UUMOxxxx" --out .\laoyu_txt --limit 2
```

睇 `laoyu_txt\md\`。內容正常再拿掉 `--limit`，可以掛過夜。中斷之後再跑同一句會跳過已完成的片。

預設讀 Chrome cookie。Windows 上 Chrome 經常讀唔到（app-bound encryption）。失敗就改：

```powershell
.\.venv\Scripts\python.exe yt_member_transcripts.py "播放清單URL" --browser firefox --out .\laoyu_txt
.\.venv\Scripts\python.exe yt_member_transcripts.py "播放清單URL" --browser edge --out .\laoyu_txt
```

或者用無痕視窗登入 YouTube，只開 `https://www.youtube.com/robots.txt`，用擴充功能匯出 Netscape `cookies.txt`，然後關掉個無痕視窗，不要再在瀏覽器開 YouTube：

```powershell
.\.venv\Scripts\python.exe yt_member_transcripts.py "播放清單URL" --cookies .\cookies.txt --out .\laoyu_txt
```

每條片只下載一種最合適的字幕，不會把所有翻譯軌一起抓下來。

帳號必須已經是該頻道會員。不要把 `cookies.txt` 傳給別人。

Chrome 有多個設定檔時加 `--browser-profile "Profile 1"`。

## 輸出

```text
laoyu_txt/
  md/影片ID.md          餵 AI，用這個
  txt/影片ID.txt        純文字
  all.json              全部合成一個 JSON
  transcripts.jsonl     一行一條，程式用
  combined.md           合集。太大就不要上傳
  index.md              目錄
  raw/                  原始字幕，可 --rebuild
  report.json           失敗清單
```

清洗邏輯改完之後，可以不上網重做文字：

```powershell
.\.venv\Scripts\python.exe yt_member_transcripts.py --rebuild --out .\laoyu_txt
```

## 沒有字幕

腳本不會自動下載影片。某條片真的沒有字幕時，它會印出 whisper 指令。廣東話內容用 `--language zh`，模型 `medium` 通常夠用。

## 舊稿會踩到的問題

- 一條片失敗就整批退出，已下載的也不會轉文字
- `--batch-file` 寫了但沒有做
- 進度被藏起來，長時間看起來像當機
- 只刪掉連續重複的一行。YouTube 自動字幕的 VTT 是滾動窗口，同一句會換著字重複
- `--sub-langs zh.*` 會把每種語言翻譯都下載，容易 HTTP 429
- 只認 `.srt`，實際很多自動字幕是 `.vtt` 或 `.json3`
- 會員專區頁不是全套清單
