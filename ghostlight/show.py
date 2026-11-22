from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import Config
from .db import Database


def _esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _base(cfg: Config) -> str:
    for key in ("social.public_url", "studio.public_url"):
        value = str(cfg.get(key, "") or "").strip()
        if value:
            return value.rstrip("/")
    return ""


def _absolute(cfg: Config, path: str) -> str:
    base = _base(cfg)
    return f"{base}{path}" if base else path


def _poster(video: dict[str, Any]) -> str:
    poster = Path(str(video.get("poster_path") or ""))
    if poster.is_file():
        return f"/api/videos/{video['id']}/file/poster"
    thumb = Path(str(video.get("thumb_path") or ""))
    if thumb.is_file():
        return f"/api/videos/{video['id']}/file/thumb"
    return ""


def _date(video: dict[str, Any]) -> str:
    raw = str(video.get("published_at") or video.get("created_at") or "")
    try:
        return datetime.fromisoformat(raw).strftime("%d %B %Y")
    except ValueError:
        return ""


def _duration(seconds: Any) -> str:
    try:
        total = int(float(seconds or 0))
    except (TypeError, ValueError):
        return ""
    if total <= 0:
        return ""
    minutes, secs = divmod(total, 60)
    return f"{minutes}:{secs:02d}" if minutes < 60 else f"{minutes // 60}:{minutes % 60:02d}:{secs:02d}"


def _published(db: Database, limit: int = 60) -> list[dict[str, Any]]:
    films = db.list_videos(limit=max(1, min(limit, 200)), status="published")
    return [film for film in films if not film.get("archived")]


def _channels(db: Database) -> dict[str, dict[str, Any]]:
    return {str(channel["id"]): channel for channel in db.list_channels()}


def _paragraphs(text: str) -> str:
    blocks = [block.strip() for block in str(text or "").split("\n\n") if block.strip()]
    return "".join(f"<p>{_esc(block).replace(chr(10), '<br />')}</p>" for block in blocks)


