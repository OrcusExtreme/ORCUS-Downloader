import os
import re
import sys
import time
import shutil
import threading
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from PIL import Image
import io

import yt_dlp
from yt_dlp.extractor.chzzk import CHZZKVideoIE
from yt_dlp.utils.traversal import traverse_obj
from yt_dlp.utils import float_or_none, int_or_none, url_or_none, download_range_func
import ffmpeg_manager

class DownloadCancelled(Exception):
    pass

_chzzk_patched = False

def patch_chzzk_extractor():
    """Patches CHZZKVideoIE once to extract progressive download (PD) MP4 streams."""
    global _chzzk_patched
    if _chzzk_patched:
        return

    def patched_real_extract(self, url):
        video_id = self._match_id(url)
        video_meta = self._download_json(
            f'https://api.chzzk.naver.com/service/v3/videos/{video_id}', video_id,
            note='Downloading video info', errnote='Unable to download video info')['content']

        live_status = 'was_live' if video_meta.get('liveOpenDate') else 'not_live'
        video_status = video_meta.get('vodStatus')
        formats = []
        subtitles = {}

        if video_status == 'ABR_HLS':
            playback_url = f'https://apis.naver.com/neonplayer/vodplay/v1/playback/{video_meta["videoId"]}'
            query = {
                'key': video_meta['inKey'],
                'env': 'real',
                'lc': 'en_US',
                'cpl': 'en_US',
            }
            mpd_doc = self._download_xml(
                playback_url, video_id, note='Downloading MPD manifest',
                query=query, headers={'Accept': 'application/dash+xml'}
            )
            ns = {'mpd': 'urn:mpeg:dash:schema:mpd:2011'}
            for rep in mpd_doc.findall('.//mpd:Representation', ns):
                rep_id = rep.get('id', '')
                base_url_elem = rep.find('mpd:BaseURL', ns)
                if base_url_elem is None or not base_url_elem.text:
                    continue
                direct_url = base_url_elem.text.strip()
                w = int_or_none(rep.get('width'))
                h = int_or_none(rep.get('height'))
                bw = int_or_none(rep.get('bandwidth'))
                codecs = rep.get('codecs', '')
                
                vcodec, acodec = 'none', 'none'
                if codecs:
                    for p in codecs.split(','):
                        p = p.strip()
                        if any(p.startswith(prefix) for prefix in ('avc', 'hev', 'vp', 'av01')):
                            vcodec = p
                        elif any(p.startswith(prefix) for prefix in ('mp4a', 'opus', 'aac')):
                            acodec = p

                formats.append({
                    'format_id': f'pd-{rep_id}',
                    'url': direct_url,
                    'ext': 'mp4',
                    'width': w,
                    'height': h,
                    'tbr': float_or_none(bw, 1000),
                    'vcodec': vcodec,
                    'acodec': acodec,
                    'protocol': 'https',
                })
        else:
            prev_formats, subtitles = self._extract_vod(video_meta)
            formats.extend(prev_formats)

        return {
            'id': video_id,
            'title': video_meta.get('videoTitle'),
            'formats': formats,
            'subtitles': subtitles,
            'thumbnail': video_meta.get('thumbnailImageUrl'),
            'duration': video_meta.get('duration'),
            'view_count': video_meta.get('readCount'),
            'like_count': video_meta.get('likeCount'),
            'channel': traverse_obj(video_meta, ('channel', 'channelName')),
            'channel_id': traverse_obj(video_meta, ('channel', 'channelId')),
            'uploader': traverse_obj(video_meta, ('channel', 'channelName')),
            'uploader_id': traverse_obj(video_meta, ('channel', 'channelId')),
            'live_status': live_status,
        }

    CHZZKVideoIE._real_extract = patched_real_extract
    _chzzk_patched = True


def clean_url(url: str) -> str:
    """Strips infinite playlist/radio query parameters from YouTube URLs."""
    u = url.strip()
    if ('youtube.com/watch' in u or 'youtu.be/' in u) and 'list=' in u:
        parsed = urllib.parse.urlparse(u)
        qs = urllib.parse.parse_qs(parsed.query)
        if 'v' in qs:
            return f"https://www.youtube.com/watch?v={qs['v'][0]}"
    return u


def detect_platform(url: str) -> str:
    """Detects platform from URL with expanded 8-platform support."""
    u = url.lower()
    if 'chzzk.naver.com' in u:
        return 'CHZZK'
    elif 'sooplive.co.kr' in u or 'afreecatv.com' in u or 'afreeca.com' in u or 'sooplive.com' in u:
        return 'SOOP'
    elif 'youtube.com' in u or 'youtu.be' in u:
        return 'YouTube'
    elif 'twitter.com' in u or 'x.com' in u:
        return 'X (Twitter)'
    elif 'instagram.com' in u:
        return 'Instagram'
    elif 'tiktok.com' in u:
        return 'TikTok'
    elif 'tv.naver.com' in u or 'now.naver.com' in u:
        return 'NaverTV'
    elif 'twitch.tv' in u:
        return 'Twitch'
    return 'Other'


