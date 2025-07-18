import os
import re
import sys
import time
import asyncio
import subprocess
from urllib.parse import unquote
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor

from telegram import Bot
from telegram.ext import Updater, CommandHandler
from telethon import TelegramClient
from telethon.tl.types import DocumentAttributeVideo

# Telegram Credentials
API_ID = 28071937
API_HASH = '1962c5ad0e8e8b8ee0864253bde77977'
PHONE_NUMBER = '+919302619108'
CHANNEL_USERNAME = '@uploadbot8924'
BOT_TOKEN = '7725920391:AAFPRTEPcjNOK62ZklxFZqTrBPw5uwPXNo4'
USER_ID = None  # Will be set on /start

bot = Bot(token=BOT_TOKEN)

def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "_", name)

def clean_extension(filename):
    name, ext = os.path.splitext(filename)
    while ext.lower() in [".mp4", ".web", ".webm", ".mkv"]:
        name, ext = os.path.splitext(name)
    return name + ".mp4"

def normalize_youtube_url(url):
    if "youtube.com/embed/" in url:
        return f"https://www.youtube.com/watch?v={url.split('/')[-1].split('?')[0]}"
    return url

def extract_links_titles(html_path):
    with open(html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")
    links = []
    for i, li in enumerate(soup.find_all("li"), start=1):
        a = li.find("a")
        if not a: continue
        url = None
        if a.has_attr('onclick'):
            match = re.search(r"playVideo\('([^']+)'\)", a['onclick'])
            if match: url = match.group(1)
        if not url and a.has_attr('href'):
            href = a['href']
            if any(x in href for x in ['.m3u8', '.pdf', 'youtube.com', 'youtu.be']):
                url = href
        if url:
            title = a.get_text(strip=True) or f"video_{i:03}"
            links.append((f"{i:03}_{title}", unquote(url)))
    return links

def get_video_duration(file_path):
    try:
        result = subprocess.run([
            'ffprobe', '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            file_path
        ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return int(float(result.stdout))
    except:
        return 0

def generate_thumbnail(video_path, output_path):
    try:
        subprocess.run([
            'ffmpeg', '-y', '-i', video_path,
            '-ss', '00:00:02.000', '-vframes', '1',
            output_path
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return os.path.exists(output_path)
    except:
        return False

async def upload_to_channel(client, filepath, caption, user_chat_id):
    file_size = os.path.getsize(filepath)
    file_name = os.path.basename(filepath)
    ext = os.path.splitext(file_name)[1].lower()
    is_video = ext in ['.mp4', '.mkv', '.mov', '.avi', '.flv']
    duration = get_video_duration(filepath)

    thumb_path = f"{filepath}.jpg"
    if is_video:
        generate_thumbnail(filepath, thumb_path)
        attributes = [DocumentAttributeVideo(duration=duration, w=720, h=1280, supports_streaming=True)]
    else:
        thumb_path = None
        attributes = None

    await client.send_message(CHANNEL_USERNAME, f"📤 {file_name} is uploading...")

    async def progress_callback(current, total):
        mb_done = f"{current / (1024*1024):.2f}MB"
        mb_total = f"{total / (1024*1024):.2f}MB"
        try:
            await bot.send_message(chat_id=user_chat_id, text=f"📤 Uploading: {file_name} - {mb_done}/{mb_total}", disable_notification=True)
        except:
            pass

    try:
        await client.send_file(
            entity=CHANNEL_USERNAME,
            file=filepath,
            caption=caption,
            thumb=thumb_path if os.path.exists(thumb_path) else None,
            attributes=attributes,
            force_document=not is_video,
            supports_streaming=is_video,
            progress_callback=progress_callback
        )
        os.remove(filepath)
        if os.path.exists(thumb_path):
            os.remove(thumb_path)
        await bot.send_message(chat_id=user_chat_id, text=f"✅ Uploaded: {file_name}")
    except Exception as e:
        await bot.send_message(chat_id=user_chat_id, text=f"❌ Upload failed: {file_name} - {e}")

def download_then_upload(title, url, output_dir, client, user_chat_id):
    try:
        filename = clean_extension(sanitize_filename(title) + ".mp4")
        output_path = os.path.join(output_dir, filename)
        if os.path.exists(output_path):
            return
        print(f"⬇️ Downloading: {filename}")

        if "youtube.com" in url or "youtu.be" in url:
            url = normalize_youtube_url(url)
            cmd = ["yt-dlp", "-f", "bestvideo+bestaudio/best", "-o", output_path, "--no-playlist"]
        elif url.endswith(".m3u8") or ".m3u8" in url:
            cmd = ["ffmpeg", "-y", "-i", url, "-c", "copy", "-bsf:a", "aac_adtstoasc", output_path]
        else:
            cmd = ["aria2c", url, "--dir", output_dir, "--out", filename, "--max-connection-per-server=16", "--split=16"]

        subprocess.run(cmd, check=True)

        if os.path.exists(output_path) and os.path.getsize(output_path) > 1024 * 100:
            asyncio.run(upload_to_channel(client, output_path, title, user_chat_id))
        else:
            print("❌ Invalid download.")
    except Exception as e:
        print(f"❌ Error: {e}")

def telegram_command_handler(update, context):
    global USER_ID
    USER_ID = update.effective_chat.id
    context.bot.send_message(chat_id=USER_ID, text="🤖 Bot is ready. Uploading will begin.")
    html_file = "index.html"
    if not os.path.exists(html_file):
        context.bot.send_message(chat_id=USER_ID, text="❌ index.html not found.")
        return
    links = extract_links_titles(html_file)
    output_dir = "downloads"
    os.makedirs(output_dir, exist_ok=True)

    client = TelegramClient("session", API_ID, API_HASH)
    asyncio.run(client.start(PHONE_NUMBER))

    for i, (title, url) in enumerate(links, start=1):
        download_then_upload(title, url, output_dir, client, USER_ID)

    asyncio.run(client.disconnect())
    context.bot.send_message(chat_id=USER_ID, text="✅ All done!")

def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", telegram_command_handler))
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
