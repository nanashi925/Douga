#!/usr/bin/env python3
"""
build.py — ずんだもん＆四国めたん 珈琲解説動画ジェネレーター
tts.quest API で音声取得 → ffmpeg で結合 → Pillow でフレーム生成 → mp4 出力
"""

import argparse, json, os, re, shutil, subprocess, sys, time, urllib.parse, urllib.request

from PIL import Image, ImageDraw, ImageFont

# ─── 設定 ───────────────────────────────────────────────
WIDTH, HEIGHT = 960, 540
FPS = 1  # 静止画なのでフレームレートは最小限
STEP_GAP = 0.5  # セリフ間の間隔(秒)
TITLE_DUR = 3.0  # タイトル画面の長さ(秒)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(BASE_DIR, "audio")
FRAMES_DIR = os.path.join(BASE_DIR, "frames")
OUTPUT_FILE = os.path.join(BASE_DIR, "output.mp4")

SPEAKER_ID = {"zunda": 3, "metan": 2}
NAMES = {"zunda": "ずんだもん", "metan": "四国めたん"}
COLORS = {
    "zunda": {"tag": (86, 171, 47), "name": (168, 224, 99)},
    "metan": {"tag": (194, 24, 91), "name": (244, 143, 177)},
}

# 台本
SCRIPT = [
    {"s": "zunda", "t": "どうも、ずんだもんなのだ！\n今日は珈琲の豆知識を紹介するのだ！",
                   "v": "どうも、ずんだもんなのだ！今日は珈琲の豆知識を紹介するのだ！"},
    {"s": "metan", "t": "四国めたんですわ。\n珈琲、わたくしも大好きですの。",
                   "v": "四国めたんですわ。珈琲、わたくしも大好きですの。"},
    {"s": "zunda", "t": "突然だけど、珈琲を最初に発見したのは\n「ヤギ」なのだ。",
                   "v": "突然だけど、珈琲を最初に発見したのはヤギなのだ。"},
    {"s": "metan", "t": "……ヤギですの？",
                   "v": "ヤギですの？"},
    {"s": "zunda", "t": "エチオピアのヤギ飼いが、\n赤い実を食べたヤギが夜中まで大はしゃぎしてるのを見て、\n珈琲が発見されたと言われているのだ。",
                   "v": "エチオピアのヤギ飼いが、赤い実を食べたヤギが夜中まで大はしゃぎしてるのを見て、珈琲が発見されたと言われているのだ。"},
    {"s": "metan", "t": "まあ、ヤギがカフェインで\n興奮してしまったということですの？",
                   "v": "まあ、ヤギがカフェインで興奮してしまったということですの？"},
    {"s": "zunda", "t": "そういうことなのだ。あと、もうひとつ。",
                   "v": "そういうことなのだ。あと、もうひとつ。"},
    {"s": "zunda", "t": "深煎りの珈琲と浅煎りの珈琲、\nカフェインが多いのはどっちだと思うのだ？",
                   "v": "深煎りの珈琲と浅煎りの珈琲、カフェインが多いのはどっちだと思うのだ？"},
    {"s": "metan", "t": "それは深煎りではなくて？\n苦いですし。",
                   "v": "それは深煎りではなくて？苦いですし。"},
    {"s": "zunda", "t": "実は浅煎りの方がカフェインは多いのだ！\n焙煎でカフェインは分解されるのだ。",
                   "v": "実は浅煎りの方がカフェインは多いのだ！焙煎でカフェインは分解されるのだ。"},
    {"s": "metan", "t": "えっ……！\n苦さとカフェインは関係ありませんの？\nそれは驚きですわ。",
                   "v": "えっ！苦さとカフェインは関係ありませんの？それは驚きですわ。"},
    {"s": "zunda", "t": "珈琲は知れば知るほど面白い飲み物なのだ。\nみんなもぜひ味わってみてほしいのだ！",
                   "v": "珈琲は知れば知るほど面白い飲み物なのだ。みんなもぜひ味わってみてほしいのだ！"},
    {"s": "metan", "t": "面白かったらグッドボタンをお願いしますわ。\nそれでは、ごきげんよう。",
                   "v": "面白かったらグッドボタンをお願いしますわ。それでは、ごきげんよう。"},
    {"s": "zunda", "t": "ばいばいなのだ！",
                   "v": "ばいばいなのだ！"},
]

