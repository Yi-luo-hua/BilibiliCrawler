"""
用户空间动态爬取模块
"""
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import List, Dict, Optional, Callable

from src.api.bilibili_api import BilibiliAPI
from config.config import MAX_DYNAMICS_PAGES, MAX_REPLY_WORKERS

logger = logging.getLogger(__name__)


def _ts_str(ts: int) -> str:
    if ts:
        return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')
    return '不限'


class DynamicCrawler:
    """从B站爬取动态内容（支持用户空间和关注页）"""

    def __init__(self, progress_callback: Optional[Callable[[str], None]] = None,
                 cookie: str = ""):
        self.api = BilibiliAPI()
        if cookie:
            self.api.set_cookie(cookie)
        self.progress_callback = progress_callback or (lambda x: None)
        self._stop_flag = False

    def _log(self, message: str):
        logger.info(message)
        self.progress_callback(message)

    def stop(self):
        self._stop_flag = True
        self._log("正在停止动态爬取...")

    def crawl_dynamics(
        self,
        host_mid: int,
        keyword: str = "",
        max_pages: int = MAX_DYNAMICS_PAGES,
        start_time: int = 0,
        end_time: int = 0,
    ) -> List[Dict]:
        self._stop_flag = False
        all_dynamics = []
        page = 1
        offset = ""
        seen_ids = set()
        min_ts_seen = 0  # 当前页最早的时间戳，用于提前停止

        self._log(f"开始爬取用户 {host_mid} 的空间动态...")
        if keyword:
            self._log(f"关键词过滤: {keyword}")
        if start_time or end_time:
            self._log(f"时间范围: {_ts_str(start_time)} ~ {_ts_str(end_time)}")

        while page <= max_pages and not self._stop_flag:
            self._log(f"正在爬取第 {page} 页动态...")

            data = self.api.get_user_dynamics(host_mid, offset=offset)
            if not data or not data.get('data'):
                self._log("未获取到数据，可能已到达最后一页")
                break

            items = data['data'].get('items', [])
            if not items:
                self._log("动态列表为空")
                break

            new_items = [it for it in items if it.get('id_str') not in seen_ids]
            if not new_items:
                self._log("检测到重复数据，停止")
                break

            seen_ids.update(it.get('id_str') for it in items)

            # 记录本页最早时间戳
            page_ts = []
            for it in new_items:
                author = it.get('modules', {}).get('module_author', {})
                ts = author.get('pub_ts', 0)
                if ts:
                    page_ts.append(ts)
            if page_ts:
                min_ts_seen = min(page_ts)

            before = len(all_dynamics)
            for item in new_items:
                if self._stop_flag:
                    break
                dynamic = self._process_dynamic(item)
                if dynamic:
                    all_dynamics.append(dynamic)

            self._log(f"第 {page} 页: 获取 {len(new_items)} 条，"
                      f"新增 {len(all_dynamics) - before} 条")

            # 提前停止：当前页最早动态已超出时间范围
            if start_time and min_ts_seen and min_ts_seen < start_time:
                self._log("已到达指定时间范围起点，停止翻页")
                break

            has_more = data['data'].get('has_more', False)
            offset = data['data'].get('offset', "")

            if has_more and offset:
                page += 1
            else:
                self._log("已到达最后一页")
                break

        self._log(f"爬取完成！共获取 {len(all_dynamics)} 条动态")
        all_dynamics = self._enrich_and_filter(all_dynamics, keyword, start_time, end_time)
        return all_dynamics

    def crawl_following_feed(
        self,
        keyword: str = "",
        max_pages: int = MAX_DYNAMICS_PAGES,
        start_time: int = 0,
        end_time: int = 0,
    ) -> List[Dict]:
        """爬取关注页动态流（需要Cookie）"""
        self._stop_flag = False
        all_dynamics = []
        page = 1
        offset = ""
        seen_ids = set()
        min_ts_seen = 0

        self._log("开始爬取关注页动态流...")
        if keyword:
            self._log(f"关键词过滤: {keyword}")
        if start_time or end_time:
            self._log(f"时间范围: {_ts_str(start_time)} ~ {_ts_str(end_time)}")

        while page <= max_pages and not self._stop_flag:
            self._log(f"正在爬取第 {page} 页动态...")

            data = self.api.get_following_feed(offset=offset)
            if not data or not data.get('data'):
                self._log("未获取到数据，可能已到达最后一页")
                break

            items = data['data'].get('items', [])
            if not items:
                self._log("动态列表为空")
                break

            new_items = [it for it in items if it.get('id_str') not in seen_ids]
            if not new_items:
                self._log("检测到重复数据，停止")
                break

            seen_ids.update(it.get('id_str') for it in items)

            # 记录本页最早时间戳
            page_ts = []
            for it in new_items:
                author = it.get('modules', {}).get('module_author', {})
                ts = author.get('pub_ts', 0)
                if ts:
                    page_ts.append(ts)
            if page_ts:
                min_ts_seen = min(page_ts)

            before = len(all_dynamics)
            for item in new_items:
                if self._stop_flag:
                    break
                dynamic = self._process_dynamic(item)
                if dynamic:
                    all_dynamics.append(dynamic)

            self._log(f"第 {page} 页: 获取 {len(new_items)} 条，"
                      f"新增 {len(all_dynamics) - before} 条")

            # 提前停止：当前页最早动态已超出时间范围
            if start_time and min_ts_seen and min_ts_seen < start_time:
                self._log("已到达指定时间范围起点，停止翻页")
                break

            has_more = data['data'].get('has_more', False)
            offset = data['data'].get('offset', "")

            if has_more and offset:
                page += 1
            else:
                self._log("已到达最后一页")
                break

        self._log(f"爬取完成！共获取 {len(all_dynamics)} 条动态")
        all_dynamics = self._enrich_and_filter(all_dynamics, keyword, start_time, end_time)
        return all_dynamics

    def _enrich_and_filter(self, dynamics: List[Dict], keyword: str = "",
                           start_time: int = 0, end_time: int = 0) -> List[Dict]:
        """充实空内容的动态（OPUS页面回退），然后按时间范围和关键词过滤"""
        # 时间过滤
        if start_time or end_time:
            filtered = []
            for d in dynamics:
                ts = d.get('timestamp', 0)
                if start_time and ts < start_time:
                    continue
                if end_time and ts > end_time:
                    continue
                filtered.append(d)
            dynamics = filtered
            self._log(f"时间过滤后剩余 {len(dynamics)} 条")

        # 找出需要充实文字的动态
        empty_ids = [d['dynamic_id'] for d in dynamics
                     if (not d['content']
                         or d['content'] == '[无文字内容]'
                         or d['content'].startswith('[图片动态'))]

        if empty_ids:
            self._log(f"正在补齐 {len(empty_ids)} 条动态的文字内容...")
            enriched = self._enrich_from_opus(empty_ids)
            for d in dynamics:
                if d['dynamic_id'] in enriched:
                    text = enriched[d['dynamic_id']]
                    old = d['content']
                    img_urls = []
                    if old.startswith('[图片动态'):
                        img_urls = re.findall(
                            r'https?://\S+?\.(?:jpg|jpeg|png|webp|gif)(?:\?\S*)?',
                            old,
                            flags=re.IGNORECASE,
                        )
                    if img_urls:
                        text = text + '\n' + ' '.join(img_urls)
                    d['content'] = text

        if keyword:
            kw = keyword.lower()
            dynamics = [d for d in dynamics if kw in d.get('content', '').lower()]
            self._log(f"关键词过滤后剩余 {len(dynamics)} 条")

        return dynamics

    def _enrich_from_opus(self, dy_ids: List[str]) -> Dict[str, str]:
        """并发获取OPUS页面文字"""
        session = self.api.session
        result = {}
        completed = [0]

        def fetch_one(dy_id):
            if self._stop_flag:
                return dy_id, ""
            try:
                r = session.get(
                    f'https://www.bilibili.com/opus/{dy_id}',
                    timeout=10,
                    headers={'Referer': 'https://www.bilibili.com/'},
                )
                if r.status_code != 200:
                    return dy_id, ""
                state = self._extract_initial_state(r.text)
                if not state:
                    return dy_id, ""
                words = []
                for mod in state.get('detail', {}).get('modules', []):
                    for p in mod.get('module_content', {}).get('paragraphs', []):
                        text_obj = p.get('text', {})
                        if isinstance(text_obj, str):
                            text_obj = json.loads(text_obj)
                        for node in text_obj.get('nodes', []):
                            if node.get('type') == 'TEXT_NODE_TYPE_WORD':
                                words.append(node['word']['words'])
                            elif node.get('type') == 'TEXT_NODE_TYPE_RICH':
                                words.append(node['rich'].get('text', ''))
                return dy_id, ''.join(words)
            except Exception:
                return dy_id, ""

        with ThreadPoolExecutor(max_workers=MAX_REPLY_WORKERS) as executor:
            futures = {executor.submit(fetch_one, did): did for did in dy_ids}
            for f in as_completed(futures):
                if self._stop_flag:
                    break
                dy_id, text = f.result()
                if text:
                    result[dy_id] = text
                completed[0] += 1
                if completed[0] % 50 == 0:
                    self._log(f"  文字补齐进度: {completed[0]}/{len(dy_ids)}")

        self._log(f"成功补齐 {len(result)} 条动态文字")
        return result

    @staticmethod
    def _extract_initial_state(html: str) -> Optional[Dict]:
        match = re.search(r'window\.__INITIAL_STATE__\s*=\s*', html)
        if not match:
            return None

        payload = html[match.end():].lstrip()
        if not payload.startswith('{'):
            return None

        try:
            state, _ = json.JSONDecoder().raw_decode(payload)
            return state if isinstance(state, dict) else None
        except json.JSONDecodeError:
            logger.debug("解析 __INITIAL_STATE__ 失败", exc_info=True)
            return None

    def _process_dynamic(self, item: Dict) -> Optional[Dict]:
        try:
            id_str = item.get('id_str', '')
            dynamic_type = item.get('type', '')
            modules = item.get('modules', {})

            # 文本内容
            content = ""
            mod_dyn = modules.get('module_dynamic', {})
            desc = mod_dyn.get('desc', {})
            if desc and desc.get('text'):
                content = desc['text']

            if not content:
                major = mod_dyn.get('major', {})
                if major:
                    archive = major.get('archive', {})
                    if archive and not content:
                        content = archive.get('title', '')
                    opus = major.get('opus', {})
                    if opus and not content:
                        summary = opus.get('summary', {})
                        content = summary.get('text', content)
                    article = major.get('article', {})
                    if article and not content:
                        content = article.get('title', content)
                    # 直播推荐：解析 live_rcmd.content JSON
                    live_rcmd = major.get('live_rcmd', {})
                    if live_rcmd and not content:
                        try:
                            raw = live_rcmd.get('content', '{}')
                            lc = json.loads(raw) if isinstance(raw, str) else raw
                            live_info = lc.get('live_play_info', {})
                            content = live_info.get('title', '') or live_info.get('live_title', '') or live_info.get('area_name', '')
                        except Exception:
                            pass
                    # 图文动态：无文字时显示图片数量和全部图片链接
                    draw = major.get('draw', {})
                    if draw and not content:
                        items_list = draw.get('items', [])
                        if items_list:
                            urls = []
                            for img in items_list:
                                url = (
                                    img.get('src')
                                    or img.get('url')
                                    or img.get('img_src')
                                    or img.get('picture')
                                    or ''
                                )
                                if url:
                                    urls.append(url)
                            content = f'[图片动态×{len(urls)}]' + (f' {" ".join(urls)}' if urls else '')

            if not content:
                content = '[无文字内容]'

            # 作者信息
            author = modules.get('module_author', {})
            pub_ts = author.get('pub_ts', 0)
            username = author.get('name', '')

            # 统计信息
            stat = modules.get('module_stat', {})

            def _extract_count(val):
                if isinstance(val, dict):
                    return val.get('count', 0)
                return val if isinstance(val, (int, float)) else 0

            return {
                'dynamic_id': id_str,
                'type': dynamic_type,
                'content': content,
                'username': username,
                'timestamp': pub_ts,
                'publish_time': datetime.fromtimestamp(pub_ts).strftime('%Y-%m-%d %H:%M:%S') if pub_ts else '',
                'like_count': _extract_count(stat.get('like', 0)),
                'comment_count': _extract_count(stat.get('comment', 0)),
                'forward_count': _extract_count(stat.get('forward', 0)),
            }
        except Exception as e:
            logger.warning(f"处理动态项时出错: {e}")
            return None
