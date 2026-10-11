# YouTube 會員影片字幕

本工具將使用者已可觀看的 YouTube 會員影片字幕下載為 Markdown、TXT 與 JSON，不下載影片本體。

若要供 NotebookLM、Claude 或 GPT 使用，請上傳 `md/` 目錄中的個別 `.md` 檔。

Markdown 比單一大型 JSON 更適合作為模型輸入。每支影片各自包含標題、日期、連結與分段字幕。JSON 的鍵名亦會計入字數；若將數百支影片併為一個檔案，很容易超過 NotebookLM 單一來源約五十萬字的上限。`all.json` 與 `transcripts.jsonl` 保留給程式讀取。

## 會員專區頁面的限制

YouTube 會員專區目前通常只顯示最近數支影片。完整的會員影片清單須使用系統播放清單。頻道 ID 以 `UC` 起首，其後為 22 個字元。去掉 `UC` 之後，可依下表組成清單：

| 範圍 | 播放清單 |
| --- | --- |
| 全部會員影片 | `https://www.youtube.com/playlist?list=UUMO` + 其餘 22 字 |
| 長片 | `UUMF` + 其餘 22 字 |
| Shorts | `UUMS` + 其餘 22 字 |
| 直播 | `UUMV` + 其餘 22 字 |

頻道 ID 可在頻道頁面依序開啟「簡介」、「更多」、「分享頻道」，再複製頻道 ID。亦可直接執行：

```powershell
.\.venv\Scripts\python.exe yt_member_transcripts.py --members-of "https://www.youtube.com/@頻道" --dry-run
```

`--dry-run` 只列出影片，不進行下載。

## 安裝

此資料夾已包含 `.venv`，且已安裝 yt-dlp。若在另一部電腦使用，請執行：

```powershell
cd C:\Users\ching\yt-member-transcripts
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U -r requirements.txt
.\.venv\Scripts\python.exe yt_member_transcripts.py --self-test
```

## 先以兩支影片試行

```powershell
cd C:\Users\ching\yt-member-transcripts
.\.venv\Scripts\python.exe yt_member_transcripts.py "https://www.youtube.com/playlist?list=UUMOxxxx" --out .\laoyu_txt --limit 2
```

請查看 `laoyu_txt\md\`。內容無誤後，移除 `--limit` 即可處理全部影片，適合長時間執行。若中途中斷，以同一指令再次執行時，已完成的影片會被略過。

預設讀取 Chrome 的 cookie。在 Windows 上，Chrome 的 cookie 經常無法讀取（app-bound encryption）。若失敗，可改用下列指令：

```powershell
.\.venv\Scripts\python.exe yt_member_transcripts.py "播放清單URL" --browser firefox --out .\laoyu_txt
.\.venv\Scripts\python.exe yt_member_transcripts.py "播放清單URL" --browser edge --out .\laoyu_txt
```

亦可使用無痕視窗登入 YouTube，只開啟 `https://www.youtube.com/robots.txt`，再以擴充功能匯出 Netscape 格式的 `cookies.txt`，隨即關閉該無痕視窗，且不要再於瀏覽器中開啟 YouTube：

```powershell
.\.venv\Scripts\python.exe yt_member_transcripts.py "播放清單URL" --cookies .\cookies.txt --out .\laoyu_txt
```

每支影片只下載一種最合適的字幕，不會一併取得所有翻譯軌。

使用的帳號必須已加入該頻道的會員。請勿將 `cookies.txt` 交給他人。

若 Chrome 有多個設定檔，請加上 `--browser-profile "Profile 1"`。

## 輸出

```text
laoyu_txt/
  md/影片ID.md          供模型使用，應上傳此檔
  txt/影片ID.txt        純文字
  all.json              全部影片合成的 JSON
  transcripts.jsonl     每行一筆，供程式使用
  combined.md           合集。檔案過大時不宜上傳
  index.md              目錄
  raw/                  原始字幕，可用 --rebuild 重建
  report.json           失敗清單
```

清洗邏輯修改之後，可在不上網的情況下重製文字：

```powershell
.\.venv\Scripts\python.exe yt_member_transcripts.py --rebuild --out .\laoyu_txt
```

## 沒有字幕時

程式不會自動下載影片。若某支影片確實沒有字幕，程式會印出 whisper 指令。廣東話內容使用 `--language zh`，`medium` 模型通常已足敷使用。

## 舊稿的問題

- 單支影片失敗即導致整批結束，已下載的字幕亦不會轉成文字。
- 文件寫有 `--batch-file`，程式卻未實作。
- 進度被隱藏，長時間執行時看似當機。
- 只刪除連續重複的一行。YouTube 自動字幕的 VTT 為滾動視窗，同一句會以不同文字重複出現。
- `--sub-langs zh.*` 會下載每種語言的翻譯，容易觸發 HTTP 429。
- 只接受 `.srt`，實際許多自動字幕為 `.vtt` 或 `.json3`。
- 會員專區頁面並非完整清單。
