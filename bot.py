import os
import logging
import signal
import sys
from datetime import datetime
import re
import requests
import tempfile
from urllib.parse import urlparse, parse_qs, quote_plus
import asyncio
import json
import sqlite3
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, Message
from pyrogram.enums import ChatAction, ParseMode
import yt_dlp
import subprocess
import sys
import os
from datetime import datetime, timedelta
import random
import time
import gc
from functools import lru_cache
import base64
import hashlib
from io import BytesIO
import shutil

# Создаём директорию для логов, если её нет
os.makedirs('/app/logs', exist_ok=True)

# Настройка логирования для продакшена
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('/app/logs/bot.log'),
        logging.StreamHandler(sys.stdout)  # Для отображения в логах Amvera
    ]
)
logger = logging.getLogger(__name__)

# Graceful shutdown для Amvera
def signal_handler(signum, frame):
    logger.info("Получен сигнал завершения, останавливаем бота...")
    sys.exit(0)

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

# Поиск ffmpeg
def find_ffmpeg():
    """Находит путь к ffmpeg"""
    ffmpeg_path = shutil.which('ffmpeg')
    if ffmpeg_path:
        return ffmpeg_path
    # Проверяем стандартные пути
    possible_paths = [
        'ffmpeg',
        'C:/ffmpeg/bin/ffmpeg.exe',
        '/usr/bin/ffmpeg',
        '/usr/local/bin/ffmpeg'
    ]
    for path in possible_paths:
        try:
            subprocess.run([path, '-version'], capture_output=True, timeout=5)
            return path
        except:
            continue
    return None

FFMPEG_PATH = find_ffmpeg()
print(f"🔍 Поиск ffmpeg: {'✅ Найден - ' + FFMPEG_PATH if FFMPEG_PATH else '❌ Не найден'}")

# Конфигурация
BOT_TOKEN = '7428917256:AAH9DDNSIlquNVw8f1hC35qmD8FpMa3LTCg'
WEBHOOK_URL = os.getenv('WEBHOOK_URL', '')
USE_PROXY = os.getenv('USE_PROXY', 'false').lower() == 'true'
PROXY_URL = os.getenv('PROXY_URL', '')  # Например: http://proxy:port
MAX_FILE_SIZE = int(os.getenv('MAX_FILE_SIZE', 200 * 1024 * 1024))  # 200MB общий лимит
MAX_FILE_SIZE_TIKTOK = int(os.getenv('MAX_FILE_SIZE_TIKTOK', 50 * 1024 * 1024))   # 50MB для TikTok
MAX_FILE_SIZE_YOUTUBE = int(os.getenv('MAX_FILE_SIZE_YOUTUBE', 200 * 1024 * 1024)) # 200MB для YouTube
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID', '')  # Для уведомлений админа
# Добавляем дефолтного админа, если переменная окружения пуста
ADMIN_CHAT_IDS = [int(id.strip()) for id in os.getenv('ADMIN_CHAT_IDS', '7850455999').split(',') if id.strip()]

STORAGE_CHANNEL_ID = "@dsds12f"  # username публичного канала для хранения файлов

async def upload_to_storage_channel(client, file_data, filename, caption=""):
    """Загружает файл в канал-хранилище и возвращает message_id"""
    try:
        file_obj = BytesIO(file_data)
        file_obj.name = filename
        
        # Проверяем доступность канала
        try:
            chat = await client.get_chat(STORAGE_CHANNEL_ID)
            logger.info(f"Канал найден: {chat.title if hasattr(chat, 'title') else 'Unknown'}")
        except Exception as e:
            logger.error(f"Канал недоступен: {e}")
            return None
        
        message = await client.send_video(
            chat_id=STORAGE_CHANNEL_ID,
            video=file_obj,
            caption=f"📁 {caption}",
            parse_mode=ParseMode.HTML
        )
        return message.id

    except Exception as e:
        logger.error(f"Ошибка загрузки в канал: {e}")
        return None

# Эмодзи для красивого дизайна
EMOJIS = {
    'fire': '🔥', 'star': '⭐', 'diamond': '💎', 'crown': '👑',
    'rocket': '🚀', 'magic': '✨', 'heart': '💖', 'lightning': '⚡',
    'trophy': '🏆', 'gem': '💠', 'sparkles': '🌟', 'rainbow': '🌈',
    'download': '📥', 'upload': '📤', 'video': '🎬', 'music': '🎵',
    'user': '👤', 'users': '👥', 'link': '🔗', 'time': '⏱️',
    'size': '💾', 'quality': '🎯', 'gift': '🎁', 'key': '🗝️',
    'unlock': '🔓', 'lock': '🔒', 'warning': '⚠️', 'error': '❌',
    'success': '✅', 'info': 'ℹ️', 'settings': '⚙️', 'stats': '📊'
}

