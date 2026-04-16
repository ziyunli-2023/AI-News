"""Email notifier — sends digest at 07:00, 12:00 and 20:00 daily."""

import logging
import smtplib
import threading
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import config
import ai_processor
import storage

logger = logging.getLogger(__name__)

# Send digest at these hours (local time) → window covers since previous send
SEND_HOURS = {7, 12, 20}
SEND_WINDOWS = {7: 11, 12: 5, 20: 8}   # hour → look-back hours
SEND_LABELS  = {7: "Morning", 12: "Midday", 20: "Evening"}


def _ensure_translations(posts: list[dict], tweets: list[dict]):
    """
    Make sure every post has title_zh/summary_zh and every tweet has text_zh.
    Calls DeepSeek for any missing pieces and persists results to SQLite so the
    web UI sees the same translations next time.
    """
    if not config.DEEPSEEK_API_KEY:
        return

    # Posts: collect missing title + summary in a flat list, translate, scatter back
    post_targets = []  # list of (post_dict, field_name, original_text)
    for b in posts:
        p = b["item"]
        if not p.get("title_zh") and p.get("title"):
            post_targets.append((p, "title_zh", p["title"]))
        if not p.get("summary_zh") and p.get("summary"):
            post_targets.append((p, "summary_zh", p["summary"][:500]))

    if post_targets:
        # Chunk into batches of 10 to stay within max_tokens
        CHUNK = 10
        translated = []
        texts = [t[2] for t in post_targets]
        for i in range(0, len(texts), CHUNK):
            translated.extend(ai_processor.translate_texts(texts[i:i + CHUNK]))
        for (p, field, _orig), zh in zip(post_targets, translated):
            if zh and zh != _orig:
                p[field] = zh
        # Persist per-post (one UPDATE each — small batches, fine)
        seen = set()
        for p, _field, _ in post_targets:
            if p.get("id") and p["id"] not in seen and (p.get("title_zh") or p.get("summary_zh")):
                seen.add(p["id"])
                try:
                    storage.update_post_translation(
                        p["id"], p.get("title_zh", ""), p.get("summary_zh", "")
                    )
                except Exception as e:
                    logger.warning("persist post translation failed: %s", e)

    # Tweets
    tweet_targets = [b["item"] for b in tweets if not b["item"].get("text_zh") and b["item"].get("text")]
    if tweet_targets:
        CHUNK = 10
        texts = [t["text"] for t in tweet_targets]
        translated = []
        for i in range(0, len(texts), CHUNK):
            translated.extend(ai_processor.translate_texts(texts[i:i + CHUNK]))
        for t, zh in zip(tweet_targets, translated):
            if zh and zh != t["text"]:
                t["text_zh"] = zh
                try:
                    storage.update_tweet_translation(t["id"], zh)
                except Exception as e:
                    logger.warning("persist tweet translation failed: %s", e)