def parse_time_to_seconds(time_str: str):
    """Parses HH:MM:SS or MM:SS to seconds float. Returns None if invalid or empty."""
    if not time_str or not time_str.strip():
        return None
    parts = time_str.strip().split(':')
    try:
        if len(parts) == 3:
            h, m, s = map(float, parts)
            return h * 3600 + m * 60 + s
        elif len(parts) == 2:
            m, s = map(float, parts)
            return m * 60 + s
        elif len(parts) == 1:
            return float(parts[0])
    except ValueError:
        return None
    return None


def fetch_preview_info(url: str) -> dict:
    """
    Fetches video metadata and loads thumbnail image into a PIL Image asynchronously.
    Returns dict with keys: title, uploader, duration_str, duration_sec, platform, thumbnail_image, thumbnail_url
    """
    cleaned = clean_url(url)
    platform = detect_platform(cleaned)
    if platform == 'CHZZK':
        patch_chzzk_extractor()

    ydl_opts = {
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
    }
    ffmpeg_dir = ffmpeg_manager.get_ffmpeg_dir()
    if ffmpeg_dir:
        ydl_opts['ffmpeg_location'] = ffmpeg_dir

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(cleaned, download=False)
            if not info:
                return None

            title = info.get('title', 'Unknown Title')
            uploader = info.get('uploader') or info.get('channel') or 'Unknown Uploader'
            duration = info.get('duration') or 0
            dur_m, dur_s = divmod(int(duration), 60)
            dur_h, dur_m = divmod(dur_m, 60)
            if dur_h > 0:
                dur_str = f"{dur_h}:{dur_m:02d}:{dur_s:02d}"
            else:
                dur_str = f"{dur_m:02d}:{dur_s:02d}" if duration else "Live / N/A"

            thumbnail_url = info.get('thumbnail')
            thumb_image = None
            if thumbnail_url:
                try:
                    req = urllib.request.Request(
                        thumbnail_url,
                        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
                    )
                    with urllib.request.urlopen(req, timeout=8) as resp:
                        img_data = resp.read()
                        thumb_image = Image.open(io.BytesIO(img_data)).convert("RGB")
                except Exception:
                    thumb_image = None

            return {
                'title': title,
                'uploader': uploader,
                'duration_str': dur_str,
                'duration_sec': duration,
                'platform': platform,
                'thumbnail_image': thumb_image,
                'thumbnail_url': thumbnail_url,
            }
    except Exception:
        return None