class Database:
    def __init__(self, db_path='/app/data/bot_users.db'):
        self.db_path = db_path
        # Создаем директорию для БД если её нет
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.init_db()
    
    def init_db(self):
        """Инициализация базы данных"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Таблица пользователей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                referrer_id INTEGER,
                referral_count INTEGER DEFAULT 0,
                total_downloads INTEGER DEFAULT 0,
                premium_until DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_active DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Таблица загрузок
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS downloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                video_url TEXT,
                video_title TEXT,
                quality TEXT,
                file_size INTEGER,
                download_time REAL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def add_user(self, user_id, username=None, first_name=None, referrer_id=None):
        """Добавление нового пользователя"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR IGNORE INTO users (user_id, username, first_name, referrer_id)
            VALUES (?, ?, ?, ?)
        ''', (user_id, username, first_name, referrer_id))
        
        # Если есть реферер, увеличиваем его счетчик
        if referrer_id:
            cursor.execute('''
                UPDATE users SET referral_count = referral_count + 1 
                WHERE user_id = ?
            ''', (referrer_id,))
        
        conn.commit()
        conn.close()
    
    def get_user(self, user_id):
        """Получение данных пользователя"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM users WHERE user_id = ?
        ''', (user_id,))
        
        user = cursor.fetchone()
        conn.close()
        return user
    
    def update_user_activity(self, user_id):
        """Обновление активности пользователя"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE users SET last_active = CURRENT_TIMESTAMP 
            WHERE user_id = ?
        ''', (user_id,))
        
        conn.commit()
        conn.close()
    
    def add_download(self, user_id, video_url, video_title, quality, file_size, download_time):
        """Добавление записи о загрузке"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO downloads (user_id, video_url, video_title, quality, file_size, download_time)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, video_url, video_title, quality, file_size, download_time))
        
        # Обновляем счетчик загрузок пользователя
        cursor.execute('''
            UPDATE users SET total_downloads = total_downloads + 1 
            WHERE user_id = ?
        ''', (user_id,))
        
        conn.commit()
        conn.close()
    
    def get_stats(self):
        """Получение общей статистики"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM users')
        total_users = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM downloads')
        total_downloads = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM users WHERE date(last_active) = date("now")')
        active_today = cursor.fetchone()[0]
        
        conn.close()
        return {
            'total_users': total_users,
            'total_downloads': total_downloads,
            'active_today': active_today
        }

class TikTokDownloader:
    def __init__(self):
        self.session = requests.Session()
        if USE_PROXY and PROXY_URL:
            self.session.proxies = {
                'http': PROXY_URL,
                'https': PROXY_URL
            }
        
        # Улучшенные заголовки
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Sec-Ch-Ua': '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'cross-origin',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache'
        })

    def get_quality_options(self, user_referrals, is_admin, platform):
        """Получение опций качества в зависимости от платформы"""
        if platform == 'youtube':
            return {
                '360p': {
                    'format': 'bestvideo[height<=360]+bestaudio/best[height<=360]',
                    'emoji': '📱',
                    'required_refs': 0
                },
                '480p': {
                    'format': 'bestvideo[height<=480]+bestaudio/best[height<=480]',
                    'emoji': '💻',
                    'required_refs': 0
                },
                '720p': {
                    'format': 'bestvideo[height<=720]+bestaudio/best[height<=720]',
                    'emoji': '🖥️',
                    'required_refs': 0
                },
                '1080p': {
                    'format': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]',
                    'emoji': '🎬',
                    'required_refs': 3
                },
                'best': {
                    'format': 'bestvideo+bestaudio/best',
                    'emoji': '👑',
                    'required_refs': 3
                },
                'audio_only': {
                    'format': 'bestaudio[ext=m4a]/bestaudio',
                    'emoji': '🎵',
                    'required_refs': 0
                }
            }
        else:  # TikTok
            return {
                'default': {'format': 'best[height<=720]/best', 'emoji': '🎬', 'required_refs': 0}
            }
    
    @lru_cache(maxsize=100)
    def extract_video_url(self, text):
        """Извлекает URL TikTok или YouTube из текста (с кешированием)"""
        tiktok_patterns = [
            r'https?://(?:www\.)?tiktok\.com/@[\w.-]+/video/\d+',
            r'https?://vm\.tiktok\.com/[\w.-]+',
            r'https?://(?:www\.)?tiktok\.com/t/[\w.-]+',
            r'https?://(?:m\.)?tiktok\.com/@[\w.-]+/video/\d+',
            r'https?://vt\.tiktok\.com/[\w.-]+'
        ]
        youtube_patterns = [
            r'https?://(?:www\.)?youtube\.com/watch\?v=[\w-]+',
            r'https?://youtu\.be/[\w-]+',
            r'https?://(?:www\.)?youtube\.com/shorts/[\w-]+',
            r'https?://m\.youtube\.com/watch\?v=[\w-]+'
        ]
        all_patterns = tiktok_patterns + youtube_patterns
        for pattern in all_patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(0)
        return None
    
    def resolve_tiktok_url(self, url):
        """Разворачивание коротких ссылок"""
        try:
            if any(short in url for short in ['vm.tiktok.com', '/t/', 'vt.tiktok.com']):
                response = self.session.head(url, allow_redirects=True, timeout=15)
                return response.url
            return url
        except Exception as e:
            logger.error(f"Ошибка при развороте URL: {e}")
            return url
    
    async def get_video_info(self, url):
        """Получение информации о TikTok видео через yt-dlp"""
        await asyncio.sleep(random.uniform(0.5, 2))
        try:
            # Используем yt-dlp для получения информации
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'socket_timeout': 30,
                'retries': 2
            }
            def extract_info():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    return ydl.extract_info(url, download=False)
            info = await asyncio.get_event_loop().run_in_executor(None, extract_info)
            if info:
                return {
                    'title': info.get('title', 'TikTok Video')[:100],
                    'uploader': info.get('uploader', 'Unknown'),
                    'duration': info.get('duration', 30),
                    'view_count': info.get('view_count', 0),
                    'like_count': info.get('like_count', 0),
                    'comment_count': info.get('comment_count', 0),
                    'description': info.get('description', ''),
                    'upload_date': str(info.get('upload_date', '')),
                    'webpage_url': url,
                    'thumbnail': info.get('thumbnail', ''),
                    'formats_available': len(info.get('formats', [])),
                    'width': info.get('width', 1080),
                    'height': info.get('height', 1920),
                    'fps': info.get('fps', 30),
                    'filesize': info.get('filesize', 0)
                }
        except Exception as e:
            logger.error(f"yt-dlp info extraction failed: {e}")
        # Fallback - возвращаем базовую информацию
        return {
            'title': 'TikTok Video',
            'uploader': 'Unknown',
            'duration': 30,
            'view_count': 1000,
            'like_count': 100,
            'comment_count': 10,
            'description': '',
            'upload_date': '',
            'webpage_url': url,
            'thumbnail': '',
            'formats_available': 1,
            'width': 1080,
            'height': 1920,
            'fps': 30,
            'filesize': 5000000
        }
    
    async def download_with_quality(self, url, quality_format):
        """Скачивание TikTok видео через yt-dlp"""
        await asyncio.sleep(random.uniform(0.5, 2))
        try:
            # Пробуем скачать через yt-dlp
            ydl_opts = {
                'format': 'best[height<=1080]/best',
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'socket_timeout': 60,
                'retries': 3,
                'outtmpl': '%(title).50s.%(ext)s',
                'prefer_ffmpeg': False,
                'writesubtitles': False,
                'writeautomaticsub': False
            }
            def download_video():
                with tempfile.TemporaryDirectory() as temp_dir:
                    ydl_opts['outtmpl'] = os.path.join(temp_dir, '%(title).50s.%(ext)s')
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([url])
                    # Найти скачанный файл
                    files = os.listdir(temp_dir)
                    if not files:
                        return None, None, "Файл не был скачан"
                    # Предпочитаем mp4 файлы
                    video_files = [f for f in files if f.endswith(('.mp4', '.webm', '.mkv'))]
                    target_file = video_files[0] if video_files else files[0]
                    video_path = os.path.join(temp_dir, target_file)
                    file_size = os.path.getsize(video_path)
                    # Проверяем размер файла
                    if file_size > MAX_FILE_SIZE_TIKTOK:
                        return None, None, f'Файл слишком большой: {file_size/1024/1024:.1f}MB (лимит: {MAX_FILE_SIZE_TIKTOK/1024/1024:.0f}MB)'
                    # Читаем файл
                    with open(video_path, 'rb') as f:
                        video_data = f.read()
                    # Создаем безопасное имя файла
                    safe_filename = re.sub(r'[^-\u007F\w\s-]', '_', target_file)
                    if not safe_filename.endswith('.mp4'):
                        safe_filename = f"{safe_filename.rsplit('.', 1)[0]}.mp4"
                    return video_data, safe_filename, None
            video_data, filename, error = await asyncio.get_event_loop().run_in_executor(None, download_video)
            if error:
                return {'success': False, 'error': error}
            if video_data and filename:
                return {
                    'success': True,
                    'data': video_data,
                    'filename': filename,
                    'size': len(video_data)
                }
        except Exception as e:
            logger.error(f"yt-dlp TikTok download failed: {e}")
        # Fallback - попробуем старый API метод
        try:
            logger.info("Пробуем fallback API метод...")
            return await self.fallback_api_download(url)
        except Exception as e:
            logger.error(f"Fallback метод не сработал: {e}")
            return {'success': False, 'error': 'Все методы скачивания не сработали'}
    
    async def fallback_api_download(self, url):
        """Резервный метод скачивания через API"""
        try:
            # Пробуем ssstik.io
            api_url = "https://ssstik.io/abc"
            data = {
                'id': url,
                'locale': 'en',
                'tt': 'dQw4w9W'  # Базовый токен
            }
            
            response = self.session.post(api_url, data=data, timeout=30)
            
            if response.status_code == 200:
                # Парсим ответ (упрощенный парсинг)
                content = response.text
                
                # Ищем ссылку на видео в ответе
                import re
                video_url_match = re.search(r'href="([^"]*)" class="[^"]*download[^"]*"', content)
                if video_url_match:
                    video_url = video_url_match.group(1)
                    
                    # Скачиваем видео
                    video_response = self.session.get(video_url, timeout=120)
                    if video_response.status_code == 200:
                        filename = f"tiktok_video_{int(time.time())}.mp4"
                        return {
                            'success': True,
                            'data': video_response.content,
                            'filename': filename,
                            'size': len(video_response.content)
                        }
            
            return {'success': False, 'error': 'API не вернул корректные данные'}
            
        except Exception as e:
            logger.error(f"Fallback API error: {e}")
            return {'success': False, 'error': f'Fallback ошибка: {str(e)[:100]}'}

    def detect_platform(self, url):
        """Определение платформы видео"""
        if any(domain in url for domain in ['tiktok.com', 'vm.tiktok.com', 'vt.tiktok.com']):
            return 'tiktok'
        elif any(domain in url for domain in ['youtube.com', 'youtu.be']):
            return 'youtube'
        return None

class YouTubeDownloader:
    def __init__(self):
        self.ydl_opts_base = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'ignoreerrors': False,
            'socket_timeout': 30,
            'retries': 2,
            'geo_bypass': True,
            'prefer_ffmpeg': True,
            'merge_output_format': 'mp4',
            'writesubtitles': False,
            'writeautomaticsub': False,
        }
        if FFMPEG_PATH:
            self.ydl_opts_base['ffmpeg_location'] = FFMPEG_PATH
            print(f"✅ Используем ffmpeg: {FFMPEG_PATH}")
        else:
            print("⚠️ ffmpeg не найден, используем форматы без конвертации")

    async def get_video_info(self, url):
        """Получение информации о YouTube видео"""
        opts = self.ydl_opts_base.copy()
        try:
            def extract_info():
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    # Отладочная информация о доступных форматах
                    if info and 'formats' in info:
                        logger.info(f"Доступные форматы для видео:")
                        for fmt in info['formats'][:10]:  # Показать первые 10
                            height = fmt.get('height', 'N/A')
                            ext = fmt.get('ext', 'N/A')
                            format_id = fmt.get('format_id', 'N/A')
                            logger.info(f"  {format_id}: {height}p {ext}")
                    return info
            info = await asyncio.get_event_loop().run_in_executor(None, extract_info)
            return info
        except Exception as e:
            logger.error(f"YouTube info error: {e}")
            return None

    async def download_with_quality(self, url, quality_format):
        """Скачивание YouTube видео"""
        opts = self.ydl_opts_base.copy()
        if FFMPEG_PATH:
            opts.update({
                'format': quality_format,
                'prefer_ffmpeg': True,
                'merge_output_format': 'mp4',
                'postprocessors': [{
                    'key': 'FFmpegVideoConvertor',
                    'preferedformat': 'mp4',
                }]
            })
        else:
            # Без ffmpeg - выбираем готовые mp4 форматы
            safe_format = quality_format.replace('bestvideo+bestaudio', 'best[ext=mp4]')
            opts.update({
                'format': f'{safe_format}/best[ext=mp4]/best',
                'prefer_ffmpeg': False,
                'postprocessors': []
            })
        logger.info(f"Скачиваем с форматом: {quality_format}")
        try:
            def download_video():
                with tempfile.TemporaryDirectory() as temp_dir:
                    opts['outtmpl'] = os.path.join(temp_dir, '%(title).50s.%(ext)s')
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        info = ydl.extract_info(url, download=False)
                        if info and 'formats' in info:
                            logger.info("Доступные форматы:")
                            for fmt in sorted(info['formats'], key=lambda x: x.get('height', 0) or 0, reverse=True)[:10]:
                                height = fmt.get('height') or 'N/A'
                                filesize = fmt.get('filesize')
                                size_str = f"{filesize/1024/1024:.1f}MB" if filesize else "неизв."
                                vcodec = fmt.get('vcodec', 'N/A')[:10]
                                acodec = fmt.get('acodec', 'N/A')[:10]
                                format_id = fmt.get('format_id', 'N/A')
                                logger.info(f"  {format_id}: {height}p, {size_str}, v:{vcodec}, a:{acodec}")
                        ydl.download([url])
                    files = os.listdir(temp_dir)
                    mp4_files = [f for f in files if f.endswith('.mp4')]
                    target_file = mp4_files[0] if mp4_files else files[0]
                    video_path = os.path.join(temp_dir, target_file)
                    file_size = os.path.getsize(video_path)
                    logger.info(f"Итоговый файл: {target_file}, размер: {file_size/1024/1024:.1f}MB")
                    # Проверяем размер файла
                    if file_size > MAX_FILE_SIZE_YOUTUBE:
                        return None, None, f'Файл слишком большой: {file_size/1024/1024:.1f}MB (лимит: {MAX_FILE_SIZE_YOUTUBE/1024/1024:.0f}MB)'
                    with open(video_path, 'rb') as f:
                        video_data = f.read()
                    return video_data, target_file, None
            video_data, filename, error = await asyncio.get_event_loop().run_in_executor(None, download_video)
            if error:
                return {'success': False, 'error': error}
            if video_data and filename:
                return {
                    'success': True,
                    'data': video_data,
                    'filename': filename
                }
        except Exception as e:
            logger.error(f"YouTube download error: {e}")
        return {'success': False, 'error': 'Не удалось скачать видео с YouTube'}

# Глобальные объекты
db = Database()
downloader = TikTokDownloader()
youtube_downloader = YouTubeDownloader()
bot_start_time = datetime.now()

API_ID = 28553397
API_HASH = "0502f27656ae614806a1f24264136fb0"

app = Client(
    "downloader_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

user_data_dict = {}

def generate_referral_link(user_id, bot_username):
    """Генерация реферальной ссылки"""
    try:
        encoded_id = base64.b64encode(str(user_id).encode()).decode()
        return f"https://t.me/{bot_username}?start=ref_{encoded_id}"
    except Exception as e:
        logger.error(f"Ошибка генерации реферальной ссылки: {e}")
        return f"https://t.me/{bot_username}"

def decode_referral_code(code):
    """Декодирование реферального кода"""
    try:
        if code.startswith('ref_'):
            encoded_id = code[4:]  # Убираем 'ref_'
            decoded_id = base64.b64decode(encoded_id.encode()).decode()
            return int(decoded_id)
    except Exception as e:
        logger.error(f"Ошибка декодирования реферального кода: {e}")
        return None

def is_admin(user_id):
    """Проверка является ли пользователь админом"""
    return user_id in ADMIN_CHAT_IDS

@app.on_message(filters.command("start"))
async def start(client, message):
    """Команда /start с реферальной системой"""
    user = message.from_user
    args = message.text.split()
    me = await client.get_me()
    bot_username = me.username
    
    # Проверяем реферальный код
    referrer_id = None
    if len(args) > 1 and args[1].startswith('ref_'):
        referrer_id = decode_referral_code(args[1])
        if referrer_id == user.id:
            referrer_id = None  # Нельзя приглашать самого себя
    
    # Добавляем пользователя в БД
    db.add_user(user.id, user.username, user.first_name, referrer_id)
    
    # Получаем данные пользователя
    user_data = db.get_user(user.id)
    referral_count = user_data[4] if user_data else 0
    
    welcome_text = f"""
{EMOJIS['fire']} <b>TikTok Downloader Premium</b> {EMOJIS['fire']}