STYLE = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body {
  margin: 0; min-height: 100vh; color: #f2ead9;
  font: 17px/1.65 Georgia, 'Times New Roman', serif;
  background:
    radial-gradient(1200px 700px at 12% -10%, rgba(94, 242, 214, .16), transparent 60%),
    radial-gradient(900px 600px at 88% 0%, rgba(255, 212, 121, .12), transparent 55%),
    linear-gradient(180deg, #070b16 0%, #0b1224 55%, #070b16 100%);
}
a { color: #ffd479; }
.wrap { width: min(1120px, 92vw); margin: 0 auto; padding: 56px 0 80px; }
.kicker { font: 700 12px/1.4 'Trebuchet MS', sans-serif; letter-spacing: .34em; text-transform: uppercase; color: #5ef2d6; }
.brand { font: 700 13px/1.4 'Trebuchet MS', sans-serif; letter-spacing: .42em; text-transform: uppercase; color: rgba(242, 234, 217, .72); }
h1 { font-size: clamp(38px, 6vw, 68px); line-height: 1.04; margin: 18px 0 12px; font-weight: 400; }
h1 em { color: #ffd479; font-style: italic; }
.lede { max-width: 58ch; color: rgba(242, 234, 217, .78); font-size: 19px; }
.top { display: flex; justify-content: space-between; align-items: baseline; gap: 18px; flex-wrap: wrap; }
.rss { font: 700 12px/1 'Trebuchet MS', sans-serif; letter-spacing: .18em; text-transform: uppercase; text-decoration: none; color: rgba(242, 234, 217, .66); border: 1px solid rgba(242, 234, 217, .22); border-radius: 999px; padding: 9px 14px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(310px, 1fr)); gap: 26px; margin-top: 44px; }
.card { display: flex; flex-direction: column; background: rgba(12, 19, 36, .78); border: 1px solid rgba(255, 255, 255, .07); border-radius: 18px; overflow: hidden; text-decoration: none; color: inherit; box-shadow: 0 24px 60px rgba(0, 0, 0, .35); transition: transform .18s ease, border-color .18s ease; }
.card:hover { transform: translateY(-3px); border-color: rgba(94, 242, 214, .35); }
.art { aspect-ratio: 16 / 9; background: linear-gradient(135deg, #101a33, #1c2450 55%, #101a33); display: block; width: 100%; object-fit: cover; }
.art.empty { display: grid; place-items: center; font-size: 40px; color: rgba(255, 212, 121, .55); }
.card-body { padding: 20px 22px 24px; display: flex; flex-direction: column; gap: 8px; }
.card-body h2 { font-size: 23px; line-height: 1.22; margin: 0; font-weight: 400; }
.meta { font: 600 11px/1.4 'Trebuchet MS', sans-serif; letter-spacing: .16em; text-transform: uppercase; color: rgba(242, 234, 217, .55); }
.hook { color: rgba(242, 234, 217, .74); font-size: 15.5px; margin: 0; }
.empty-state { margin-top: 60px; padding: 54px 30px; border: 1px dashed rgba(242, 234, 217, .18); border-radius: 20px; text-align: center; color: rgba(242, 234, 217, .6); }
.film { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(280px, .65fr); gap: 40px; margin-top: 34px; }
.player { width: 100%; border-radius: 18px; background: #000; box-shadow: 0 30px 70px rgba(0, 0, 0, .45); }
.poster { width: 100%; border-radius: 18px; border: 1px solid rgba(255, 255, 255, .08); }
.side { display: flex; flex-direction: column; gap: 16px; }
.side h2 { font-size: 14px; letter-spacing: .26em; text-transform: uppercase; color: #5ef2d6; font-family: 'Trebuchet MS', sans-serif; margin: 0; }
.side p { margin: 0; color: rgba(242, 234, 217, .78); }
.tags { display: flex; flex-wrap: wrap; gap: 8px; }
.tag { font: 600 11px/1 'Trebuchet MS', sans-serif; letter-spacing: .1em; text-transform: uppercase; border: 1px solid rgba(94, 242, 214, .3); color: rgba(94, 242, 214, .85); border-radius: 999px; padding: 7px 10px; }
.actions { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 6px; }
.btn { display: inline-block; text-decoration: none; font: 700 12px/1 'Trebuchet MS', sans-serif; letter-spacing: .16em; text-transform: uppercase; padding: 13px 18px; border-radius: 999px; border: 1px solid rgba(255, 212, 121, .45); color: #ffd479; }
.btn.solid { background: #ffd479; color: #10131f; border-color: #ffd479; }
.back { text-decoration: none; color: rgba(242, 234, 217, .6); font: 600 12px/1 'Trebuchet MS', sans-serif; letter-spacing: .18em; text-transform: uppercase; }
footer { margin-top: 70px; padding-top: 26px; border-top: 1px solid rgba(255, 255, 255, .08); display: flex; justify-content: space-between; gap: 16px; flex-wrap: wrap; color: rgba(242, 234, 217, .45); font: 12px/1.6 'Trebuchet MS', sans-serif; letter-spacing: .12em; text-transform: uppercase; }
@media (max-width: 820px) { .film { grid-template-columns: 1fr; } .wrap { padding-top: 34px; } }
"""


def _page(cfg: Config, title: str, description: str, body: str, image: str = "") -> str:
    studio = str(cfg.get("studio.name", "Ghostlight Studio"))
    og = [
        f'<meta property="og:title" content="{_esc(title)}" />',
        f'<meta property="og:description" content="{_esc(description)}" />',
        '<meta property="og:type" content="website" />',
        f'<meta name="description" content="{_esc(description)}" />',
    ]
    if image:
        og.append(f'<meta property="og:image" content="{_esc(_absolute(cfg, image))}" />')
    base = _base(cfg)
    if base:
        og.append(f'<meta property="og:url" content="{_esc(base)}/show" />')
    return (
        "<!DOCTYPE html><html lang=\"en\"><head>"
        f"<meta charset=\"utf-8\" /><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />"
        f"<title>{_esc(title)} — {_esc(studio)}</title>"
        + "".join(og)
        + f'<link rel="alternate" type="application/rss+xml" title="{_esc(studio)}" href="/feed.xml" />'
        f"<style>{STYLE}</style></head><body><div class=\"wrap\">{body}"
        "<footer><span>No faces. No repeats.</span>"
        f"<span>{_esc(studio)} · every film written, scored, painted and uploaded by the machine.</span></footer>"
        "</div></body></html>"
    )


def render_index(cfg: Config, db: Database, limit: int = 60) -> str:
    studio = str(cfg.get("studio.name", "Ghostlight Studio"))
    tagline = str(cfg.get("studio.tagline", ""))
    channels = _channels(db)
    films = _published(db, limit)
    cards = []
    for film in films:
        channel = channels.get(str(film.get("channel_id") or ""), {})
        poster = _poster(film)
        art = (
            f'<img class="art" src="{_esc(poster)}" alt="" loading="lazy" />'
            if poster else '<span class="art empty">✳</span>'
        )
        meta = " · ".join(part for part in (
            str(channel.get("name") or ""),
            "Short" if film.get("format") == "short" else "Long form",
            _duration(film.get("duration")),
            _date(film),
        ) if part)
        cards.append(
            f'<a class="card" href="/show/{_esc(film["id"])}">{art}'
            '<span class="card-body">'
            f'<span class="meta">{_esc(meta)}</span>'
            f"<h2>{_esc(film.get('title') or 'Untitled')}</h2>"
            f"<span class=\"hook\">{_esc(film.get('hook') or '')}</span>"
            "</span></a>"
        )
    shelf = (
        f'<div class="grid">{"".join(cards)}</div>' if cards else
        '<div class="empty-state"><p>The curtain is still down.</p>'
        '<p>Films appear here the moment the studio publishes one.</p></div>'
    )
    body = (
        '<header class="top"><span class="brand">' + _esc(studio) + '</span>'
        '<a class="rss" href="/feed.xml">RSS</a></header>'
        f'<h1>The <em>show.</em></h1>'
        f'<p class="lede">{_esc(tagline or "One strange idea at a time.")}</p>'
        f"{shelf}"
    )
    return _page(cfg, studio, tagline or "One strange idea at a time.", body,
                 image=_poster(films[0]) if films else "")


def render_film(cfg: Config, db: Database, video: dict[str, Any]) -> str:
    channels = _channels(db)
    channel = channels.get(str(video.get("channel_id") or ""), {})
    script = video.get("script") or {}
    description = str(script.get("description") or video.get("description") or "")
    hook = str(video.get("hook") or script.get("hook") or "")
    poster = _poster(video)
    playable = Path(str(video.get("video_path") or "")).is_file()
    if playable:
        screen = (
            f'<video class="player" controls preload="metadata"'
            + (f' poster="{_esc(poster)}"' if poster else "")
            + f'><source src="/api/videos/{_esc(video["id"])}/file/video" type="video/mp4" /></video>'
        )
    elif poster:
        screen = f'<img class="poster" src="{_esc(poster)}" alt="" />'
    else:
        screen = '<div class="poster art empty">✳</div>'
    meta = " · ".join(part for part in (
        str(channel.get("name") or ""),
        "Short" if video.get("format") == "short" else "Long form",
        _duration(video.get("duration")),
        _date(video),
    ) if part)
    tags = [str(tag) for tag in (video.get("tags") or []) if str(tag).strip()][:8]
    tag_html = "".join(f'<span class="tag">{_esc(tag)}</span>' for tag in tags)
    youtube = str(video.get("youtube_url") or "")
    actions = [f'<a class="btn" href="/show">All films</a>']
    if youtube:
        actions.append(f'<a class="btn solid" href="{_esc(youtube)}" rel="noopener">Watch on YouTube</a>')
    body = (
        '<header class="top"><a class="back" href="/show">← The show</a>'
        '<a class="rss" href="/feed.xml">RSS</a></header>'
        f'<span class="kicker">{_esc(meta)}</span>'
        f'<h1>{_esc(video.get("title") or "Untitled")}</h1>'
        '<div class="film">'
        f"<div>{screen}</div>"
        '<aside class="side">'
        + (f"<div><h2>The idea</h2>{_paragraphs(hook)}</div>" if hook else "")
        + (f"<div><h2>About this film</h2>{_paragraphs(description)}</div>" if description else "")
        + (f'<div class="tags">{tag_html}</div>' if tag_html else "")
        + f'<div class="actions">{"".join(actions)}</div>'
        "</aside></div>"
    )
    summary = hook or description or "A film from the Ghostlight Studio."
    return _page(cfg, str(video.get("title") or "A film"), summary, body, image=poster)