# ─── フォント ────────────────────────────────────────────
def _find_font():
    for p in [
        "/usr/share/fonts/opentype/ipafont-gothic/ipagp.ttf",
        "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
        "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]:
        if os.path.exists(p):
            return p
    sys.exit("Japanese font not found")

FONT_PATH = _find_font()

def font(size):
    return ImageFont.truetype(FONT_PATH, size)

# ─── 1. 音声取得 ─────────────────────────────────────────

# espeak-ng の声設定（ずんだもん=男声, 四国めたん=女声）
ESPEAK_VOICE = {"zunda": "ja", "metan": "ja+f3"}

def _has_espeak():
    return shutil.which("espeak-ng") is not None

def espeak_synth(text, speaker, dest):
    """espeak-ng で wav を生成（APIフォールバック用）"""
    voice = ESPEAK_VOICE.get(speaker, "ja")
    subprocess.run(
        ["espeak-ng", "-v", voice, "-s", "160", "-w", dest, text],
        capture_output=True, check=True
    )

def api_get(url):
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, json.loads(r.read())

def download(url, dest):
    urllib.request.urlretrieve(url, dest)

def fetch_audio_voicevox(index, line):
    """tts.quest API で音声取得"""
    dest = os.path.join(AUDIO_DIR, f"{index:02d}.mp3")
    if os.path.exists(dest) and os.path.getsize(dest) > 1000:
        print(f"  [{index:02d}] cached")
        return dest

    sid = SPEAKER_ID[line["s"]]
    text = line["v"]
    api_url = f"https://api.tts.quest/v3/voicevox/synthesis?speaker={sid}&text={urllib.parse.quote(text)}"

    for attempt in range(3):
        try:
            status, data = api_get(api_url)
        except Exception as e:
            print(f"  [{index:02d}] request error: {e}, retry...")
            time.sleep(2 * (attempt + 1))
            continue

        # 429 rate limit
        if "retryAfter" in data and data.get("retryAfter"):
            wait = data["retryAfter"] + 1
            print(f"  [{index:02d}] rate limited, wait {wait}s")
            time.sleep(wait)
            continue

        # async synthesis
        if data.get("audioStatusUrl"):
            dl_url = data.get("mp3DownloadUrl")
            st_url = data.get("audioStatusUrl")
            print(f"  [{index:02d}] polling...", end="", flush=True)
            for _ in range(60):
                time.sleep(0.5)
                try:
                    _, st = api_get(st_url)
                    if st.get("isAudioReady"):
                        print(" ready")
                        if dl_url:
                            download(dl_url, dest)
                            return dest
                        break
                    if st.get("isAudioError"):
                        print(" error")
                        break
                except Exception:
                    pass
                print(".", end="", flush=True)
            print()
            continue

        # direct download
        dl_url = data.get("mp3DownloadUrl") or data.get("mp3StreamingUrl")
        if dl_url:
            download(dl_url, dest)
            print(f"  [{index:02d}] ok")
            return dest

        time.sleep(1)

    return None

LOCAL_ONLY = False  # --local フラグで True に

def fetch_audio(index, line):
    """音声取得: VOICEVOX API → espeak-ng フォールバック"""
    # キャッシュ済みチェック
    for ext in (".mp3", ".wav"):
        cached = os.path.join(AUDIO_DIR, f"{index:02d}{ext}")
        if os.path.exists(cached) and os.path.getsize(cached) > 1000:
            print(f"  [{index:02d}] cached")
            return cached

    # VOICEVOX API を試行（--local でスキップ）
    if not LOCAL_ONLY:
        result = fetch_audio_voicevox(index, line)
        if result:
            return result

    # espeak-ng フォールバック
    if _has_espeak():
        dest = os.path.join(AUDIO_DIR, f"{index:02d}.wav")
        try:
            espeak_synth(line["v"], line["s"], dest)
            print(f"  [{index:02d}] espeak-ng fallback ok")
            return dest
        except Exception as e:
            print(f"  [{index:02d}] espeak-ng error: {e}")

    print(f"  [{index:02d}] FAILED")
    return None

def fetch_all_audio():
    os.makedirs(AUDIO_DIR, exist_ok=True)
    paths = []
    for i, line in enumerate(SCRIPT):
        p = fetch_audio(i, line)
        paths.append(p)
        time.sleep(0.3)
    return paths

# ─── 2. ffmpeg で音声処理 ──────────────────────────────────
def get_duration(path):
    """ffprobe で音声の長さ(秒)を取得"""
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True
    )
    return float(r.stdout.strip())