{EMOJIS['sparkles']} Добро пожаловать, <b>{user.first_name}</b>!

{EMOJIS['diamond']} <b>Ваш статус:</b>
{EMOJIS['users']} Приглашено друзей: <b>{referral_count}</b>
{EMOJIS['quality']} Доступные качества:
• 360p/480p/720p - {EMOJIS['success']} <i>Доступно всем</i>
• 1080p - {"✅ <i>Доступно</i>" if referral_count >= 3 or is_admin(user.id) else "🔒 <i>Нужно 3 друга</i>"}

{EMOJIS['gift']} <b>Пригласи друзей и получи:</b>
{EMOJIS['diamond']} 3 друга = 1080p качество

{EMOJIS['rocket']} <b>Как пользоваться:</b>
1️⃣ Отправь ссылку на TikTok или YouTube видео
2️⃣ Выбери качество
3️⃣ Получи видео без водяных знаков!

{EMOJIS['link']} <b>Твоя реферальная ссылка:</b>
<code>{generate_referral_link(user.id, bot_username)}</code>
"""
    
    if referrer_id:
        welcome_text += f"\n{EMOJIS['heart']} <i>Спасибо за переход по реферальной ссылке!</i>"
    
    referral_link = generate_referral_link(user.id, bot_username)
    share_url = f"https://t.me/share/url?url={quote_plus(referral_link)}&text={quote_plus('Скачивай TikTok и YouTube видео без водяных знаков!')}"
    
    keyboard = [
        [InlineKeyboardButton(f"{EMOJIS['users']} Пригласить друзей", url=share_url)],
        [InlineKeyboardButton(f"{EMOJIS['stats']} Статистика", callback_data="stats"),
         InlineKeyboardButton(f"{EMOJIS['info']} Помощь", callback_data="help")]
    ]
    
    await message.reply_text(
        welcome_text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True
    )

async def quality_selection(client, message, tiktok_url: str, video_info: dict):
    """Выбор качества видео для TikTok"""
    user = message.from_user
    user_data = db.get_user(user.id)
    referral_count = user_data[4] if user_data else 0
    is_user_admin = is_admin(user.id)
    
    quality_options = downloader.get_quality_options(referral_count, is_user_admin, 'tiktok')
    
    text = f"""
{EMOJIS['video']} <b>TikTok видео найдено:</b>

