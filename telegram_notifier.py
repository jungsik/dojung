# -*- coding: utf-8 -*-
"""텔레그램 발송. 4096자 제한 자동 분할 + 1회 재시도."""
import time

import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_TIMEOUT_SEC

MAX_LEN = 3900  # 텔레그램 상한 4096보다 여유를 둔다


class TelegramNotifier:
    def __init__(self, token=None, chat_id=None, timeout_sec=None):
        self.token = token if token is not None else TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id if chat_id is not None else TELEGRAM_CHAT_ID
        self.timeout_sec = float(timeout_sec if timeout_sec is not None else TELEGRAM_TIMEOUT_SEC)

    @property
    def enabled(self):
        return bool(str(self.token).strip() and str(self.chat_id).strip())

    def _split(self, message):
        """줄 단위로 잘라 MAX_LEN 이하 조각들로 나눈다."""
        if len(message) <= MAX_LEN:
            return [message]
        chunks, current = [], ""
        for line in message.split("\n"):
            if len(current) + len(line) + 1 > MAX_LEN:
                chunks.append(current.rstrip())
                current = ""
            current += line + "\n"
        if current.strip():
            chunks.append(current.rstrip())
        return chunks

    def _post(self, text):
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": text, "disable_web_page_preview": True}
        for attempt in (1, 2):  # 한국->텔레그램 경로는 가끔 SSL 핸드셰이크가 느리다
            try:
                response = requests.post(url, data=payload, timeout=self.timeout_sec)
                if 200 <= response.status_code < 300:
                    return True
                print(f"[TELEGRAM] HTTP {response.status_code}: {response.text[:120]}")
            except Exception as exc:
                print(f"[TELEGRAM] send failed (try {attempt}): {type(exc).__name__}")
            if attempt == 1:
                time.sleep(2)
        return False

    def send(self, message):
        if not self.enabled:
            return False
        ok = True
        for chunk in self._split(str(message)):
            if not self._post(chunk):
                ok = False
            time.sleep(0.4)
        return ok