class DownloaderWorker(threading.Thread):
    def __init__(self, url: str, output_dir: str, callbacks: dict, 
                 download_type: str = "video", resolution: str = "best",
                 clip_start: str = None, clip_end: str = None):
        super().__init__(daemon=True)
        self.raw_url = url.strip()
        self.url = clean_url(self.raw_url)
        self.output_dir = output_dir
        self.callbacks = callbacks  # on_start, on_progress, on_status, on_finish
        self.download_type = download_type  # "video" or "audio"
        self.resolution = resolution  # "best", "2160", "1440", "1080", "720", "480", "360"
        self.clip_start = clip_start
        self.clip_end = clip_end

        self.is_cancelled = False
        self.pause_event = threading.Event()
        self.pause_event.set()  # Initially not paused
        self.is_paused = False
        self.last_progress_time = 0

    def pause(self):
        self.is_paused = True
        self.pause_event.clear()
        if 'on_status' in self.callbacks:
            self.callbacks['on_status']("Download paused.")

    def resume(self):
        self.is_paused = False
        self.pause_event.set()
        if 'on_status' in self.callbacks:
            self.callbacks['on_status']("Resuming download...")

    def cancel(self):
        self.is_cancelled = True
        self.pause_event.set()  # Unblock if paused to exit immediately

    def _progress_hook(self, d):
        if self.is_cancelled:
            raise DownloadCancelled("Download cancelled by user.")

        # Wait if paused
        self.pause_event.wait()

        if self.is_cancelled:
            raise DownloadCancelled("Download cancelled by user.")

        status = d.get('status')
        if status == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes', 0)
            speed = d.get('speed') or 0
            eta = d.get('eta') or 0
            filename = os.path.basename(d.get('filename', ''))

            pct = (downloaded / total * 100) if total > 0 else 0
            speed_mb = speed / (1024 * 1024) if speed else 0
            eta_m, eta_s = divmod(int(eta), 60)
            eta_str = f"{eta_m:02d}:{eta_s:02d}" if eta else "N/A"
            speed_str = f"{speed_mb:.2f} MB/s" if speed_mb else "Calculating..."

            now = time.time()
            if now - self.last_progress_time >= 0.15 or pct >= 100:
                self.last_progress_time = now
                if 'on_progress' in self.callbacks:
                    self.callbacks['on_progress'](
                        pct,
                        downloaded / (1024 * 1024),
                        total / (1024 * 1024),
                        speed_str,
                        eta_str,
                        filename
                    )

        elif status == 'finished':
            filename = os.path.basename(d.get('filename', ''))
            action = "Extracting & tagging MP3 audio..." if self.download_type == "audio" else "Merging & finalizing..."
            if 'on_status' in self.callbacks:
                self.callbacks['on_status'](f"Finished download: {filename}. {action}")

    def run(self):
        patch_chzzk_extractor()
        platform = detect_platform(self.url)

        type_text = "Audio (MP3)" if self.download_type == "audio" else f"Video ({self.resolution}p)"
        if 'on_status' in self.callbacks:
            self.callbacks['on_status'](f"[{platform}] Analyzing {type_text}...")

        outtmpl = os.path.join(self.output_dir, '%(title)s [%(id)s].%(ext)s')

        postprocessors = []
        if self.download_type == 'audio':
            fmt = 'bestaudio/best'
            # MP3 Extraction with 320k
            postprocessors.append({
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320',
            })
            postprocessors.append({'key': 'FFmpegMetadata'})
            postprocessors.append({'key': 'EmbedThumbnail'})
            merge_format = None
            writethumbnail = True
        else:
            writethumbnail = False
            res_val = self.resolution
            if res_val in ("best", "Best (Original)"):
                if platform == 'CHZZK':
                    fmt = 'best'
                else:
                    fmt = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best'
            else:
                try:
                    num_h = int(str(res_val).replace('p', ''))
                    fmt = f'bestvideo[height<={num_h}][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<={num_h}]+bestaudio/best[height<={num_h}]/best'
                except Exception:
                    fmt = 'bestvideo+bestaudio/best'

            merge_format = 'mp4'

        ydl_opts = {
            'format': fmt,
            'outtmpl': outtmpl,
            'progress_hooks': [self._progress_hook],
            'continuedl': True,
            'noplaylist': True,
            'retries': 10,
            'fragment_retries': 10,
            'quiet': True,
            'no_warnings': True,
        }
        if writethumbnail:
            ydl_opts['writethumbnail'] = True
        if merge_format:
            ydl_opts['merge_output_format'] = merge_format
        if postprocessors:
            ydl_opts['postprocessors'] = postprocessors

        ffmpeg_dir = ffmpeg_manager.get_ffmpeg_dir()
        if not ffmpeg_dir:
            if 'on_status' in self.callbacks:
                self.callbacks['on_status']("Setting up media engine (FFmpeg)...")

            def _ff_progress(pct, msg):
                if 'on_status' in self.callbacks:
                    self.callbacks['on_status'](f"FFmpeg: {msg}")

            try:
                ffmpeg_dir = ffmpeg_manager.ensure_ffmpeg(progress_callback=_ff_progress)
            except Exception as e:
                if 'on_finish' in self.callbacks:
                    self.callbacks['on_finish'](False, f"FFmpeg error: {str(e)}", None)
                return

        if ffmpeg_dir:
            ydl_opts['ffmpeg_location'] = ffmpeg_dir

        start_sec = parse_time_to_seconds(self.clip_start)
        end_sec = parse_time_to_seconds(self.clip_end)
        if start_sec is not None and end_sec is not None and start_sec >= end_sec:
            if 'on_finish' in self.callbacks:
                self.callbacks['on_finish'](False, f"Invalid clip range: Start time ({self.clip_start}) must be earlier than End time ({self.clip_end}).", None)
            return

        if start_sec is not None or end_sec is not None:
            s_val = start_sec if start_sec is not None else 0
            ydl_opts['download_ranges'] = download_range_func(None, [(s_val, end_sec)])
            ydl_opts['force_keyframes_at_cuts'] = True

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(self.url, download=False)
                if not info:
                    raise Exception("Failed to retrieve video metadata.")

                title = info.get('title', 'Unknown Title')
                uploader = info.get('uploader') or info.get('channel') or 'Unknown Uploader'
                duration = info.get('duration') or 0
                dur_m, dur_s = divmod(int(duration), 60)
                dur_str = f"{dur_m}:{dur_s:02d}" if duration else "N/A"

                if 'on_start' in self.callbacks:
                    self.callbacks['on_start'](title, uploader, dur_str, platform)

                if 'on_status' in self.callbacks:
                    self.callbacks['on_status'](f"Downloading: {title} ({type_text})")

                ydl.download([self.url])
                final_file = ydl.prepare_filename(info)
                
                if self.download_type == 'audio':
                    base, _ = os.path.splitext(final_file)
                    if os.path.exists(base + '.mp3'):
                        final_file = base + '.mp3'
                else:
                    if not os.path.exists(final_file):
                        base, _ = os.path.splitext(final_file)
                        if os.path.exists(base + '.mp4'):
                            final_file = base + '.mp4'

            if 'on_finish' in self.callbacks:
                self.callbacks['on_finish'](True, f"{type_text} download completed successfully!", final_file)

        except DownloadCancelled:
            if 'on_finish' in self.callbacks:
                self.callbacks['on_finish'](False, "Download cancelled by user.", None)
        except Exception as e:
            if 'on_finish' in self.callbacks:
                self.callbacks['on_finish'](False, f"Error: {str(e)}", None)