{EMOJIS['music']} <b>Название:</b> {video_info.get('title', 'TikTok Video')}
{EMOJIS['user']} <b>Автор:</b> @{video_info.get('uploader', 'Unknown')}
{EMOJIS['time']} <b>Длительность:</b> {video_info.get('duration', 0)}с
👀 <b>Просмотры:</b> {video_info.get('view_count', 0):,}
❤️ <b>Лайки:</b> {video_info.get('like_count', 0):,}
💬 <b>Комментарии:</b> {video_info.get('comment_count', 0):,}
📐 <b>Разрешение:</b> {video_info.get('width', 0)}x{video_info.get('height', 0)}
🎞️ <b>FPS:</b> {video_info.get('fps', 0)}
📊 <b>Форматов доступно:</b> {video_info.get('formats_available', 0)}

{EMOJIS['quality']} <b>Скачать видео без водяных знаков:</b>
"""
    
    # Создаем безопасный callback data
    try:
        encoded_url = base64.b64encode(tiktok_url.encode('utf-8')).decode('utf-8')
        if len(encoded_url) > 50:
            url_hash = hashlib.md5(tiktok_url.encode()).hexdigest()[:16]
            if user.id not in user_data_dict:
                user_data_dict[user.id] = {}
            user_data_dict[user.id]['current_video_url'] = tiktok_url
            user_data_dict[user.id]['video_info'] = video_info
            encoded_url = url_hash
    except Exception as e:
        logger.error(f"Ошибка кодирования URL: {e}")
        encoded_url = "error"
    
    keyboard = [[InlineKeyboardButton(
        f"🎬 Скачать TikTok видео",
        callback_data=f"dl_default_{encoded_url}"
    )]]
    
    keyboard.append([InlineKeyboardButton(f"{EMOJIS['error']} Отмена", callback_data="cancel")])
    
    # Сохраняем данные в контексте
    if user.id not in user_data_dict:
        user_data_dict[user.id] = {}
    user_data_dict[user.id]['current_video_url'] = tiktok_url
    user_data_dict[user.id]['video_info'] = video_info
    
    await message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

@app.on_callback_query()
async def callback_query_handler(client, query):
    data = query.data
    user = query.from_user
    await query.answer()
    
    try:
        if data == "stats":
            await show_user_stats(client, query)
        elif data == "help":
            await show_help(client, query)
        elif data == "cancel":
            await query.edit_message_text(f"{EMOJIS['success']} Операция отменена")
        elif data.startswith("locked_"):
            quality = data.split("_")[1]
            me = await client.get_me()
            bot_username = me.username
            await query.edit_message_text(
                f"{EMOJIS['lock']} <b>Качество {quality} заблокировано!</b>\n\n"
                f"{EMOJIS['gift']} Пригласите минимум 3 друзей для разблокировки 1080p\n"
                f"{EMOJIS['link']} Ваша реферальная ссылка:\n"
                f"<code>{generate_referral_link(user.id, bot_username)}</code>",
                parse_mode=ParseMode.HTML
            )
        elif data.startswith("dl_"):
            await process_download(client, query)
        elif data.startswith("yt_"):
            await process_youtube_download(client, query)
    except Exception as e:
        logger.error(f"Ошибка в callback_query_handler: {e}")
        await query.edit_message_text(
            f"{EMOJIS['error']} <b>Системная ошибка</b>\n\n"
            f"Попробуйте другую ссылку или повторите позже",
            parse_mode=ParseMode.HTML
        )

async def show_user_stats(client, query):
    """Показ статистики пользователя"""
    user = query.from_user
    user_data = db.get_user(user.id)
    me = await client.get_me()
    bot_username = me.username
    
    if user_data:
        referral_count = user_data[4]
        total_downloads = user_data[5]
        created_at = datetime.fromisoformat(user_data[7])
        days_with_bot = (datetime.now() - created_at).days
        
        text = f"""
{EMOJIS['stats']} <b>Ваша статистика:</b>

{EMOJIS['user']} <b>Имя:</b> {user.first_name}
{EMOJIS['users']} <b>Приглашено друзей:</b> {referral_count}
{EMOJIS['download']} <b>Скачано видео:</b> {total_downloads}
📅 <b>С нами:</b> {days_with_bot} дней

{EMOJIS['quality']} <b>Доступные качества:</b>
• 360p/480p/720p: {EMOJIS['success']}
• 1080p: {"✅" if referral_count >= 3 or is_admin(user.id) else "🔒"}

{EMOJIS['gift']} <b>До 1080p осталось:</b> {max(0, 3 - referral_count)} друзей
"""
    else:
        text = f"{EMOJIS['error']} Ошибка получения статистики"
    
    referral_link = generate_referral_link(user.id, bot_username)
    share_url = f"https://t.me/share/url?url={quote_plus(referral_link)}&text={quote_plus('Скачивай видео без водяных знаков!')}"
    keyboard = [[InlineKeyboardButton(f"{EMOJIS['users']} Пригласить друзей", url=share_url)]]
    
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_help(client, query):
    """Показ справки"""
    text = f"""
{EMOJIS['info']} <b>Помощь по использованию бота:</b>

{EMOJIS['rocket']} <b>Как скачать видео:</b>
1️⃣ Скопируйте ссылку на TikTok или YouTube видео
2️⃣ Отправьте ее боту
3️⃣ Выберите качество
4️⃣ Получите видео без водяных знаков!

