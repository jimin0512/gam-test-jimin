# -*- coding: utf-8 -*-
"""Gemini 촌평 — Vercel 서버리스 함수.

이 앱에서 서버가 필요한 유일한 자리다. **키를 숨기기 위해서** 존재한다.
키를 app.js 에 적으면 브라우저에서 그대로 보인다.

  받는 것   {"score": 62, "grade": "수습 딱지 뗌",
             "directions": ["맞힘", "높게", "틀림", "높게", "틀림"]}
  주는 것   {"comment": "...", "nickname": "..."}

**숫자를 보내지 않는다.** 방향만 보낸다 — 숫자를 주면 그 숫자로 새 숫자를
만들어낸다. 점수·등급·오차는 전부 브라우저가 이미 계산했다.

키가 없거나 호출이 실패하면 {"comment": null} 을 200 으로 돌려준다.
**앱은 촌평 없이도 그대로 돈다.**

외부 라이브러리를 쓰지 않는다 (requirements.txt 가 필요 없다).
"""
import json
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler

# AI Studio(aistudio.google.com)에서 지금 쓸 수 있는 모델 이름으로 맞춘다.
# 모델 이름과 무료 한도는 자주 바뀐다 — 교안의 이름을 그대로 믿지 말 것.
MODEL = "gemini-2.5-flash"
ENDPOINT = ("https://generativelanguage.googleapis.com/v1beta/"
            "models/{model}:generateContent")
TIMEOUT = 6

PROMPT = """너는 직장 데이터 퀴즈 앱의 촌평 담당이다.

사용자가 방금 '{topic}' 주제의 감 테스트를 풀었다. 결과는 이렇다.

  점수: {score}점 ({grade})
  문항별로 어느 방향으로 빗나갔는지: {directions}

  '높게' = 실제보다 크게 잡음, '낮게' = 실제보다 작게 잡음,
  '비슷' = 거의 맞음, '맞힘'/'틀림' = 객관식

규칙
- 두 문장 이내로 짧게. 존댓말.
- **숫자를 새로 만들지 마라.** 위에 없는 수치를 쓰면 안 된다.
- 어느 방향으로 치우쳤는지를 짚고, 회사 생활에 빗대 가볍게 말한다.
- 비꼬거나 훈계하지 않는다. 읽고 웃을 수 있게.
- 마지막 줄에 별명을 하나 붙인다. 6글자 이내.

형식(JSON 만 출력):
{{"comment": "두 문장", "nickname": "별명"}}"""


def _ask(score, grade, directions, topic=""):
    """(comment, nickname, code) 를 돌려준다.

    code 는 "ok" 아니면 아래 중 하나 — 원인 확인용 임시 진단 코드다.
    상태코드 숫자 말고는 아무것도 담지 않는다: 키 값도, Gemini 응답 원문도,
    prompt 도 나가지 않는다. 원인이 확인되면 이 코드는 지운다.
      no_key / http_<상태코드> / timeout / url_error /
      response_parse_error / empty_response / comment_parse_error /
      unknown_error
    """
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None, None, "no_key"

    body = {
        "contents": [{
            "parts": [{
                "text": PROMPT.format(topic=topic or "이번", score=score,
                                      grade=grade,
                                      directions=", ".join(directions))
            }]
        }],
        "generationConfig": {
            "temperature": 1.0,
            "maxOutputTokens": 200,
            "responseMimeType": "application/json",
        },
    }
    req = urllib.request.Request(
        ENDPOINT.format(model=MODEL),
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        method="POST")

    # 실패 지점을 구분한다 — 키 값과 에러 본문은 print() 로만 남기고
    # (Vercel Function Logs 전용) 응답에는 상태코드 수준의 code 만 태운다.
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        body_snip = e.read().decode("utf-8", "ignore")[:300]
        print(f"[comment] Gemini HTTPError {e.code}: {body_snip}")
        return None, None, f"http_{e.code}"
    except TimeoutError as e:
        print(f"[comment] Gemini 타임아웃: {e}")
        return None, None, "timeout"
    except urllib.error.URLError as e:
        print(f"[comment] Gemini URLError: {e}")
        return None, None, "url_error"
    except Exception as e:
        print(f"[comment] Gemini 호출 실패: {type(e).__name__}: {e}")
        return None, None, "unknown_error"

    try:
        out = json.loads(raw)
    except Exception as e:
        print(f"[comment] Gemini 응답 JSON 파싱 실패: {type(e).__name__}: {e}")
        return None, None, "response_parse_error"

    try:
        text = out["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        print(f"[comment] Gemini 응답에 candidates/text 없음: {type(e).__name__}: {e}")
        return None, None, "empty_response"

    try:
        got = json.loads(text)
    except Exception as e:
        print(f"[comment] comment JSON 파싱 실패: {type(e).__name__}: {e}")
        return None, None, "comment_parse_error"

    comment = str(got.get("comment", ""))[:300]
    nickname = str(got.get("nickname", ""))[:20]
    return comment, nickname, "ok"


class handler(BaseHTTPRequestHandler):
    def _send(self, payload, code=200):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        # 1) 요청 파싱 단계 — _ask() 를 부르기도 전에 실패하면 post_parse_error
        try:
            n = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(n) or b"{}")
            score = int(req.get("score", 0))
            grade = str(req.get("grade", ""))
            directions = [str(x) for x in req.get("directions", [])][:10]
            topic = str(req.get("topic", ""))[:50]
        except Exception as e:
            print(f"[comment] do_POST 요청 파싱 실패: {type(e).__name__}: {e}")
            self._send({"comment": None, "debug": "post_parse_error"})
            return

        # 2) Gemini 호출 단계 — _ask() 가 이미 원인을 code 로 분류해 돌려준다
        try:
            comment, nickname, code = _ask(score, grade, directions, topic)
        except Exception as e:
            print(f"[comment] do_POST _ask 호출 실패: {type(e).__name__}: {e}")
            self._send({"comment": None, "debug": "unknown_error"})
            return

        if code == "ok":
            self._send({"comment": comment, "nickname": nickname})
        else:
            # 임시 진단용 — 원인 확인 후 이 debug 필드는 제거한다
            self._send({"comment": None, "debug": code})

    def do_GET(self):
        self._send({"ok": True, "key": bool(os.environ.get("GEMINI_API_KEY"))})
