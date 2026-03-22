"""Email notifier — sends digest at 09:00 and 20:00 daily."""

import logging
import smtplib
import threading
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import config
import ai_processor

logger = logging.getLogger(__name__)

# Send digest at these hours (local time)
SEND_HOURS = {9, 20}


class EmailNotifier:
    def __init__(self):
        self._queue: list[dict] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._sent_hours: set[int] = set()  # track which hours already sent today

    def start(self):
        if not config.EMAIL_SENDER or not config.EMAIL_APP_PASSWORD:
            logger.warning("Email not configured — notifier disabled")
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="email-notifier")
        self._thread.start()
        logger.info("Email notifier started — daily digest at %s → %s",
                    ", ".join(f"{h:02d}:00" for h in sorted(SEND_HOURS)),
                    config.EMAIL_RECIPIENT)

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def enqueue(self, item: dict, item_type: str = "post"):
        """Accumulate new items for the next digest."""
        with self._lock:
            self._queue.append({"item": item, "type": item_type})

    def _run(self):
        while not self._stop.is_set():
            now = datetime.now()
            hour = now.hour

            # Reset sent tracker at midnight
            if hour == 0:
                self._sent_hours.clear()

            # Check if it's a send hour and we haven't sent yet this hour
            if hour in SEND_HOURS and hour not in self._sent_hours:
                with self._lock:
                    batch = list(self._queue)
                    self._queue.clear()

                if batch:
                    try:
                        self._send(batch, label="Morning" if hour < 12 else "Evening")
                        self._sent_hours.add(hour)
                    except Exception as e:
                        logger.error("Failed to send email: %s", e)
                        # Re-queue items so they're not lost
                        with self._lock:
                            self._queue = batch + self._queue
                else:
                    logger.info("Digest time (%02d:00) — no new items, skipping", hour)
                    self._sent_hours.add(hour)

            # Sleep 60s between checks
            self._stop.wait(60)

    def _send(self, batch: list[dict], label: str = "Digest"):
        posts  = [b for b in batch if b["type"] == "post"]
        tweets = [b for b in batch if b["type"] == "tweet"]
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

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
        # Digest summary block
        if digest_summary:
            html_parts.append(f"""
  <div style='background:#fffbeb;border:1px solid #fcd34d;border-radius:8px;
              padding:16px 20px;margin-bottom:24px;'>
    <div style='font-size:12px;font-weight:600;color:#92400e;margin-bottom:8px;'>📋 今日 AI 资讯摘要</div>
    <p style='margin:0;font-size:14px;color:#333;line-height:1.7;'>{digest_summary}</p>
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
                html_parts.append(f"""
  <div style='margin-bottom:18px;padding:16px;border-left:4px solid #1d9bf0;
              background:#f0f8ff;border-radius:0 8px 8px 0;'>
    <div style='font-size:11px;color:#888;margin-bottom:6px;'>@{t['username']} · {date}</div>
    <p style='margin:0;font-size:14px;color:#222;line-height:1.6;'>{t['text']}</p>
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
                text_lines.append(f"[{p['source']}] {p['title']}\n{p['url']}\n")
            else:
                t = b["item"]
                text_lines.append(f"@{t['username']}: {t['text'][:140]}\n{t.get('url','')}\n")

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = config.EMAIL_SENDER
        msg["To"]      = config.EMAIL_RECIPIENT
        msg.attach(MIMEText("\n".join(text_lines), "plain"))
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(config.EMAIL_SENDER, config.EMAIL_APP_PASSWORD)
            server.sendmail(config.EMAIL_SENDER, config.EMAIL_RECIPIENT, msg.as_string())

        logger.info("Digest sent (%s): %d items → %s", label, len(batch), config.EMAIL_RECIPIENT)