{EMOJIS['link']} <b>Поддерживаемые ссылки:</b>
<b>TikTok:</b>
• tiktok.com/@user/video/123...
• vm.tiktok.com/abc123
• vt.tiktok.com/xyz789
• m.tiktok.com/...

<b>YouTube:</b>
• youtube.com/watch?v=...
• youtu.be/...
• youtube.com/shorts/...

{EMOJIS['gift']} <b>Реферальная система:</b>
• 3 друга = доступ к 1080p
• 720p и ниже доступны всем!
• Делитесь ссылкой и получайте бонусы!

{EMOJIS['quality']} <b>Качества видео:</b>
📱 360p - базовое качество
💻 480p - стандартное качество  
🖥️ 720p - HD качество (доступно всем)
🎬 1080p - Full HD (3+ друга)
🎵 Только аудио (MP3) - для YouTube

{EMOJIS['warning']} <b>Ограничения:</b>
• Только публичные видео
• YouTube: максимум {MAX_FILE_SIZE_YOUTUBE/1024/1024:.0f}MB
• TikTok: максимум {MAX_FILE_SIZE_TIKTOK/1024/1024:.0f}MB
• Без нарушения авторских прав
"""
    
    keyboard = [[InlineKeyboardButton(f"{EMOJIS['rocket']} Начать скачивание", callback_data="cancel")]]
    
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def process_download(client, query):
    """Обработка скачивания TikTok видео"""
    user = query.from_user
    try:
        data_parts = query.data.split('_')
        if len(data_parts) < 3:
            await query.edit_message_text(f"{EMOJIS['error']} Ошибка формата данных")
            return
        quality = data_parts[1]
        encoded_url = '_'.join(data_parts[2:])
        # Получаем URL
        if len(encoded_url) <= 16:  # Это хеш
            if user.id in user_data_dict:
                tiktok_url = user_data_dict[user.id].get('current_video_url')
                if not tiktok_url:
                    await query.edit_message_text(f"{EMOJIS['error']} Ссылка не найдена. Отправьте ссылку заново.")
                    return
            else:
                await query.edit_message_text(f"{EMOJIS['error']} Данные не найдены. Отправьте ссылку заново.")
                return
        else:
            try:
                tiktok_url = base64.b64decode(encoded_url.encode()).decode('utf-8')
            except Exception:
                await query.edit_message_text(f"{EMOJIS['error']} Ошибка обработки ссылки")
                return
    except Exception as e:
        logger.error(f"Ошибка парсинга callback data: {e}")
        await query.edit_message_text(f"{EMOJIS['error']} Ошибка обработки запроса")
        return
    await query.edit_message_text(
        f"{EMOJIS['download']} <b>Скачиваю TikTok видео...</b>\n"
        f"{EMOJIS['time']} Пожалуйста, подождите...",
        parse_mode=ParseMode.HTML
    )
    # Обновляем активность пользователя
    db.update_user_activity(user.id)
    try:
        start_time = time.time()
        # Получаем формат качества
        user_data = db.get_user(user.id)
        referral_count = user_data[4] if user_data else 0
        quality_options = downloader.get_quality_options(referral_count, is_admin(user.id), 'tiktok')
        if quality not in quality_options:
            await query.edit_message_text(f"{EMOJIS['error']} Качество недоступно")
            return
        quality_format = quality_options[quality]['format']
        result = await downloader.download_with_quality(tiktok_url, quality_format)
        if result['success']:
            download_time = time.time() - start_time
            video_info = user_data_dict[user.id].get('video_info', {}) if user.id in user_data_dict else {}
            file_size_mb = len(result['data']) / (1024 * 1024)
            caption = f"""
{EMOJIS['success']} <b>TikTok видео скачано!</b>

📝 <b>Название:</b> {video_info.get('title', 'TikTok Video')[:50]}
{EMOJIS['user']} <b>Автор:</b> {video_info.get('uploader', 'Unknown')}
{EMOJIS['size']} <b>Размер:</b> {file_size_mb:.1f}MB
⚡ <b>Время:</b> {download_time:.1f}с
"""
            # Пытаемся загрузить в канал-хранилище
            await query.edit_message_text(
                f"{EMOJIS['upload']} Загружаю в хранилище...",
                parse_mode=ParseMode.HTML
            )
            message_id = await upload_to_storage_channel(client, result['data'], result['filename'], caption)
            if message_id:
                # Успешно загружено в канал - копируем содержимое
                try:
                    storage_message = await client.get_messages(STORAGE_CHANNEL_ID, message_id)
                    await client.send_video(
                        chat_id=user.id,
                        video=storage_message.video.file_id,
                        caption=caption,
                        parse_mode=ParseMode.HTML
                    )
                    db.add_download(user.id, tiktok_url, video_info.get('title', 'TikTok Video'), 'default', len(result['data']), download_time)
                    await query.message.delete()
                except Exception as e:
                    logger.error(f"Ошибка копирования из канала: {e}")
                    # Если не удалось скопировать из канала, отправляем напрямую
                    file_obj = BytesIO(result['data'])
                    file_obj.name = result['filename']
                    await client.send_video(
                        chat_id=user.id,
                        video=file_obj,
                        caption=caption,
                        parse_mode=ParseMode.HTML
                    )
                    db.add_download(user.id, tiktok_url, video_info.get('title', 'TikTok Video'), 'default', len(result['data']), download_time)
                    await query.message.delete()
            else:
                # Канал недоступен - отправляем напрямую
                await query.edit_message_text("⚠️ Канал недоступен, отправляю напрямую...")
                file_obj = BytesIO(result['data'])
                file_obj.name = result['filename']
                await client.send_video(
                    chat_id=user.id,
                    video=file_obj,
                    caption=caption,
                    parse_mode=ParseMode.HTML
                )
                db.add_download(user.id, tiktok_url, video_info.get('title', 'TikTok Video'), 'default', len(result['data']), download_time)
                await query.message.delete()
        else:
            await query.edit_message_text(
                f"{EMOJIS['error']} <b>Не удалось скачать видео</b>\n\n"
                f"📝 Причина: {result.get('error', 'Неизвестная ошибка')}\n\n"
                f"{EMOJIS['info']} <b>Возможные решения:</b>\n"
                f"• Проверьте, что видео публичное\n"
                f"• Попробуйте другую ссылку TikTok\n"
                f"• Повторите попытку через 1-2 минуты\n"
                f"• Убедитесь что видео не удалено\n\n"
                f"{EMOJIS['sparkles']} <i>Отправьте новую ссылку для скачивания</i>",
                parse_mode=ParseMode.HTML
            )
    except Exception as e:
        logger.error(f"Критическая ошибка скачивания TikTok: {e}")
        await query.edit_message_text(
            f"{EMOJIS['error']} <b>Системная ошибка</b>\n\n"
            f"Попробуйте другую ссылку или повторите позже",
            parse_mode=ParseMode.HTML
        )

async def process_youtube_download(client, query):
    """Обработка скачивания YouTube видео"""
    user = query.from_user
    try:
        data_parts = query.data.split('_')
        quality = data_parts[1]
        encoded_url = '_'.join(data_parts[2:])
        
        # Проверка доступа к premium качествам
        if quality in ['1080p', 'best']:
            user_data = db.get_user(user.id)
            referral_count = user_data[4] if user_data else 0
            if not is_admin(user.id) and referral_count < 3:
                await query.edit_message_text(
                    f"{EMOJIS['lock']} <b>Качество {quality} заблокировано!</b>\n\n"
                    f"Пригласите {3 - referral_count} друзей для разблокировки!",
                    parse_mode=ParseMode.HTML
                )
                return
        
        if len(encoded_url) <= 16:
            if user.id in user_data_dict:
                youtube_url = user_data_dict[user.id].get('current_video_url')
            else:
                youtube_url = None
        else:
            try:
                youtube_url = base64.b64decode(encoded_url.encode()).decode('utf-8')
            except:
                youtube_url = None
        
        if not youtube_url:
            await query.edit_message_text(f"{EMOJIS['error']} Ссылка не найдена")
            return
            
    except Exception as e:
        logger.error(f"Ошибка парсинга YouTube callback: {e}")
        await query.edit_message_text(f"{EMOJIS['error']} Ошибка обработки")
        return
    
    await query.edit_message_text(
        f"{EMOJIS['download']} <b>Скачиваю YouTube видео...</b>\n"
        f"{EMOJIS['quality']} Качество: {quality}\n"
        f"{EMOJIS['time']} Пожалуйста, подождите...",
        parse_mode=ParseMode.HTML
    )
    
    try:
        start_time = time.time()
        
        user_data = db.get_user(user.id)
        referral_count = user_data[4] if user_data else 0
        quality_options = downloader.get_quality_options(referral_count, is_admin(user.id), 'youtube')
        
        if quality not in quality_options:
            await query.edit_message_text(f"{EMOJIS['error']} Качество недоступно")
            return
        
        quality_format = quality_options[quality]['format']
        logger.info(f"Используемый формат для {quality}: {quality_format}")
        
        result = await youtube_downloader.download_with_quality(youtube_url, quality_format)
        
        if result['success']:
            download_time = time.time() - start_time
            video_info = user_data_dict[user.id].get('video_info', {}) if user.id in user_data_dict else {}
            file_size_mb = len(result['data']) / (1024 * 1024)
            
            caption = f"""
{EMOJIS['success']} <b>YouTube видео скачано!</b>