def trim_silence(src, dst):
    """末尾の無音だけをカット（内部の間は保持）"""
    # reverse → 先頭の無音除去 → reverse で末尾だけトリム
    subprocess.run(
        ["ffmpeg", "-y", "-i", src,
         "-af", "areverse,silenceremove=start_periods=1:start_duration=0.05:start_threshold=-40dB,areverse",
         "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", dst],
        capture_output=True, check=True
    )

def make_silence(dst, duration=0.5):
    """無音ファイルを生成"""
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         "anullsrc=r=24000:cl=mono",
         "-t", str(duration), "-ar", "24000", "-ac", "1",
         "-c:a", "pcm_s16le", dst],
        capture_output=True, check=True
    )

def export_web_audio(audio_paths):
    """トリミング済み音声を voice/ にmp3で書き出し（HTML用）"""
    voice_dir = os.path.join(BASE_DIR, "voice")
    os.makedirs(voice_dir, exist_ok=True)

    trimmed_dir = os.path.join(AUDIO_DIR, "trimmed")

    for i, p in enumerate(audio_paths):
        dest = os.path.join(voice_dir, f"{i:02d}.mp3")
        src = os.path.join(trimmed_dir, f"{i:02d}_trimmed.wav")
        if not os.path.exists(src):
            # trimmed がなければ元ファイルから直接変換
            src = p if p else None
        if src and os.path.exists(src):
            subprocess.run(
                ["ffmpeg", "-y", "-i", src,
                 "-c:a", "libmp3lame", "-b:a", "128k", dest],
                capture_output=True, check=True
            )
            print(f"  [{i:02d}] exported to voice/{i:02d}.mp3")
        else:
            print(f"  [{i:02d}] skipped (no source)")

def merge_audio(audio_paths):
    """全音声をトリミング→0.5秒間隔で結合"""
    trimmed_dir = os.path.join(AUDIO_DIR, "trimmed")
    os.makedirs(trimmed_dir, exist_ok=True)

    silence_file = os.path.join(trimmed_dir, "silence.wav")
    make_silence(silence_file, STEP_GAP)

    durations = []
    concat_list = []

    for i, p in enumerate(audio_paths):
        if p is None:
            durations.append(1.0)
            dummy = os.path.join(trimmed_dir, f"{i:02d}_trimmed.wav")
            make_silence(dummy, 1.0)
            concat_list.append(dummy)
        else:
            trimmed = os.path.join(trimmed_dir, f"{i:02d}_trimmed.wav")
            trim_silence(p, trimmed)
            dur = get_duration(trimmed)
            durations.append(dur)
            concat_list.append(trimmed)

        if i < len(audio_paths) - 1:
            concat_list.append(silence_file)

    # concat用テキストファイル生成
    list_file = os.path.join(AUDIO_DIR, "concat.txt")
    with open(list_file, "w") as f:
        for p in concat_list:
            f.write(f"file '{p}'\n")

    merged = os.path.join(AUDIO_DIR, "merged.wav")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
         "-i", list_file, "-ar", "24000", "-ac", "1",
         "-c:a", "pcm_s16le", merged],
        capture_output=True, check=True
    )

    print(f"  merged audio: {get_duration(merged):.1f}s")
    return merged, durations

