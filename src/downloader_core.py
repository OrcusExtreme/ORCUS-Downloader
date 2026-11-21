import io
import os
import time
import logging
import threading
import urllib.parse
import urllib.request
from logging.handlers import RotatingFileHandler
from PIL import Image

import yt_dlp
from yt_dlp.extractor.chzzk import CHZZKVideoIE
from yt_dlp.utils.traversal import traverse_obj
from yt_dlp.utils import float_or_none, int_or_none, download_range_func
import ffmpeg_manager
import js_runtime_manager

class DownloadCancelled(Exception):
    pass


# -----------------------------------------------------------------------------
# Logging: yt-dlp warnings/errors are collected instead of being discarded
# -----------------------------------------------------------------------------
_file_logger = None
_file_logger_lock = threading.Lock()

def _get_file_logger() -> logging.Logger:
    """Rotating log at %LOCALAPPDATA%/ORCUS Downloader/logs/ytdlp.log (created once, thread-safe)."""
    global _file_logger
    with _file_logger_lock:
        if _file_logger is not None:
            return _file_logger
        logger = logging.getLogger("orcus.ytdlp")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        if not logger.handlers:  # idempotent: never attach a second file handler
            try:
                log_dir = os.path.join(os.path.dirname(ffmpeg_manager.get_local_storage_dir()), "logs")
                os.makedirs(log_dir, exist_ok=True)
                handler = RotatingFileHandler(os.path.join(log_dir, "ytdlp.log"),
                                              maxBytes=1_000_000, backupCount=2, encoding="utf-8")
                handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
                logger.addHandler(handler)
            except Exception:
                logger.addHandler(logging.NullHandler())
        _file_logger = logger
        return logger


# Warnings caused by a missing/broken JS challenge solver (browser cookies cannot fix these)
_JS_WARNING_KEYS = ('javascript runtime', 'js runtime', 'challenge', 'signature')

# Warnings that indicate YouTube formats were dropped (=> possibly degraded quality)
_QUALITY_WARNING_KEYS = _JS_WARNING_KEYS + (
    'po token', 'formats may be missing', 'formats have been skipped',
    'only images are available',
)


class YdlLogger:
    """yt-dlp logger that records warnings, writes them to the log file and
    optionally forwards them to the UI status callback."""

    def __init__(self, on_warning=None):
        self.warnings = []
        self.on_warning = on_warning
        self._log = _get_file_logger()

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        self.warnings.append(msg)
        self._log.warning(msg)
        if self.on_warning:
            try:
                self.on_warning(msg)
            except Exception:
                pass

    def error(self, msg):
        self._log.error(msg)

    def has_quality_warning(self) -> bool:
        return any(k in w.lower() for w in self.warnings for k in _QUALITY_WARNING_KEYS)

    def has_js_warning(self) -> bool:
        return any(k in w.lower() for w in self.warnings for k in _JS_WARNING_KEYS)


def build_video_format_opts(resolution: str) -> dict:
    """
    Format selection for video downloads.
    - Allows every container/codec (VP9/AV1 webm are the only source of 1440p/4K
      on YouTube); the result is merged into MP4 by FFmpeg.
    - A height limit is expressed via format_sort ('res:N' = best <= N, otherwise
      the closest above) so a missing resolution never silently falls back to 360p.
    - At equal resolution, H.264/AAC are preferred for player compatibility.
    """
    target = None
    if resolution not in (None, "", "best", "Best (Original)"):
        try:
            target = int(str(resolution).replace('p', ''))
        except ValueError:
            target = None
    return {
        'format': 'bv*+ba/b',
        'format_sort': [f'res:{target}' if target else 'res', 'fps', 'vcodec:h264', 'acodec:aac'],
    }