📝 <b>Название:</b> {video_info.get('title', 'YouTube Video')[:50]}
{EMOJIS['user']} <b>Канал:</b> {video_info.get('uploader', 'Unknown')}
{EMOJIS['quality']} <b>Качество:</b> {quality}
{EMOJIS['size']} <b>Размер:</b> {file_size_mb:.1f}MB
⚡ <b>Время:</b> {download_time:.1f}с
"""
            
            # Пытаемся загрузить в канал-хранилище
            await query.edit_message_text(
                f"{EMOJIS['upload']} Загружаю в хранилище...",
                parse_mode=ParseMode.HTML
            )
            
            message_id = await upload_to_storage_channel(client, result['data'], result['filename'], caption)
            
            if message_id:
                # Успешно загружено в канал - копируем содержимое
                try:
                    storage_message = await client.get_messages(STORAGE_CHANNEL_ID, message_id)
                    await client.send_video(
                        chat_id=user.id,
                        video=storage_message.video.file_id,
                        caption=caption,
                        parse_mode=ParseMode.HTML
                    )
                    db.add_download(user.id, youtube_url, video_info.get('title', 'YouTube Video'), quality, len(result['data']), download_time)
                    await query.message.delete()
                except Exception as e:
                    logger.error(f"Ошибка копирования из канала: {e}")
                    # Если не удалось скопировать из канала, отправляем напрямую
                    file_obj = BytesIO(result['data'])
                    file_obj.name = result['filename']
                    await client.send_video(
                        chat_id=user.id,
                        video=file_obj,
                        caption=caption,
                        parse_mode=ParseMode.HTML
                    )
                    db.add_download(user.id, youtube_url, video_info.get('title', 'YouTube Video'), quality, len(result['data']), download_time)
                    await query.message.delete()

            else:
                # Канал недоступен - отправляем напрямую
                await query.edit_message_text("⚠️ Канал недоступен, отправляю напрямую...")
                
                file_obj = BytesIO(result['data'])
                file_obj.name = result['filename']
                
                await client.send_video(
                    chat_id=user.id,
                    video=file_obj,
                    caption=caption,
                    parse_mode=ParseMode.HTML
                )
                db.add_download(user.id, youtube_url, video_info.get('title', 'YouTube Video'), quality, len(result['data']), download_time)
                await query.message.delete()
            
        else:
            await query.edit_message_text(
                f"{EMOJIS['error']} <b>Не удалось скачать видео</b>\n"
                f"Причина: {result.get('error', 'Неизвестная ошибка')}",
                parse_mode=ParseMode.HTML
            )
            
    except Exception as e:
        logger.error(f"YouTube download error: {e}")
        await query.edit_message_text(
            f"{EMOJIS['error']} Ошибка скачивания YouTube видео",
            parse_mode=ParseMode.HTML
        )

@app.on_message(filters.command("adminstats"))
async def admin_stats(client, message):
    """Админская статистика (команда /adminstats)"""
    user = message.from_user
    
    if not is_admin(user.id):
        await message.reply_text(f"{EMOJIS['error']} У вас нет прав доступа")
        return
    
    stats = db.get_stats()
    
    # Получаем топ пользователей по рефералам
    conn = sqlite3.connect(db.db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT username, first_name, referral_count, total_downloads 
        FROM users 
        ORDER BY referral_count DESC 
        LIMIT 10
    ''')
    top_referrers = cursor.fetchall()
    
    cursor.execute('''
        SELECT COUNT(*) FROM users 
        WHERE date(created_at) = date("now")
    ''')
    new_users_today = cursor.fetchone()[0]
    
    cursor.execute('''
        SELECT COUNT(*) FROM downloads 
        WHERE date(created_at) = date("now")
    ''')
    downloads_today = cursor.fetchone()[0]
    
    conn.close()
    
    text = f"""
{EMOJIS['crown']} <b>АДМИН ПАНЕЛЬ</b> {EMOJIS['crown']}

{EMOJIS['stats']} <b>Общая статистика:</b>
{EMOJIS['users']} Всего пользователей: <b>{stats['total_users']}</b>
{EMOJIS['download']} Всего скачиваний: <b>{stats['total_downloads']}</b>
{EMOJIS['sparkles']} Активных сегодня: <b>{stats['active_today']}</b>
{EMOJIS['gift']} Новых сегодня: <b>{new_users_today}</b>
📥 Скачиваний сегодня: <b>{downloads_today}</b>

