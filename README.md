# YouTube 會員影片字幕

[English](README.en.md)

把你的帳號已經可以觀看的 YouTube 會員影片字幕，存成 Markdown、TXT 與 JSON。這個工具不下載影片，也不下載音訊。

給 NotebookLM、Claude 或 GPT 使用時，上傳 `md/` 裡的個別 `.md`。每支影片一個檔，內含標題、日期、連結和整理後的字幕。

## 安裝

需要 Python 3.11 或以上。Windows 有 Python 啟動器時用 `py -3`；沒有就改用 `python`。

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U -r requirements.txt
.\.venv\Scripts\python.exe yt_member_transcripts.py --self-test
```

macOS 與 Linux：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -U -r requirements.txt
.venv/bin/python yt_member_transcripts.py --self-test
```

依賴只有 [yt-dlp](https://github.com/yt-dlp/yt-dlp)。`.venv/` 不會進入版本庫。`--self-test` 不連網。

## 登入

帳號必須已經加入該頻道的會員。程式預設讀取 Chrome 的 cookie。Windows 上的 Chrome 常因 app-bound encryption 讀不到 cookie，可改用：

```powershell
.\.venv\Scripts\python.exe yt_member_transcripts.py "播放清單URL" --browser firefox --out .\out
.\.venv\Scripts\python.exe yt_member_transcripts.py "播放清單URL" --browser edge --out .\out
```

較穩妥的做法是匯出一份 Netscape cookie 檔：

1. 開無痕視窗，只登入要使用的那個 Google 帳號。
2. 瀏覽器若同時登入多個帳號，先把會員帳號切成目前帳號再匯出。YouTube 會使用 cookie 裡的預設帳號。這個工具不會加上 `authuser`，也不能指定第幾個帳號。
3. 只開啟 <https://www.youtube.com/robots.txt>。
4. 用擴充功能匯出 Netscape 格式的 `cookies.txt`。
5. 關閉該無痕視窗。不要再用這個工作階段開啟 YouTube。YouTube 會輪換登入 cookie，匯出的檔案隨即失效。

```powershell
.\.venv\Scripts\python.exe yt_member_transcripts.py "播放清單URL" --cookies .\cookies.txt --out .\out
```

Chrome 有多個設定檔時，加上 `--browser-profile "Profile 1"`。公開影片可用 `--no-cookies`。

`cookies.txt`、`cookies-*.txt` 與 `*.cookies.txt` 已列入 `.gitignore`。cookie 是登入工作階段，不要提交到 Git，也不要貼到問題回報。

## 指定影片

會員專區頁面通常只列出最近幾支，不是完整清單。頻道 ID 的形式是 `UC` 再加 22 個字元。去掉開頭的 `UC` 之後，系統播放清單是：

| 範圍 | 播放清單 ID |
| --- | --- |
| 全部會員影片 | `UUMO` + 其餘 22 字 |
| 長片 | `UUMF` + 其餘 22 字 |
| Shorts | `UUMS` + 其餘 22 字 |
| 直播 | `UUMV` + 其餘 22 字 |

頻道 ID 可在頻道頁的「簡介」→「更多」→「分享頻道」複製，或由程式解析：

```powershell
.\.venv\Scripts\python.exe yt_member_transcripts.py --members-of "https://www.youtube.com/@頻道" --dry-run
```

`--members-of` 接受頻道 URL、`@handle` 或 `UC...`。`--members-kind` 可選 `all`（預設）、`videos`、`shorts`、`live`。

`--dry-run` 只列出影片並寫入 `playlist.json`，不下載字幕。`--limit 2` 是在整份清單列舉完成後，只處理開頭的 N 支。會員清單通常由新到舊，所以這是最新的 N 支，不是「跳過已完成的影片之後再取 N 支」。已完成的影片會在這 N 支裡面被跳過。

先試兩支：

```powershell
.\.venv\Scripts\python.exe yt_member_transcripts.py "https://www.youtube.com/playlist?list=UUMOxxxx" --out .\out --limit 2
```

確認 `out\md\` 之後，去掉 `--limit` 即處理清單內全部影片。中斷後用同一指令再跑。`meta/{影片ID}.json` 裡的字幕正文達到 5 個字元，即視為完成並跳過。`--redo` 會重新下載。每支新處理的影片之間預設暫停 2 秒，可用 `--sleep` 調整。

網址同時有 `v=` 和 `list=` 時，預設只處理那一支影片。要跟整份播放清單，加 `--yes-playlist`。

多個網址可放在文字檔，一行一個，`#` 開頭是註解：

```powershell
.\.venv\Scripts\python.exe yt_member_transcripts.py --batch-file .\urls.txt --cookies .\cookies.txt --out .\out
```

正在直播或尚未開始的項目會跳過。標成私人、已刪除或無法取得的項目也會跳過。

## 檔名

人讀的檔案是 `YYYY-MM-DD 標題.md` 與同名 `.txt`。

- 標題以 `YYYYMMDD` 開頭時，檔名採用這組日期，並從標題移除這 8 個數字。上傳日不同時，也不會變成兩個日期疊在一起。
- 否則使用 YouTube 上傳日。上傳日來自 8 位數字 `YYYYMMDD`，寫成 `YYYY-MM-DD`。
- `< > : " / \ | ? *` 與控制字元改成空格。連續空白收成一個，結尾的空格和句點會去掉。全形標點保留。
- 主檔名最長 140 個字元。
- 同一輪寫入索引時，若主檔名重複，後者會加上影片 ID。
- `index.md` 的日期欄是上傳日，所以可以和檔名上的日期不同。

`meta/`、`raw/`、`logs/` 仍以影片 ID 命名。續傳和 `--rebuild` 靠這三處辨認影片。

## 輸出

預設目錄是 `out/`。

```text
out/
  md/YYYY-MM-DD 標題.md    給模型，上傳這個
  txt/YYYY-MM-DD 標題.txt  純文字
  index.md                 目錄。日期欄是上傳日
  combined.md              全部字幕合在一個檔
  all.json                 程式讀取
  transcripts.jsonl        一行一筆，程式讀取
  meta/{影片ID}.json       進度與中介資料，含 file_stem
  raw/{影片ID}/            原始字幕
  logs/{影片ID}.log        該支影片的 yt-dlp 紀錄
  report.json              失敗清單
  playlist.json            本次處理的清單
```

每支影片只下載一種字幕。預設語言是 `zh-Hant`。人手字幕優先於自動字幕，也不會把其他語言的翻譯軌全部抓下來。沒有偏好語言時會改用相近語言，除非加上 `--no-fallback`。Markdown 會標示語言，以及「人手」或「自動」。

`combined.md` 只方便檢視。字幕正文合計超過 40 萬個字元時，程式會提醒。這是字元數，不是詞數。NotebookLM（現稱 Gemini Notebook）公開的單一來源上限以詞數和檔案大小計算，來源個數另視方案而定，而且會調整。上傳個別 `.md`。

清洗規則改動之後，可離線重製文字：

```powershell
.\.venv\Scripts\python.exe yt_member_transcripts.py --rebuild --out .\out
```

`--rebuild` 只讀取 `raw/`，不會連網。

## 沒有字幕時

程式不會自動下載影片或音訊，也不會自動執行 Whisper。

`report.json` 的 `error` 只有三種：

| 紀錄內容 | `error` |
| --- | --- |
| 寫明沒有所請求的字幕 | `這支影片沒有可下載的字幕` |
| 沒有上一句，但有登入或會員錯誤 | `登入後才看得到，或 cookie 已失效` |
| 兩者都沒有 | `沒有字幕` |

YouTube 常在同一段紀錄裡同時寫會員提示和「沒有字幕」。兩句都在時，以沒有字幕為準。會員提示單獨出現，才算登入或會員資格的問題。

若要自行轉錄，程式會印出範例指令。粵語內容可用 `whisper ... --model medium --language zh`。Whisper 與音訊下載都要另外安裝、另外執行。

字幕網址若被丟棄，常見原因是 YouTube 要求 PO Token。請看 [yt-dlp 的 PO Token 說明](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide)。yt-dlp 也可能提示缺少 JavaScript runtime；請看 [EJS](https://github.com/yt-dlp/yt-dlp/wiki/EJS)。這兩項都不是本程式內建的功能。

## 公開這個倉庫之前

版本庫目前的歷史只有程式、測試與說明，沒有 cookie，也沒有下載下來的字幕。公開之後，下列內容仍不應進入 Git：

- 任何 cookie 檔。外流等同交出該 Google 帳號的工作階段。
- `md/`、`txt/`、`raw/`、`meta/` 和你的輸出目錄。裡面是會員內容的正文。
- `--out` 若不用 `out/`，該目錄不會被自動忽略，必須自行寫進 `.gitignore`。`out/` 已忽略。

只下載你的帳號已經可以觀看的內容。會員字幕的權利依創作者與 YouTube 的約定而定；把下載結果提交到公開倉庫或轉傳給他人，通常超出個人收看範圍。

本倉庫沒有授權條款。選定授權之前，他人沒有預設的重用許可。使用 yt-dlp 存取 YouTube 時，須同時遵守 YouTube 服務條款，以及你和頻道之間的會員條款。
