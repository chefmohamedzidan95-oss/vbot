import re
import json
import logging
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote, parse_qs, urlparse
from typing import List, Optional, Dict

from .base import BaseProvider, VideoResult, Category

logger = logging.getLogger(__name__)


class QfilmProvider(BaseProvider):
    """
    Qfilm & Q-Drama Provider.
    Supports movies from a.qfilm.tv and series from a.q-drama.com.
    """

    DOMAINS = {
        "movies": "https://a.qfilm.tv",
        "series": "https://a.q-drama.com",
    }

    CATEGORIES = [
        Category(id="movies_arabic", name="🎬 أفلام عربية", icon="🎬"),
        Category(id="movies_foreign", name="🍿 أفلام أجنبية", icon="🍿"),
        Category(id="movies_action", name="💥 أفلام أكشن", icon="💥"),
        Category(id="movies_comedy", name="😂 أفلام كوميدية", icon="😂"),
        Category(id="movies_horror", name="👻 أفلام رعب", icon="👻"),
        Category(id="movies_anime", name="⛩️ أفلام أنمي", icon="⛩️"),
        Category(id="series_arabic", name="📺 مسلسلات عربية", icon="📺"),
        Category(id="series_foreign", name="🌍 مسلسلات أجنبية", icon="🌍"),
        Category(id="series_turkish", name="🇹🇷 مسلسلات تركية", icon="🇹🇷"),
        Category(id="series_korean", name="🇰🇷 مسلسلات كورية", icon="🇰🇷"),
        Category(id="series_anime", name="🎨 مسلسلات أنمي", icon="🎨"),
    ]

    CATEGORY_QUERIES = {
        "movies_arabic": ("عربي", "movies"),
        "movies_foreign": ("أجنبي", "movies"),
        "movies_action": ("أكشن", "movies"),
        "movies_comedy": ("كوميدي", "movies"),
        "movies_horror": ("رعب", "movies"),
        "movies_anime": ("أنمي", "movies"),
        "series_arabic": ("عربي", "series"),
        "series_foreign": ("أجنبي", "series"),
        "series_turkish": ("تركي", "series"),
        "series_korean": ("كوري", "series"),
        "series_anime": ("أنمي", "series"),
    }

    def __init__(self, config_path: str = "config.json"):
        self.config = self._load_config(config_path)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.config.get(
                "user_agent",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
            "Referer": self.DOMAINS["movies"],
        })
        self.timeout = self.config.get("request_timeout", 30)
        self.player_base_url = self.config.get("player_web_app_url", "")

    @property
    def id(self) -> str:
        return "qfilm"

    @property
    def name(self) -> str:
        return "كيو فيلم & دراما 🍿"

    @property
    def description(self) -> str:
        return "مصدر متميز للأفلام العربية والأجنبية والمسلسلات (a.qfilm.tv & a.q-drama.com)"

    def _load_config(self, config_path: str) -> dict:
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def get_categories(self) -> List[Category]:
        return self.CATEGORIES

    def _get(self, url: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", self.timeout)
        kwargs.setdefault("allow_redirects", True)
        resp = self.session.get(url, **kwargs)
        resp.raise_for_status()
        return resp

    def _extract_vid(self, url: str) -> str:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        vids = params.get("vid", [])
        if vids:
            return vids[0]
        m = re.search(r'vid=([a-f0-9]+)', url)
        if m:
            return m.group(1)
        return ""

    def search(self, query: str, page: int = 1) -> List[VideoResult]:
        results: List[VideoResult] = []
        seen_vids = set()

        for domain_key in ("movies", "series"):
            base = self.DOMAINS[domain_key]
            encoded = quote(query, safe='')
            search_url = f"{base}/search.php?keywords={encoded}"
            if page > 1:
                search_url += f"&page={page}"
            try:
                html = self._get(search_url).text
                soup = BeautifulSoup(html, "lxml")
                domain_results = self._parse_grid(soup, base)
                for r in domain_results:
                    if r.vid not in seen_vids:
                        seen_vids.add(r.vid)
                        r.provider_id = self.id
                        results.append(r)
            except Exception as e:
                logger.error(f"Search failed for {domain_key}: {e}")

        return results

    def get_by_category(self, category_id: str, page: int = 1) -> List[VideoResult]:
        cat_info = self.CATEGORY_QUERIES.get(category_id)
        if cat_info:
            kw, domain_key = cat_info
            base = self.DOMAINS[domain_key]
            encoded = quote(kw, safe='')
            url = f"{base}/search.php?keywords={encoded}"
            if page > 1:
                url += f"&page={page}"
            try:
                html = self._get(url).text
                soup = BeautifulSoup(html, "lxml")
                results = self._parse_grid(soup, base)
                for r in results:
                    r.provider_id = self.id
                return results
            except Exception as e:
                logger.error(f"Category fetch failed for {category_id}: {e}")
                return []
        return self.search(category_id, page=page)

    def _parse_grid(self, soup: BeautifulSoup, base_url: str) -> List[VideoResult]:
        results: List[VideoResult] = []
        grid = soup.find("ul", id="pm-grid")
        if not grid:
            grid = soup.find("ul", class_="pm-ul-browse-videos")
        items = grid.find_all("li") if grid else []

        for li in items:
            res = self._parse_item(li, base_url)
            if res and res.vid:
                results.append(res)
        return results

    def _parse_item(self, li, base_url: str) -> Optional[VideoResult]:
        thumb_div = li.find("div", class_="pm-video-thumb")
        if not thumb_div:
            return None

        video_link = thumb_div.find("a")
        watch_url = video_link.get("href", "") if video_link else ""
        watch_url = urljoin(base_url, watch_url)

        title_tag = li.find("h3", class_="caption")
        title = title_tag.get_text(strip=True) if title_tag else ""

        img = thumb_div.find("img")
        thumb_url = ""
        if img:
            thumb_url = img.get("data-echo") or img.get("src", "")

        dur_tag = thumb_div.find("span", class_="pm-label-duration")
        duration = dur_tag.get_text(strip=True) if dur_tag else ""

        labels = []
        for span in thumb_div.find_all("span", class_=re.compile(r"\blabel\b")):
            classes = span.get("class", [])
            if "pm-label-duration" in classes:
                continue
            txt = span.get_text(strip=True)
            if txt and txt != duration:
                labels.append(txt)

        vid = self._extract_vid(watch_url)
        if not vid:
            return None

        return VideoResult(
            vid=vid,
            title=title or self._clean_title(watch_url),
            watch_url=watch_url,
            thumb_url=urljoin(base_url, thumb_url) if thumb_url else "",
            duration=duration,
            labels=labels,
            provider_id=self.id,
        )

    def _clean_title(self, text: str) -> str:
        for prefix in ("مشاهدة فيلم", "مشاهدة مسلسل", "مشاهدة أنيمي"):
            text = text.replace(prefix, "")
        text = text.replace("HD", "").replace("اون لاين", "")
        return text.strip(" -")

    def _resolve_base_url(self, vid: str, extra: Optional[dict] = None) -> str:
        if extra and extra.get("watch_url"):
            if "q-drama.com" in extra["watch_url"]:
                return self.DOMAINS["series"]
            return self.DOMAINS["movies"]
        return self.DOMAINS["movies"]

    def get_video_details(self, vid: str, extra: Optional[dict] = None) -> VideoResult:
        base = self._resolve_base_url(vid, extra)
        watch_url = f"{base}/watch.php?vid={vid}"

        try:
            html = self._get(watch_url).text
        except Exception:
            base = self.DOMAINS["series"] if base == self.DOMAINS["movies"] else self.DOMAINS["movies"]
            watch_url = f"{base}/watch.php?vid={vid}"
            html = self._get(watch_url).text

        soup = BeautifulSoup(html, "lxml")

        title = self._extract_title(soup)
        description = self._extract_description(soup)
        categories = self._extract_categories(soup)
        thumb_url = self._extract_thumb(soup) or self._extract_thumb_from_js(html) or self._extract_og_image(soup)
        if thumb_url and not thumb_url.startswith("http"):
            thumb_url = urljoin(base, thumb_url)

        duration = self._extract_duration_from_js(html) or self._extract_duration_meta(soup)
        views = self._extract_views(soup) or self._extract_views_from_js(html)
        quality = self._extract_quality(html)

        video_data = VideoResult(
            vid=vid,
            title=title,
            watch_url=watch_url,
            thumb_url=thumb_url,
            duration=duration,
            description=description,
            categories=categories,
            views=views,
            quality=quality,
            provider_id=self.id,
        )
        video_data.is_series = self._check_is_series(soup, categories, title)
        if video_data.is_series:
            video_data.labels.append("مسلسل")

        video_data.direct_links = self._get_direct_links(vid, base)
        return video_data

    def _extract_title(self, soup) -> str:
        h1 = soup.find("h1", itemprop="name")
        if h1:
            return h1.get_text(strip=True)
        og_title = soup.find("meta", property="og:title")
        if og_title:
            return og_title.get("content", "")
        title_tag = soup.find("title")
        return title_tag.get_text(strip=True) if title_tag else ""

    def _extract_description(self, soup) -> str:
        desc_div = soup.find("div", class_="MetaDesc")
        if desc_div:
            return desc_div.get_text(strip=True)
        og_desc = soup.find("meta", property="og:description")
        if og_desc:
            return og_desc.get("content", "")
        return ""

    def _extract_categories(self, soup) -> List[str]:
        cats_div = soup.find("div", class_="CatsDesc")
        if cats_div:
            return [a.get_text(strip=True) for a in cats_div.find_all("a")]
        return []

    def _extract_thumb(self, soup) -> str:
        img = soup.find("img", class_="img-responsive")
        if img:
            return img.get("src") or img.get("data-echo", "")
        return ""

    def _extract_thumb_from_js(self, html: str) -> str:
        m = re.search(r'thumb_url:\s*"([^"]+)"', html)
        if m:
            return m.group(1)
        m = re.search(r'"thumb_url":\s*"([^"]+)"', html)
        if m:
            return m.group(1)
        return ""

    def _extract_og_image(self, soup) -> str:
        img = soup.find("meta", property="og:image")
        if img:
            return img.get("content", "")
        return ""

    def _extract_duration_from_js(self, html: str) -> str:
        m = re.search(r'duration_str:\s*"([^"]+)"', html)
        if m:
            return m.group(1)
        m = re.search(r'"duration_str":\s*"([^"]+)"', html)
        if m:
            return m.group(1)
        return ""

    def _extract_duration_meta(self, soup) -> str:
        meta = soup.find("meta", itemprop="duration")
        if meta:
            content = meta.get("content", "")
            m = re.search(r'PT([^"]+)', content)
            if m:
                return self._format_iso_duration(m.group(1))
        return ""

    def _format_iso_duration(self, iso_str: str) -> str:
        m = re.match(r'(\d+)H?(\d+)M?(\d+)S?', iso_str)
        if m:
            h, mi, s = m.groups()
            return f"{h}:{mi}:{s}"
        return iso_str

    def _extract_views(self, soup) -> int:
        interaction = soup.find(attrs={"itemprop": "interactionStatistic"})
        if interaction:
            count_meta = interaction.find("meta", attrs={"itemprop": "userInteractionCount"})
            if count_meta:
                try:
                    return int(count_meta.get("content", "0"))
                except ValueError:
                    pass
        return 0

    def _extract_views_from_js(self, html: str) -> int:
        m = re.search(r'views:\s*(\d+)', html)
        if m:
            return int(m.group(1))
        m = re.search(r'"views":\s*(\d+)', html)
        if m:
            return int(m.group(1))
        return 0

    def _extract_quality(self, html: str) -> str:
        m = re.search(r'quality["\']?\s*:\s*["\']?(\d+p)', html)
        if m:
            return m.group(1)
        meta = re.search(r'<meta property="og:video:width" content="(\d+)"', html)
        if meta:
            w = int(meta.group(1))
            if w >= 1920:
                return "1080p"
            elif w >= 1280:
                return "720p"
            return f"{w}p"
        return ""

    def _check_is_series(self, soup, categories, title) -> bool:
        for c in categories:
            if "مسلسل" in c or "series" in c.lower():
                return True
        if "مسلسل" in title:
            return True
        if soup.find("div", class_="AiredEPS"):
            return True
        return False

    def get_series_episodes(self, series_url_or_vid: str) -> List[VideoResult]:
        if series_url_or_vid.startswith("http"):
            watch_url = series_url_or_vid
            base = self.DOMAINS["series"] if "q-drama.com" in watch_url else self.DOMAINS["movies"]
        else:
            base = self.DOMAINS["series"]
            watch_url = f"{base}/watch.php?vid={series_url_or_vid}"

        try:
            html = self._get(watch_url).text
        except Exception:
            return []

        soup = BeautifulSoup(html, "lxml")
        episodes: List[VideoResult] = []

        eps_div = soup.find("div", class_="AiredEPS")
        if eps_div:
            for a in eps_div.find_all("a", href=True):
                href = a.get("href")
                ep_url = urljoin(base, href)
                vid = self._extract_vid(ep_url)
                if not vid:
                    continue
                ep_num = ""
                em = a.find("em")
                if em:
                    ep_num = em.get_text(strip=True)
                seen_text = a.get_text(strip=True) or em.get_text(strip=True) if em else ""
                title = f"الحلقة {ep_num}" if ep_num else (seen_text or vid)
                episodes.append(VideoResult(
                    vid=vid,
                    title=title,
                    watch_url=ep_url,
                    thumb_url="",
                    duration="",
                    provider_id=self.id,
                ))

        if not episodes:
            related = soup.find("h4", class_="RelatedVideos")
            if related:
                next_ul = related.find_next_sibling("ul")
                if next_ul:
                    for li in next_ul.find_all("li"):
                        a = li.find("a", href=True) or li.find("a")
                        if a and a.get("href"):
                            href = a.get("href")
                            ep_url = urljoin(base, href)
                            vid = self._extract_vid(ep_url)
                            if vid and not any(e.vid == vid for e in episodes):
                                ep_title = a.get("title", "") or a.get_text(strip=True)
                                episodes.append(VideoResult(
                                    vid=vid,
                                    title=ep_title,
                                    watch_url=ep_url,
                                    thumb_url="",
                                    duration="",
                                    provider_id=self.id,
                                ))

        seen = set()
        unique = []
        for e in episodes:
            if e.vid not in seen:
                seen.add(e.vid)
                unique.append(e)
        return unique

    def _get_direct_links(self, vid: str, base: str) -> List[Dict[str, str]]:
        links: List[Dict[str, str]] = []
        play_url = f"{base}/play.php?vid={vid}"

        try:
            html = self._get(play_url).text
            iframe_srcs = re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', html)
            for src in iframe_srcs:
                src = urljoin(base, src)
                try:
                    link_info = self._extract_video_source(src)
                    if link_info:
                        links.append(link_info)
                except Exception:
                    continue
        except Exception as e:
            logger.error(f"Play page error for vid={vid}: {e}")

        if not links:
            embed_url = f"{base}/embed.php?vid={vid}"
            try:
                html2 = self._get(embed_url).text
                iframe_srcs2 = re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', html2)
                for src in iframe_srcs2:
                    src = urljoin(base, src)
                    try:
                        link_info = self._extract_video_source(src)
                        if link_info:
                            links.append(link_info)
                    except Exception:
                        continue
            except Exception:
                pass

        return links

    def _extract_video_source(self, iframe_url: str) -> Optional[Dict[str, str]]:
        html = self._get(iframe_url).text

        m = re.search(r'file["\']?\s*:\s*["\']([^"\']+)', html)
        if m:
            file_url = m.group(1)
            if file_url.startswith("//"):
                file_url = "https:" + file_url
            elif file_url.startswith("/"):
                file_url = urljoin(iframe_url, file_url)

            quality = "HLS"
            if ".m3u8" in file_url:
                quality = "HLS (adaptive)"
            elif ".mp4" in file_url:
                m_q = re.search(r'(\d+p)', file_url)
                quality = m_q.group(1) if m_q else "MP4"

            return {
                "url": file_url,
                "quality": quality,
                "source": iframe_url,
                "type": "hls" if ".m3u8" in file_url else "mp4",
            }
        return None

    def get_web_app_url(self, video: VideoResult) -> str:
        """
        Return the Web App URL for playback.
        If a custom web_app_player_url is configured and direct link exists,
        it builds a custom player URL.
        Otherwise falls back to play.php/embed.php player.
        """
        vid = video.vid
        base = self._resolve_base_url(vid, {"watch_url": video.watch_url})

        # Check if direct stream link is available and custom web app player is configured
        if self.player_base_url and video.direct_links:
            direct_stream = video.direct_links[0]["url"]
            stream_enc = quote(direct_stream, safe='')
            title_enc = quote(video.title or '', safe='')
            thumb_enc = quote(video.thumb_url or '', safe='')
            return f"{self.player_base_url}?stream={stream_enc}&title={title_enc}&thumb={thumb_enc}"

        # Default player embed URL for WebApp Info
        return f"{base}/play.php?vid={vid}"