{EMOJIS['trophy']} <b>Топ по рефералам:</b>
"""
    
    for i, (username, first_name, ref_count, downloads) in enumerate(top_referrers[:5], 1):
        display_name = f"@{username}" if username else first_name or "Аноним"
        text += f"{i}. {display_name}: {ref_count} реф. ({downloads} скач.)\n"
    
    uptime = datetime.now() - bot_start_time
    text += f"\n{EMOJIS['time']} <b>Время работы:</b> {str(uptime).split('.')[0]}"
    
    await message.reply_text(text, parse_mode=ParseMode.HTML)

@app.on_message(filters.command("broadcast"))
async def broadcast_command(client, message):
    """Рассылка сообщения всем пользователям (только для админов)"""
    user = message.from_user
    
    if not is_admin(user.id):
        await message.reply_text(f"{EMOJIS['error']} У вас нет прав доступа")
        return
    
    # Получаем текст сообщения
    command_parts = message.text.split(' ', 1)
    if len(command_parts) < 2:
        await message.reply_text(
            f"{EMOJIS['info']} Использование: /broadcast <сообщение>\n"
            f"Пример: /broadcast Привет! Обновление бота!"
        )
        return
    
    broadcast_text = command_parts[1]
    
    # Получаем всех пользователей
    conn = sqlite3.connect(db.db_path)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM users')
    all_users = cursor.fetchall()
    conn.close()
    
    sent_count = 0
    failed_count = 0
    
    status_msg = await message.reply_text(
        f"{EMOJIS['rocket']} Начинаю рассылку для {len(all_users)} пользователей..."
    )
    
    for (user_id,) in all_users:
        try:
            await client.send_message(
                chat_id=user_id,
                text=f"{EMOJIS['diamond']} <b>Сообщение от администрации:</b>\n\n{broadcast_text}",
                parse_mode=ParseMode.HTML
            )
            sent_count += 1
            await asyncio.sleep(0.1)  # Небольшая задержка
        except Exception as e:
            failed_count += 1
            logger.error(f"Ошибка отправки пользователю {user_id}: {e}")
    
    await status_msg.edit_text(
        f"{EMOJIS['success']} <b>Рассылка завершена!</b>\n\n"
        f"✅ Отправлено: {sent_count}\n"
        f"❌ Не удалось: {failed_count}\n"
        f"📊 Всего: {len(all_users)}",
        parse_mode=ParseMode.HTML
    )

@app.on_message(filters.text & ~filters.command(['start', 'adminstats', 'broadcast']))
async def handle_message(client, message):
    """Обработка текстовых сообщений с ссылками"""
    message_text = message.text
    video_url = downloader.extract_video_url(message_text)
    
    if not video_url:
        await message.reply_text(
            f"{EMOJIS['link']} <b>Отправьте ссылку на TikTok или YouTube видео</b>\n\n"
            f"🎬 Поддерживаемые платформы:\n"
            f"• TikTok (все форматы ссылок)\n"
            f"• YouTube (обычные видео и Shorts)\n\n"
            f"📝 Просто скопируйте ссылку и отправьте мне!",
            parse_mode=ParseMode.HTML
        )
        return
    
    platform = downloader.detect_platform(video_url)
    
    if platform == 'tiktok':
        await download_tiktok_video(client, message, video_url)
    elif platform == 'youtube':
        await download_youtube_video(client, message, video_url)
    else:
        await message.reply_text(f"{EMOJIS['error']} Не удалось определить платформу видео")

async def download_tiktok_video(client, message: Message, tiktok_url: str):
    """Обработка скачивания TikTok видео"""
    await client.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    
    status_message = await message.reply_text(
        f"{EMOJIS['magic']} <b>Получаю информацию о TikTok видео...</b>",
        parse_mode=ParseMode.HTML
    )
    
    try:
        resolved_url = downloader.resolve_tiktok_url(tiktok_url)
        video_info = await downloader.get_video_info(resolved_url)
        
        await status_message.delete()
        await quality_selection(client, message, resolved_url, video_info)
        
    except Exception as e:
        logger.error(f"Ошибка обработки TikTok видео: {e}")
        await status_message.edit_text(
            f"{EMOJIS['error']} <b>Не удалось обработать TikTok видео</b>\n\n"
            f"{EMOJIS['info']} Возможные причины:\n"
            f"• Видео удалено или недоступно\n"
            f"• Приватный аккаунт\n"
            f"• Неправильная ссылка\n"
            f"• Временные проблемы с сервером\n\n"
            f"Попробуйте другую ссылку",
            parse_mode=ParseMode.HTML
        )

async def download_youtube_video(client, message: Message, youtube_url: str):
    """Обработка скачивания YouTube видео"""
    await client.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    
    status_message = await message.reply_text(
        f"{EMOJIS['download']} <b>Получаю информацию о YouTube видео...</b>",
        parse_mode=ParseMode.HTML
    )
    
    try:
        video_info = await youtube_downloader.get_video_info(youtube_url)
        
        if not video_info:
            await status_message.edit_text(
                f"{EMOJIS['error']} <b>Не удалось получить информацию о видео</b>\n\n"
                f"Возможные причины:\n"
                f"• Видео недоступно или удалено\n"
                f"• Видео приватное\n"
                f"• Ограничения по региону\n"
                f"• Неправильная ссылка\n\n"
                f"Попробуйте другое видео",
                parse_mode=ParseMode.HTML
            )
            return
        
        await status_message.delete()
        await youtube_quality_selection(client, message, youtube_url, video_info)
        
    except Exception as e:
        logger.error(f"YouTube critical error: {e}")
        await status_message.edit_text(
            f"{EMOJIS['error']} <b>Системная ошибка</b>\n"
            f"Попробуйте позже или другое видео",
            parse_mode=ParseMode.HTML
        )

async def youtube_quality_selection(client, message: Message, youtube_url: str, video_info: dict):
    """Выбор качества для YouTube видео"""
    user = message.from_user
    user_data = db.get_user(user.id)
    referral_count = user_data[4] if user_data else 0
    is_user_admin = is_admin(user.id)
    
    quality_options = downloader.get_quality_options(referral_count, is_user_admin, 'youtube')
    
    duration_seconds = int(video_info.get('duration', 0))
    duration_str = str(timedelta(seconds=duration_seconds))
    
    warning_text = ""
    if duration_seconds > 1200:  # 20 минут
        warning_text = f"\n🚨 <i>Очень длинное видео ({duration_str}), рекомендуем 720p или аудио</i>"
    elif duration_seconds > 600:  # 10 минут
        warning_text = f"\n⚠️ <i>Видео длинное ({duration_str}), файл может быть большим</i>"
    
    text = f"""
{EMOJIS['video']} <b>YouTube видео найдено:</b>

📝 <b>Название:</b> {video_info.get('title', 'YouTube Video')[:100]}
{EMOJIS['user']} <b>Канал:</b> {video_info.get('uploader', 'Unknown')}
{EMOJIS['time']} <b>Длительность:</b> {duration_str}
👀 <b>Просмотры:</b> {video_info.get('view_count', 0):,}
👍 <b>Лайки:</b> {video_info.get('like_count', 0):,}{warning_text}