# ─── 3. フレーム生成 (Pillow) ──────────────────────────────
def draw_bg(img):
    """珈琲テーマの背景グラデーション"""
    draw = ImageDraw.Draw(img)
    for y in range(HEIGHT):
        r = int(60 * (1 - y / HEIGHT) + 26 * (y / HEIGHT))
        g = int(36 * (1 - y / HEIGHT) + 26 * (y / HEIGHT))
        b = int(21 * (1 - y / HEIGHT) + 62 * (y / HEIGHT))
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b))
    # テーマ装飾（背景にうっすら）— RGB画像なのでグラデに近い色で薄く
    try:
        deco_font = font(90)
        # 背景色に近い薄い色で描画（ほぼ見えない程度）
        draw.text((WIDTH // 2, HEIGHT * 32 // 100), "COFFEE",
                  fill=(38, 33, 30), font=deco_font, anchor="mm")
    except Exception:
        pass

def load_character(name):
    path = os.path.join(BASE_DIR, "images", f"{name}.png")
    if not os.path.exists(path):
        return None
    img = Image.open(path).convert("RGBA")
    # 高さを画面の60%にリサイズ
    target_h = int(HEIGHT * 0.55)
    ratio = target_h / img.height
    target_w = int(img.width * ratio)
    return img.resize((target_w, target_h), Image.LANCZOS)

def make_frame_title():
    """タイトルカード"""
    img = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    draw_bg(img)
    draw = ImageDraw.Draw(img)

    # 暗いオーバーレイ
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 180))
    img = Image.composite(Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0)),
                          img, overlay.split()[3])
    draw = ImageDraw.Draw(img)

    # タイトル
    title_font = font(44)
    draw.text((WIDTH // 2, HEIGHT // 2 - 50), "珈琲のひみつ",
              fill=(245, 222, 179), font=title_font, anchor="mm")

    # サブタイトル
    sub_font = font(22)
    draw.text((WIDTH // 2, HEIGHT // 2 + 10), "ずんだもん ＆ 四国めたん",
              fill=(170, 170, 170), font=sub_font, anchor="mm")

    # クレジット
    credit_font = font(14)
    draw.text((WIDTH // 2, HEIGHT // 2 + 50),
              "音声: VOICEVOX ずんだもん・四国めたん / 音声API: ttsQuestV3",
              fill=(102, 102, 102), font=credit_font, anchor="mm")

    return img

def make_frame_line(line_idx, chara_imgs):
    """セリフ用フレーム"""
    line = SCRIPT[line_idx]
    speaker = line["s"]

    img = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    draw_bg(img)

    # キャラクター描画
    char_area_bottom = int(HEIGHT * 0.70)
    for key, pos_x in [("zunda", 0.12), ("metan", 0.88)]:
        cimg = chara_imgs.get(key)
        if cimg is None:
            continue
        is_speaking = (key == speaker)
        c = cimg.copy()
        if not is_speaking:
            # 暗く + グレースケール気味に
            from PIL import ImageEnhance
            c = ImageEnhance.Brightness(c).enhance(0.4)

        x = int(WIDTH * pos_x - c.width // 2)
        y_offset = -5 if is_speaking else 0
        y = char_area_bottom - c.height + y_offset
        img.paste(c, (x, y), c)

    # 字幕エリア（下部30%）
    draw = ImageDraw.Draw(img)
    sub_top = int(HEIGHT * 0.70)
    draw.rectangle([(0, sub_top), (WIDTH, HEIGHT - 20)], fill=(0, 0, 0, 210))
    # 実際にRGBなので半透明はできない。黒で塗る
    draw.rectangle([(0, sub_top), (WIDTH, HEIGHT - 20)], fill=(10, 10, 12))

    # 話者タグ
    tag_font = font(14)
    tag_text = NAMES[speaker]
    tag_color = COLORS[speaker]["tag"]
    tag_bbox = draw.textbbox((0, 0), tag_text, font=tag_font)
    tag_w = tag_bbox[2] - tag_bbox[0] + 12
    tag_h = tag_bbox[3] - tag_bbox[1] + 6
    draw.rectangle([(12, sub_top), (12 + tag_w, sub_top + tag_h)], fill=tag_color)
    draw.text((18, sub_top + 2), tag_text, fill=(255, 255, 255), font=tag_font)

    # 字幕テキスト
    sub_font = font(24)
    text_lines = line["t"].split("\n")
    total_text_h = len(text_lines) * 32
    sub_center_y = (sub_top + HEIGHT - 20) // 2
    y_start = sub_center_y - total_text_h // 2
    for i, tl in enumerate(text_lines):
        draw.text((WIDTH // 2, y_start + i * 32), tl,
                  fill=(255, 255, 255), font=sub_font, anchor="mm")

    # コントロールバー（下部20px）
    draw.rectangle([(0, HEIGHT - 20), (WIDTH, HEIGHT)], fill=(0, 0, 0))
    # プログレスバー
    progress = (line_idx + 1) / len(SCRIPT)
    bar_x = 40
    bar_w = WIDTH - 80
    draw.rectangle([(bar_x, HEIGHT - 12), (bar_x + bar_w, HEIGHT - 9)], fill=(51, 51, 51))
    # グラデーションバー
    filled_w = int(bar_w * progress)
    for x in range(filled_w):
        ratio = x / max(bar_w, 1)
        r = int(86 * (1 - ratio) + 244 * ratio)
        g = int(171 * (1 - ratio) + 143 * ratio)
        b = int(47 * (1 - ratio) + 177 * ratio)
        draw.line([(bar_x + x, HEIGHT - 12), (bar_x + x, HEIGHT - 9)], fill=(r, g, b))
    # ステップ表示
    step_font = font(11)
    draw.text((WIDTH - 35, HEIGHT - 15), f"{line_idx + 1}/{len(SCRIPT)}",
              fill=(102, 102, 102), font=step_font, anchor="mm")

    return img

def generate_frames(durations):
    """全フレームを生成し、各フレームの表示秒数を返す"""
    os.makedirs(FRAMES_DIR, exist_ok=True)

    chara_imgs = {}
    for name in ["zundamon", "metan"]:
        key = name.replace("mon", "a").replace("damon", "da")  # quick hack
        # Actually just use the right key
        pass
    chara_imgs["zunda"] = load_character("zundamon")
    chara_imgs["metan"] = load_character("metan")

    frame_info = []  # (path, duration_seconds)

    # タイトルフレーム
    title_path = os.path.join(FRAMES_DIR, "frame_000.png")
    make_frame_title().save(title_path)
    frame_info.append((title_path, TITLE_DUR))
    print(f"  frame_000: title ({TITLE_DUR}s)")

    # 各セリフフレーム
    for i in range(len(SCRIPT)):
        path = os.path.join(FRAMES_DIR, f"frame_{i + 1:03d}.png")
        make_frame_line(i, chara_imgs).save(path)
        dur = durations[i] + STEP_GAP  # 音声 + ギャップ
        frame_info.append((path, dur))
        print(f"  frame_{i + 1:03d}: {SCRIPT[i]['s']} ({dur:.1f}s)")

    return frame_info

# ─── 4. mp4 生成 ──────────────────────────────────────────
def build_video(merged_audio, frame_info):
    """フレーム + 音声を結合して mp4 を生成"""
    # ffmpeg concat demuxer 用のリスト（各フレームに duration 指定）
    frames_list = os.path.join(FRAMES_DIR, "frames.txt")
    with open(frames_list, "w") as f:
        for path, dur in frame_info:
            f.write(f"file '{path}'\n")
            f.write(f"duration {dur:.3f}\n")
        # 最後のフレームをもう一度（ffmpeg concat の仕様）
        f.write(f"file '{frame_info[-1][0]}'\n")

    subprocess.run(
        ["ffmpeg", "-y",
         "-f", "concat", "-safe", "0", "-i", frames_list,
         "-i", merged_audio,
         "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "128k",
         "-shortest",
         "-movflags", "+faststart",
         OUTPUT_FILE],
        check=True
    )
    print(f"\n  output: {OUTPUT_FILE}")
    dur = get_duration(OUTPUT_FILE)
    size_mb = os.path.getsize(OUTPUT_FILE) / 1024 / 1024
    print(f"  duration: {dur:.1f}s, size: {size_mb:.1f}MB")

# ─── メイン ───────────────────────────────────────────────
def main():
    global LOCAL_ONLY

    parser = argparse.ArgumentParser(description="珈琲のひみつ 動画ジェネレーター")
    parser.add_argument("--local", action="store_true",
                        help="API をスキップして espeak-ng のみで音声生成")
    args = parser.parse_args()
    LOCAL_ONLY = args.local

    print("=" * 50)
    print("珈琲のひみつ — 動画ジェネレーター")
    if LOCAL_ONLY:
        print("  (ローカルモード: espeak-ng 使用)")
    print("=" * 50)

    print("\n[1/4] 音声取得...")
    audio_paths = fetch_all_audio()

    failed = sum(1 for p in audio_paths if p is None)
    if failed:
        print(f"  WARNING: {failed}/{len(SCRIPT)} audio files failed")

    print("\n[2/5] 音声結合...")
    merged_audio, durations = merge_audio(audio_paths)

    print("\n[3/5] Web用音声書き出し...")
    export_web_audio(audio_paths)

    print("\n[4/5] フレーム生成...")
    frame_info = generate_frames(durations)

    print("\n[5/5] mp4 生成...")
    build_video(merged_audio, frame_info)

    print("\n  Done!")

if __name__ == "__main__":
    main()