class EmailNotifier:
    def __init__(self):
        self._queue: list[dict] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if not config.EMAIL_SENDER or not config.EMAIL_APP_PASSWORD:
            logger.warning("Email not configured — notifier disabled")
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="email-notifier")
        self._thread.start()
        logger.info("Email notifier started — daily digest at %s → %s",
                    ", ".join(f"{h:02d}:00" for h in sorted(SEND_HOURS)),
                    ", ".join(config.EMAIL_RECIPIENTS))

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def enqueue(self, item: dict, item_type: str = "post"):
        """Accumulate new items for the next digest."""
        with self._lock:
            self._queue.append({"item": item, "type": item_type})

    def _build_batch(self, slot_time: datetime, window_hours: int) -> list[dict]:
        """Fetch posts/tweets for the window ending at slot_time."""
        from datetime import timedelta
        cutoff = (slot_time - timedelta(hours=window_hours)).isoformat()
        posts  = [p for p in storage.get_latest_posts(limit=40)
                  if (p.get("published") or p.get("fetched_at", "")) >= cutoff]
        tweets = [t for t in storage.get_latest_tweets(limit=30)
                  if t.get("created_at", "") >= cutoff]
        return [{"item": p, "type": "post"} for p in posts] + \
               [{"item": t, "type": "tweet"} for t in tweets]

    def _try_send_slot(self, date_str: str, slot_hour: int, slot_time: datetime, label: str):
        """Build and send digest for one slot; returns True on success."""
        batch = self._build_batch(slot_time, SEND_WINDOWS[slot_hour])

        # Drain any in-memory queue items not yet in DB
        with self._lock:
            queued = list(self._queue)
            self._queue.clear()
        existing_ids = {b["item"].get("id") for b in batch}
        for q in queued:
            if q["item"].get("id") not in existing_ids:
                batch.append(q)

        if batch:
            try:
                self._send(batch, label=label)
                storage.record_digest_sent(date_str, slot_hour)
                return True
            except Exception as e:
                logger.error("Failed to send email: %s", e)
                with self._lock:
                    self._queue = queued + self._queue
                return False
        else:
            logger.info("Digest %s %02d:00 — no items in window, skipping", date_str, slot_hour)
            storage.record_digest_sent(date_str, slot_hour)
            return True

    def _run(self):
        from datetime import timedelta
        # Grace period: catch up today's slot if woke up within 2 hours
        CATCHUP_GRACE_HOURS = 2

        while not self._stop.is_set():
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")

            # ── Today's scheduled and grace-period sends ───────────────────
            for slot_hour in sorted(SEND_HOURS):
                slot_time = now.replace(hour=slot_hour, minute=0, second=0, microsecond=0)
                if slot_time > now:
                    continue
                if storage.was_digest_sent(today, slot_hour):
                    continue

                minutes_late = (now - slot_time).total_seconds() / 60
                if minutes_late > CATCHUP_GRACE_HOURS * 60:
                    storage.record_digest_sent(today, slot_hour)
                    logger.info("Digest slot %02d:00 missed by %.0f min — skipping", slot_hour, minutes_late)
                    continue

                label = SEND_LABELS[slot_hour]
                if minutes_late > 5:
                    label += " (catch-up)"
                self._try_send_slot(today, slot_hour, slot_time, label)

            # ── Cross-day catch-up: send the most recent missed past slot ──
            # Collect all unsent slots from previous days (up to 7 days back),
            # ordered most-recent-first. Send only the latest one; silently
            # mark the rest as done to avoid a flood of old digests.
            missed_past = []
            for days_back in range(1, 8):
                check_date = now - timedelta(days=days_back)
                date_str = check_date.strftime("%Y-%m-%d")
                for slot_hour in sorted(SEND_HOURS, reverse=True):
                    slot_time = check_date.replace(hour=slot_hour, minute=0, second=0, microsecond=0)
                    if not storage.was_digest_sent(date_str, slot_hour):
                        missed_past.append((date_str, slot_hour, slot_time))

            if missed_past:
                # Send only the most recent missed slot
                date_str, slot_hour, slot_time = missed_past[0]
                label = f"{SEND_LABELS[slot_hour]} (catch-up from {date_str})"
                self._try_send_slot(date_str, slot_hour, slot_time, label)
                # Silently discard all older missed slots
                for old_date, old_hour, _ in missed_past[1:]:
                    storage.record_digest_sent(old_date, old_hour)
                    logger.info("Cross-day slot %s %02d:00 — marked skipped (superseded by catch-up)",
                                old_date, old_hour)

            # Sleep 60s between checks
            self._stop.wait(60)

    def _send(self, batch: list[dict], label: str = "Digest"):
        posts  = [b for b in batch if b["type"] == "post"]
        tweets = [b for b in batch if b["type"] == "tweet"]
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

        # ── Ensure bilingual: fill any missing _zh translations on demand ──
        _ensure_translations(posts, tweets)

        subject = f"🤖 AI News {label} — {len(batch)} item(s) · {now_str}"

        # ── AI digest summary ──────────────────────────────────────────────
        digest_summary = ai_processor.generate_digest_summary(batch)

        # ── HTML body ──────────────────────────────────────────────────────
        html_parts = ["""
<html><body style='font-family:-apple-system,BlinkMacSystemFont,sans-serif;
  max-width:680px;margin:auto;padding:24px;background:#fff;color:#222;'>
"""]
        html_parts.append(f"""
  <div style='background:#0f3460;color:#fff;padding:20px 24px;border-radius:10px 10px 0 0;'>
    <h1 style='margin:0;font-size:20px;'>🤖 AI News {label}</h1>
    <p style='margin:4px 0 0;font-size:13px;opacity:.8;'>{now_str} &nbsp;·&nbsp; {len(batch)} new item(s)</p>
  </div>
  <div style='background:#f4f6fb;padding:16px 24px;border-radius:0 0 10px 10px;margin-bottom:24px;'>
    <span style='font-size:13px;color:#555;'>📰 {len(posts)} blog posts &nbsp;&nbsp; 🐦 {len(tweets)} tweets</span>
  </div>
""")
        # Digest summary block — bullet points, one per line
        if digest_summary:
            bullets_html = "".join(
                f"<li style='margin:6px 0;font-size:14px;color:#333;line-height:1.6;'>{b}</li>"
                for b in digest_summary
            )
            html_parts.append(f"""
  <div style='background:#fffbeb;border:1px solid #fcd34d;border-radius:8px;
              padding:16px 20px;margin-bottom:24px;'>
    <div style='font-size:12px;font-weight:600;color:#92400e;margin-bottom:10px;'>📋 今日 AI 资讯摘要</div>
    <ul style='margin:0;padding-left:20px;'>{bullets_html}</ul>
  </div>
""")

        if posts:
            html_parts.append(f"<h2 style='font-size:16px;color:#0f3460;border-bottom:2px solid #0f3460;padding-bottom:8px;'>📰 Blog Posts ({len(posts)})</h2>")
            for b in posts:
                p = b["item"]
                date = p.get("published", "")[:16].replace("T", " ") if p.get("published") else ""
                title_zh   = p.get("title_zh", "")
                summary_zh = p.get("summary_zh", "")
                zh_title_html   = f"<div style='font-size:13px;color:#888;margin-top:3px;'>{title_zh}</div>" if title_zh else ""
                zh_summary_html = f"<p style='margin:6px 0 0;font-size:12px;color:#aaa;line-height:1.5;'>{summary_zh[:200]}…</p>" if summary_zh else ""
                html_parts.append(f"""
  <div style='margin-bottom:18px;padding:16px;border-left:4px solid #0f3460;
              background:#f8f9fa;border-radius:0 8px 8px 0;'>
    <div style='font-size:11px;color:#888;margin-bottom:6px;'>{p['source']} · {date}</div>
    <a href='{p['url']}' style='font-size:15px;font-weight:600;color:#0f3460;text-decoration:none;
       line-height:1.4;display:block;'>{p['title']}</a>
    {zh_title_html}
    {'<p style="margin:8px 0 0;font-size:13px;color:#555;line-height:1.5;">' + p["summary"][:200] + "…</p>" if p.get("summary") else ""}
    {zh_summary_html}
    <a href='{p['url']}' style='display:inline-block;margin-top:10px;font-size:12px;
       color:#fff;background:#0f3460;padding:5px 12px;border-radius:4px;text-decoration:none;'>
      Read →</a>
  </div>""")

        if tweets:
            html_parts.append(f"<h2 style='font-size:16px;color:#1d9bf0;border-bottom:2px solid #1d9bf0;padding-bottom:8px;margin-top:28px;'>🐦 Tweets ({len(tweets)})</h2>")
            for b in tweets:
                t = b["item"]
                date = t.get("created_at", "")[:16].replace("T", " ")
                text_zh = t.get("text_zh", "")
                zh_block = (
                    f"<p style='margin:6px 0 0;font-size:13px;color:#666;line-height:1.6;'>{text_zh}</p>"
                    if text_zh else ""
                )
                html_parts.append(f"""
  <div style='margin-bottom:18px;padding:16px;border-left:4px solid #1d9bf0;
              background:#f0f8ff;border-radius:0 8px 8px 0;'>
    <div style='font-size:11px;color:#888;margin-bottom:6px;'>@{t['username']} · {date}</div>
    <p style='margin:0;font-size:14px;color:#222;line-height:1.6;'>{t['text']}</p>
    {zh_block}
    <div style='margin-top:10px;font-size:12px;color:#888;'>
      ❤ {t.get('likes',0)} &nbsp;&nbsp; 🔁 {t.get('retweets',0)}
      &nbsp;&nbsp;
      <a href='{t.get("url","")}' style='color:#1d9bf0;text-decoration:none;'>View tweet →</a>
    </div>
  </div>""")

        html_parts.append("""
  <div style='margin-top:32px;padding-top:16px;border-top:1px solid #eee;
              font-size:11px;color:#aaa;text-align:center;'>
    AI News Monitor · Sent automatically
  </div>
</body></html>""")
        html_body = "".join(html_parts)

        # ── Plain text fallback ────────────────────────────────────────────
        text_lines = [f"AI News {label} — {now_str}\n{len(batch)} new item(s)\n"]
        for b in batch:
            if b["type"] == "post":
                p = b["item"]
                line = f"[{p['source']}] {p['title']}"
                if p.get("title_zh"):
                    line += f"\n  {p['title_zh']}"
                line += f"\n{p['url']}\n"
                text_lines.append(line)
            else:
                t = b["item"]
                line = f"@{t['username']}: {t['text'][:140]}"
                if t.get("text_zh"):
                    line += f"\n  {t['text_zh'][:140]}"
                line += f"\n{t.get('url','')}\n"
                text_lines.append(line)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(config.EMAIL_SENDER, config.EMAIL_APP_PASSWORD)
            for recipient in config.EMAIL_RECIPIENTS:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject
                msg["From"]    = config.EMAIL_SENDER
                msg["To"]      = recipient
                msg.attach(MIMEText("\n".join(text_lines), "plain"))
                msg.attach(MIMEText(html_body, "html"))
                server.sendmail(config.EMAIL_SENDER, recipient, msg.as_string())

        logger.info("Digest sent (%s): %d items → %s", label, len(batch),
                    ", ".join(config.EMAIL_RECIPIENTS))