{EMOJIS['quality']} <b>Выберите качество для скачивания:</b>
<i>Лимит: {MAX_FILE_SIZE_YOUTUBE/1024/1024:.0f}MB для YouTube</i>
"""
    
    keyboard = []
    row = []
    
    try:
        encoded_url = base64.b64encode(youtube_url.encode('utf-8')).decode('utf-8')
        if len(encoded_url) > 50:
            url_hash = hashlib.md5(youtube_url.encode()).hexdigest()[:16]
            if user.id not in user_data_dict:
                user_data_dict[user.id] = {}
            user_data_dict[user.id]['current_video_url'] = youtube_url
            user_data_dict[user.id]['video_info'] = video_info
            encoded_url = url_hash
    except Exception as e:
        logger.error(f"Ошибка кодирования YouTube URL: {e}")
        encoded_url = "error"
    
    for quality, options in quality_options.items():
        if quality in ['1080p', 'best'] and not is_user_admin and referral_count < 3:
            row.append(InlineKeyboardButton(
                f"🔒 {quality} (нужно {3-referral_count} реф.)",
                callback_data=f"locked_{quality}"
            ))
        elif quality == 'audio_only':
            row.append(InlineKeyboardButton(
                f"{options['emoji']} MP3",
                callback_data=f"yt_{quality}_{encoded_url}"
            ))
        elif quality == 'best':
            row.append(InlineKeyboardButton(
                f"{options['emoji']} Лучшее",
                callback_data=f"yt_{quality}_{encoded_url}"
            ))
        else:
            row.append(InlineKeyboardButton(
                f"{options['emoji']} {quality}",
                callback_data=f"yt_{quality}_{encoded_url}"
            ))
        
        if len(row) == 2:
            keyboard.append(row)
            row = []
    
    if row:
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton(f"{EMOJIS['error']} Отмена", callback_data="cancel")])
    
    # Сохраняем данные в контексте
    if user.id not in user_data_dict:
        user_data_dict[user.id] = {}
    user_data_dict[user.id]['current_video_url'] = youtube_url
    user_data_dict[user.id]['video_info'] = video_info
    user_data_dict[user.id]['platform'] = 'youtube'
    
    await message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def detailed_diagnosis():
    print("=== ДИАГНОСТИКА ===")
    # 1. Проверяем ffmpeg
    try:
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True)
        print("✅ ffmpeg установлен")
        print(f"Версия: {result.stdout.split()[2] if result.stdout else 'неизвестно'}")
    except Exception as e:
        print("❌ ffmpeg не найден", e)
    # 2. Проверяем yt-dlp
    try:
        print(f"✅ yt-dlp версия: {yt_dlp.version.__version__}")
    except Exception as e:
        print("❌ Проблема с yt-dlp", e)
    # 3. Проверяем интернет
    try:
        import requests
        response = requests.get("https://www.google.com", timeout=5)
        print("✅ Интернет работает")
    except Exception as e:
        print("❌ Проблемы с интернетом", e)
    # 4. Тестируем простое видео
    test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    ydl_opts = {
        'quiet': False,
        'no_warnings': False,
        'extract_flat': True,
        'force_json': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(test_url, download=False)
            print(f"✅ Тестовое видео работает: {info.get('title', 'Без названия')}")
            return True
    except Exception as e:
        print(f"❌ Тестовое видео не работает: {e}")
        return False

def update_yt_dlp():
    try:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--upgrade', 'yt-dlp'])
        print("✅ yt-dlp обновлен")
    except:
        print("❌ Не удалось обновить yt-dlp")

def get_video_info(url):
    ydl_opts = {
        'quiet': False,
        'no_warnings': False,
        'extract_flat': False,
        'writesubtitles': False,
        'writeautomaticsub': False,
        'ignoreerrors': True,
        'geo_bypass': True,
        'geo_bypass_country': 'US',
        'extractor_retries': 3,
        'fragment_retries': 3,
        'skip_unavailable_fragments': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'referer': 'https://www.youtube.com/',
        'headers': {
            'Accept-Language': 'en-US,en;q=0.9',
        },
        'format': 'best[height<=480]',
        'noplaylist': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            print(f"🔍 Пробую получить информацию о: {url}")
            info = ydl.extract_info(url, download=False)
            if info:
                print(f"✅ Успех! Название: {info.get('title', 'Без названия')}")
                print(f"📺 Длительность: {info.get('duration', 'неизвестно')} сек")
                print(f"👁 Просмотры: {info.get('view_count', 'неизвестно')}")
                return info
            else:
                print("❌ Информация не получена")
                return None
    except Exception as e:
        print(f"❌ Ошибка: {str(e)}")
        try:
            print("🔄 Пробую альтернативный метод...")
            ydl_opts_simple = {
                'quiet': True,
                'extract_flat': True,
                'force_json': True,
            }
            with yt_dlp.YoutubeDL(ydl_opts_simple) as ydl:
                info = ydl.extract_info(url, download=False)
                if info:
                    print(f"✅ Альтернативный метод сработал: {info.get('title', 'Без названия')}")
                    return info
        except Exception as e2:
            print(f"❌ И альтернативный метод не сработал: {str(e2)}")
        return None

def extract_video_id(url):
    """Извлекает ID видео из различных форматов YouTube ссылок"""
    patterns = [
        r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})',
        r'youtube\.com\/.*[?&]v=([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def get_youtube_info(url):
    """Получает информацию о YouTube видео с расширенной обработкой ошибок"""
    video_id = extract_video_id(url)
    print(f"🔍 Обрабатываю YouTube видео ID: {video_id}")
    if not video_id:
        return None, "❌ Не удалось извлечь ID видео из ссылки"
    alternative_urls = [
        f"https://www.youtube.com/watch?v={video_id}",
        f"https://youtu.be/{video_id}",
        f"https://www.youtube.com/embed/{video_id}",
        f"https://m.youtube.com/watch?v={video_id}"
    ]
    ydl_configs = [
        {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'format': 'best[height<=720]',
            'noplaylist': True,
        },
        {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'format': 'best[height<=480]',
            'noplaylist': True,
            'geo_bypass': True,
            'geo_bypass_country': 'US',
        },
        {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'force_json': True,
            'noplaylist': True,
        },
    ]
    for config_num, ydl_opts in enumerate(ydl_configs, 1):
        for url_num, test_url in enumerate(alternative_urls, 1):
            try:
                print(f"🔄 Попытка {config_num}.{url_num}: {test_url[:50]}...")
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(test_url, download=False)
                    if info and info.get('title'):
                        print(f"✅ Успех! Найдено: {info.get('title')}")
                        return info, None
            except Exception as e:
                error_msg = str(e).lower()
                print(f"❌ Попытка {config_num}.{url_num} неудачна: {str(e)[:100]}...")
                if 'unavailable' in error_msg or 'private' in error_msg:
                    continue
                elif 'blocked' in error_msg:
                    continue
                elif 'age' in error_msg:
                    continue
                else:
                    continue
    error_messages = [
        "❌ Не удалось получить информацию о видео",
        "",
        "🔍 Возможные причины:",
        "• Видео удалено или сделано приватным",
        "• Видео заблокировано в вашем регионе",
        "• Видео имеет возрастные ограничения",
        "• Неправильная ссылка или ID видео",
        "• Временные проблемы с YouTube API",
        "",
        "💡 Что попробовать:",
        "• Проверьте ссылку в браузере",
        "• Попробуйте другое видео",
        "• Подождите несколько минут и попробуйте снова"
    ]
    return None, "\n".join(error_messages)

def handle_youtube_url(url, message):
    """Обработчик YouTube ссылок для бота"""
    try:
        processing_msg = message.reply("🔄 Обрабатываю YouTube видео...")
        info, error = get_youtube_info(url)
        if info:
            title = info.get('title', 'Без названия')
            duration = info.get('duration', 0)
            view_count = info.get('view_count', 0)
            uploader = info.get('uploader', 'Неизвестно')
            duration_str = f"{duration//60}:{duration%60:02d}" if duration else "неизвестно"
            success_message = (
                f"✅ **Видео найдено!**\n\n"
                f"📺 **Название:** {title}\n"
                f"👤 **Автор:** {uploader}\n"
                f"⏱ **Длительность:** {duration_str}\n"
                f"👁 **Просмотры:** {view_count:,}\n\n"
                f"⬇️ Начинаю скачивание..."
            )
            processing_msg.edit_text(success_message)
        else:
            processing_msg.edit_text(error)
    except Exception as e:
        message.reply(f"❌ Критическая ошибка: {str(e)}")

def download_without_ffmpeg(url):
    import yt_dlp
    ydl_opts = {
        'format': 'best[ext=mp4]/best',  # Выбираем готовый mp4
        'outtmpl': '%(title)s.%(ext)s',
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            ydl.download([url])
            return True
        except Exception as e:
            print(f"Ошибка: {e}")
            return False

# Запуск диагностики и тестов (можно закомментировать после проверки)
if __name__ == '__main__':
    app.run()