# YouTube member-video subtitles

[中文](README.md)

Save subtitles from YouTube member videos your account can already watch. Output is Markdown, TXT, and JSON. This tool does not download video or audio.

For NotebookLM, Claude, or GPT, upload the individual `.md` files in `md/`. Each file is one video and contains the title, date, link, and cleaned transcript.

## Install

Python 3.11 or newer is required. On Windows, use `py -3` when the Python launcher is installed; otherwise use `python`.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U -r requirements.txt
.\.venv\Scripts\python.exe yt_member_transcripts.py --self-test
```

macOS and Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -U -r requirements.txt
.venv/bin/python yt_member_transcripts.py --self-test
```

The only dependency is [yt-dlp](https://github.com/yt-dlp/yt-dlp). `.venv/` is not part of the repository. `--self-test` does not use the network.

## Sign in

The account must already be a member of the channel. The default is to read Chrome’s cookies. On Windows, Chrome often cannot be read because of app-bound encryption. Use another browser instead:

```powershell
.\.venv\Scripts\python.exe yt_member_transcripts.py "PLAYLIST_URL" --browser firefox --out .\out
.\.venv\Scripts\python.exe yt_member_transcripts.py "PLAYLIST_URL" --browser edge --out .\out
```

Exporting a Netscape cookie file is more predictable:

1. Open a private window and sign in to the one Google account you intend to use.
2. If several Google accounts are signed in, switch to the member account before exporting. YouTube uses the default account stored in the cookie jar. This tool does not add `authuser` and cannot select an account by index.
3. Open only <https://www.youtube.com/robots.txt>.
4. Export a Netscape-format `cookies.txt` with a cookie extension.
5. Close that private window. Do not open YouTube again in that same session. YouTube rotates the sign-in cookies, and the exported file stops working.

```powershell
.\.venv\Scripts\python.exe yt_member_transcripts.py "PLAYLIST_URL" --cookies .\cookies.txt --out .\out
```

For another Chrome profile, add `--browser-profile "Profile 1"`. Public videos can use `--no-cookies`.

`cookies.txt`, `cookies-*.txt`, and `*.cookies.txt` are listed in `.gitignore`. A cookie file is a sign-in session. Do not commit it or paste it into an issue.

## Which videos

The channel membership tab usually lists only the latest few videos, not the full archive. A channel id is `UC` plus 22 characters. Remove the leading `UC`, then build the system playlist:

| Scope | Playlist id |
| --- | --- |
| All member videos | `UUMO` + the other 22 characters |
| Long videos | `UUMF` + the other 22 characters |
| Shorts | `UUMS` + the other 22 characters |
| Live streams | `UUMV` + the other 22 characters |

Copy the channel id from the channel page: About, then more, then Share channel. Or let the tool resolve it:

```powershell
.\.venv\Scripts\python.exe yt_member_transcripts.py --members-of "https://www.youtube.com/@channel" --dry-run
```

`--members-of` accepts a channel URL, an `@handle`, or a `UC...` id. `--members-kind` is `all` (the default), `videos`, `shorts`, or `live`.

`--dry-run` lists videos and writes `playlist.json`. It does not download subtitles. `--limit 2` applies after the whole list has been fetched: only the first N entries are processed. Member playlists are usually newest first, so this is the newest N videos. It does not mean “skip finished videos, then take N more.” Finished videos inside those N entries are skipped.

Try two videos:

```powershell
.\.venv\Scripts\python.exe yt_member_transcripts.py "https://www.youtube.com/playlist?list=UUMOxxxx" --out .\out --limit 2
```

After checking `out\md\`, drop `--limit` to process the whole list. Run the same command again after an interruption. A video is finished when `meta/{video-id}.json` contains a transcript of at least 5 characters. `--redo` downloads it again. The tool pauses 2 seconds after each newly processed video. Change that with `--sleep`.

A URL that contains both `v=` and `list=` is treated as one video. Add `--yes-playlist` to follow the playlist.

Put several URLs in a text file, one per line. Lines starting with `#` are comments:

```powershell
.\.venv\Scripts\python.exe yt_member_transcripts.py --batch-file .\urls.txt --cookies .\cookies.txt --out .\out
```

Live and upcoming entries are skipped. Entries marked private, deleted, or unavailable are skipped.

## File names

The files meant for people are `YYYY-MM-DD title.md` and a `.txt` file with the same stem.

- When the title starts with `YYYYMMDD`, that date is used in the file name and those eight digits are removed from the title. A different upload date is not added in front, so the name does not contain two dates.
- Otherwise the YouTube upload date is used. An 8-digit `YYYYMMDD` value is written as `YYYY-MM-DD`.
- `< > : " / \ | ? *` and control characters become spaces. Repeated whitespace is collapsed. Trailing spaces and periods are removed. Fullwidth punctuation is kept.
- The stem is capped at 140 characters.
- If two stems would match while the index is written, the later file gets the video id appended.
- The date column in `index.md` is the upload date, so it can differ from the date in the file name.

`meta/`, `raw/`, and `logs/` stay named by video id. Resume and `--rebuild` depend on those names.

## Output

The default directory is `out/`.

```text
out/
  md/YYYY-MM-DD title.md     for a model; upload these
  txt/YYYY-MM-DD title.txt   plain text
  index.md                   catalog; the date column is the upload date
  combined.md                every transcript in one file
  all.json                   for programs
  transcripts.jsonl          one JSON object per line, for programs
  meta/{video-id}.json       progress and metadata, including file_stem
  raw/{video-id}/            original subtitle file
  logs/{video-id}.log        yt-dlp log for that video
  report.json                failures
  playlist.json              the list processed this run
```

Each video contributes one subtitle. The preferred language is `zh-Hant`. A manual track is preferred to an automatic track. Translation tracks in other languages are not all downloaded. If the preferred language is missing, a close language is used unless you pass `--no-fallback`. The Markdown file records the language and whether the track was manual or automatic (`人手` or `自動` in the Chinese label).

`combined.md` is only a convenience. The tool warns when the transcript bodies together exceed 400,000 characters. That number is a character count, not a word count. NotebookLM, now Gemini Notebook, publishes a per-source limit in words and file size. The number of sources depends on the plan, and both limits change. Upload the individual `.md` files.

After a change to the cleaning rules, rebuild the text offline:

```powershell
.\.venv\Scripts\python.exe yt_member_transcripts.py --rebuild --out .\out
```

`--rebuild` reads `raw/` and does not use the network.

## When a video has no subtitles

The tool does not download video or audio on its own, and it does not run Whisper.

`report.json` uses one of three `error` strings:

| What the log contains | `error` |
| --- | --- |
| An explicit statement that the requested subtitles are absent | `這支影片沒有可下載的字幕` |
| No such statement, but a sign-in or membership error | `登入後才看得到，或 cookie 已失效` |
| Neither | `沒有字幕` |

YouTube often prints a membership warning and “no subtitles” in the same log. When both are present, the report says the video has no downloadable subtitles. A membership warning by itself is treated as a sign-in or membership problem.

If you want your own transcript, the tool prints sample commands. For Cantonese, `whisper ... --model medium --language zh` is the sample it prints. Install and run Whisper, and the audio download, separately.

Caption URLs are sometimes discarded because YouTube requires a PO Token. See the [yt-dlp PO Token Guide](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide). yt-dlp may also warn that no JavaScript runtime is available; see [EJS](https://github.com/yt-dlp/yt-dlp/wiki/EJS). Neither feature is built into this program.

## Before making this repository public

The history of this repository contains the program, tests, and these documents. It does not contain cookies or downloaded transcripts. After the repository is public, the following still must stay out of Git:

- Any cookie file. Publishing it hands over that Google account session.
- `md/`, `txt/`, `raw/`, `meta/`, and your output directory. Those files contain membership content.
- A custom `--out` directory is not ignored automatically. Add it to `.gitignore`. The default `out/` directory is ignored.

Download only what your account can already watch. Rights in member subtitles follow the creator’s terms and YouTube’s terms. Committing the downloaded text to a public repository, or passing it on, is usually outside personal viewing.

This repository has no license file. Until you choose one, other people do not have a default right to reuse it. Accessing YouTube through yt-dlp also has to follow the YouTube Terms of Service and the membership terms between you and the channel.