def _selected_height(info: dict):
    if not info:
        return None
    h = info.get('height')
    if h:
        return h
    for f in info.get('requested_formats') or []:
        if f.get('height'):
            return f['height']
    return None

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
                
                # Unknown codecs (codecs attr missing, e.g. declared on AdaptationSet)
                # stay None so yt-dlp treats the PD MP4 as a muxed A/V stream.
                vcodec, acodec = None, None
                if codecs:
                    vcodec, acodec = 'none', 'none'
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
        'noplaylist': True,
        'logger': YdlLogger(),
    }
    if platform == 'YouTube':
        # Preview only needs metadata: use an already-provisioned runtime if present
        # but never block the preview on a Deno download.
        ydl_opts.update(js_runtime_manager.get_ytdlp_js_opts(js_runtime_manager.find_deno_exe()))
    ffmpeg_dir = ffmpeg_manager.get_ffmpeg_dir()
    if ffmpeg_dir:
        ydl_opts['ffmpeg_location'] = ffmpeg_dir

    try:
        info = None
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(cleaned, download=False)
        except Exception as e:
            if platform == 'YouTube' and any(k in str(e).lower() for k in ['sign in', 'login_required', 'cookies', 'bot']):
                for b in ['edge', 'chrome', 'firefox', 'brave', 'whale']:
                    try:
                        retry_opts = dict(ydl_opts)
                        retry_opts['cookiesfrombrowser'] = (b,)
                        with yt_dlp.YoutubeDL(retry_opts) as r_ydl:
                            info = r_ydl.extract_info(cleaned, download=False)
                            if info:
                                break
                    except Exception:
                        continue
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

    def _finish(self, success, message, filepath):
        if 'on_finish' in self.callbacks:
            self.callbacks['on_finish'](success, message, filepath)

    def run(self):
        # Guarantees on_finish is always delivered, even if engine setup fails,
        # so the UI never stays stuck in the "downloading" state.
        try:
            self._run()
        except DownloadCancelled:
            self._finish(False, "Download cancelled by user.", None)
        except Exception as e:
            self._finish(False, f"Error: {str(e)}", None)

    def _run(self):
        patch_chzzk_extractor()
        platform = detect_platform(self.url)

        if self.download_type == "audio":
            type_text = "Audio (MP3)"
        elif str(self.resolution).isdigit():
            type_text = f"Video ({self.resolution}p)"
        else:
            type_text = "Video (Best)"
        if 'on_status' in self.callbacks:
            self.callbacks['on_status'](f"[{platform}] Analyzing {type_text}...")

        outtmpl = os.path.join(self.output_dir, '%(title)s [%(id)s].%(ext)s')

        postprocessors = []
        format_opts = {}
        if self.download_type == 'audio':
            format_opts = {'format': 'bestaudio/best'}
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
            format_opts = build_video_format_opts(self.resolution)
            merge_format = 'mp4'

        ydl_opts = {
            **format_opts,
            'outtmpl': outtmpl,
            'progress_hooks': [self._progress_hook],
            'continuedl': True,
            'noplaylist': True,
            'retries': 10,
            'fragment_retries': 10,
            'quiet': True,
            # Speed & Performance Optimizations
            'concurrent_fragment_downloads': 8,   # Parallel chunk downloads for DASH & HLS
            'buffersize': 1048576,                # 1MB I/O buffer to reduce disk latency
            'postprocessor_args': {
                'default': ['-threads', '0'],
                'FFmpegExtractAudio': ['-threads', '0'],
                'FFmpegVideoRemuxer': ['-threads', '0'],
                'FFmpegMerger': ['-threads', '0'],
            },
        }
        deno_path = None
        if platform == 'YouTube':
            deno_path = js_runtime_manager.find_deno_exe()
            if not deno_path:
                if 'on_status' in self.callbacks:
                    self.callbacks['on_status']("Setting up YouTube JS runtime (Deno)...")

                def _deno_progress(pct, msg):
                    if 'on_status' in self.callbacks:
                        self.callbacks['on_status'](f"Deno: {msg}")

                deno_path = js_runtime_manager.ensure_deno(progress_callback=_deno_progress)
            ydl_opts.update(js_runtime_manager.get_ytdlp_js_opts(deno_path))
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

        # Engine setup (Deno / FFmpeg downloads) may take a while; honour Cancel here.
        if self.is_cancelled:
            raise DownloadCancelled("Download cancelled by user.")

        target_h = None
        if self.download_type != 'audio':
            try:
                target_h = int(str(self.resolution).replace('p', ''))
            except (TypeError, ValueError):
                target_h = None

        auth_keys = ['sign in', 'login_required', 'use --cookies-from-browser', 'bot', 'confirm your age']
        candidate = None  # (ydl, info, logger, browser)
        ydl_closed = False
        last_error = None
        auth_error = None

        try:
            # Attempt 1: no cookies
            try:
                candidate = self._extract(ydl_opts, None)
            except DownloadCancelled:
                raise
            except Exception as e:
                last_error = e
                if not (platform == 'YouTube' and any(k in str(e).lower() for k in auth_keys)):
                    raise
                auth_error = e

            # Attempt 2+: browser cookies — only when they can actually help:
            # login/age/bot checks, or degraded quality while the JS solver itself worked.
            # (Missing/broken Deno degrades quality too, but cookies cannot fix that.)
            needs_cookies = candidate is None or (
                deno_path is not None
                and self._is_degraded(candidate, target_h)
                and not candidate[2].has_js_warning()
            )
            if platform == 'YouTube' and needs_cookies:
                for b in ['edge', 'chrome', 'firefox', 'brave', 'whale', 'opera', 'vivaldi']:
                    if self.is_cancelled:
                        raise DownloadCancelled("Download cancelled by user.")
                    if 'on_status' in self.callbacks:
                        self.callbacks['on_status'](f"Trying authentication with {b.capitalize()} browser cookies...")
                    try:
                        alt = self._extract(ydl_opts, b)
                    except DownloadCancelled:
                        raise
                    except Exception as e:
                        last_error = e
                        continue
                    if candidate is None or (_selected_height(alt[1]) or 0) > (_selected_height(candidate[1]) or 0):
                        if candidate is not None:
                            candidate[0].close()
                        candidate = alt
                    else:
                        alt[0].close()
                    if not self._is_degraded(candidate, target_h):
                        break

            if candidate is None:
                # Report the original sign-in error, not whichever browser failed last.
                if auth_error is not None:
                    raise Exception(
                        "YouTube에서 로그인 인증을 요구하고 있습니다 (연령 제한, 비공개 또는 봇 방지 감지).\n"
                        "Edge 또는 Chrome 브라우저에서 YouTube에 로그인되어 있는지 확인해주세요."
                    )
                raise last_error or Exception("Failed to retrieve video metadata.")

            ydl, info, logger, browser = candidate
            with ydl:
                title = info.get('title', 'Unknown Title')
                uploader = info.get('uploader') or info.get('channel') or 'Unknown Uploader'
                duration = info.get('duration') or 0
                dur_m, dur_s = divmod(int(duration), 60)
                dur_str = f"{dur_m}:{dur_s:02d}" if duration else "N/A"

                if 'on_start' in self.callbacks:
                    try:
                        self.callbacks['on_start'](title, uploader, dur_str, platform)
                    except Exception:
                        pass

                cookie_note = f" with {browser.capitalize()} cookies" if browser else ""
                if 'on_status' in self.callbacks:
                    try:
                        self.callbacks['on_status'](f"Downloading{cookie_note}: {title} ({type_text})")
                    except Exception:
                        pass

                result = ydl.process_ie_result(info, download=True) or info
                final_file = None
                for rd in result.get('requested_downloads') or []:
                    if rd.get('filepath'):
                        final_file = rd['filepath']
                if not final_file:
                    final_file = ydl.prepare_filename(result)

                if self.download_type == 'audio':
                    base, _ = os.path.splitext(final_file)
                    if os.path.exists(base + '.mp3'):
                        final_file = base + '.mp3'
                else:
                    if not os.path.exists(final_file):
                        base, _ = os.path.splitext(final_file)
                        if os.path.exists(base + '.mp4'):
                            final_file = base + '.mp4'
            ydl_closed = True

            msg = f"{type_text} download completed successfully{cookie_note}!"
            if self.download_type != 'audio':
                w, h = result.get('width'), _selected_height(result)
                if h:
                    msg += f" [{w}x{h}]" if w else f" [{h}p]"
                if self._is_degraded(candidate, target_h):
                    if candidate[2].has_js_warning() or deno_path is None:
                        reason = "YouTube JS 런타임(Deno)을 사용할 수 없어 고화질 포맷을 받지 못함"
                    else:
                        reason = "YouTube가 고화질 포맷을 제공하지 않음"
                    msg += (f"\n⚠ 요청한 화질을 받지 못했습니다 ({reason}).\n"
                            "로그: %LOCALAPPDATA%\\ORCUS Downloader\\logs\\ytdlp.log")
                elif target_h and h and h < target_h:
                    msg += f" (원본 최대 해상도 {h}p)"

        except BaseException:
            if candidate is not None and not ydl_closed:
                candidate[0].close()
            raise  # reported by run()

        self._finish(True, msg, final_file)

    def _extract(self, base_opts: dict, browser):
        """Extracts metadata (with format selection) using a fresh YoutubeDL.
        Returns (ydl, info, logger, browser); the caller owns/closes ydl."""
        def _on_warning(msg):
            if 'on_status' in self.callbacks:
                self.callbacks['on_status'](f"⚠ {msg[:160]}")

        logger = YdlLogger(on_warning=_on_warning)
        opts = dict(base_opts)
        opts['logger'] = logger
        if browser:
            opts['cookiesfrombrowser'] = (browser,)
        ydl = yt_dlp.YoutubeDL(opts)
        try:
            info = ydl.extract_info(self.url, download=False)
            if not info:
                raise Exception("Failed to retrieve video metadata.")
        except BaseException:
            ydl.close()
            raise
        return ydl, info, logger, browser

    def _is_degraded(self, candidate, target_h) -> bool:
        """True when yt-dlp reported dropped YouTube formats and the selected video
        is a low-resolution (<= 480p) fallback below what was requested.

        A genuinely low-resolution video still gets separate DASH video+audio
        streams ('requested_formats'); the degraded case falls back to a single
        progressive format (e.g. 360p format 18) unless the JS solver failed."""
        if candidate is None or self.download_type == 'audio':
            return False
        _, info, logger, _ = candidate
        if not logger.has_quality_warning():
            return False
        h = _selected_height(info)
        if h is None:
            return True
        if info.get('requested_formats') and not logger.has_js_warning():
            return False
        return h <= 480 and (target_h is None or h < target_h)
