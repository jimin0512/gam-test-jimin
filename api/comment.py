# -*- coding: utf-8 -*-
"""Gemini 촌평 — Vercel 서버리스 함수.

이 앱에서 서버가 필요한 유일한 자리다. **키를 숨기기 위해서** 존재한다.
키를 app.js 에 적으면 브라우저에서 그대로 보인다.

  받는 것   {"score": 62, "grade": 70,
             "directions": ["correct", "high", "wrong", "high", "wrong"],
             "topic": "cities"}
  주는 것   {"comment": "...", "nickname": "..."}

**숫자를 보내지 않는다.** 방향만 보낸다 — 숫자를 주면 그 숫자로 새 숫자를
만들어낸다. 점수·등급·오차는 전부 브라우저가 이미 계산했다.

**body 는 ASCII 만 담는다.** grade 는 등급 컷오프 숫자, topic 은 topic id,
directions 는 영어 코드다 — 한글이 섞이면 Vercel 의 Python 런타임에서
body 를 읽는 단계 자체가 UnicodeDecodeError 로 깨지는 문제가 있었다.
한국어 문맥은 아래 TOPIC_NAMES/GRADE_NAMES/DIRECTION_KO 로 이 파일
안에서만 복원한다 — 전부 topics.json/화면에 이미 공개된 제목·등급 이름일
뿐, 정답이나 원본 데이터가 아니다.

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

# ?probe=test 로 실제 generateContent 성공 여부를 확인할 후보 —
# models.list 로 이 키에서 존재/generateContent 지원을 이미 확인한 것만 둔다.
# 임시 진단용, 원인 확인 후 지운다.
PROBE_CANDIDATES = ["gemini-3.5-flash", "gemini-3.5-flash-lite"]

# topics.json 에 이미 공개된 제목/등급 이름 — 정답/원본 데이터 아님.
TOPIC_NAMES = {
    "seoul-heat": "서울은 얼마나 더워졌나",
    "seoul-rain": "비는 언제, 얼마나",
    "seoul-air": "미세먼지, 언제 나쁜가",
    "working-hours": "우리는 얼마나 일하나",
    "population": "인구와 출산",
    "internet": "인터넷과 연결",
    "usdkrw": "원달러 환율 26년",
    "cities": "서울·도쿄·런던·싱가포르",
    "quakes": "지진은 얼마나 자주",
    "life": "얼마나 오래 사나",
}
GRADE_NAMES = {90: "촉이 데이터급", 70: "감이 좋은 편", 50: "보통의 감각",
               30: "느낌대로 삽니다", 0: "감은 접어두시죠"}
DIRECTION_KO = {"correct": "맞힘", "wrong": "틀림", "high": "높게",
                "low": "낮게", "same": "비슷"}

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


def _ask(score, grade_min, directions, topic_id=""):
    """(comment, nickname, code) 를 돌려준다. code 는 "ok" 아니면 실패 종류
    (키 값·Gemini 응답 원문은 절대 담지 않는다 — print() 로만, 최소한으로,
    Vercel Function Logs 에만 남긴다).

    입력은 전부 ASCII(등급 컷오프 숫자 / topic id / 영어 방향 코드)로 받고,
    Gemini 프롬프트에 쓸 한국어 문맥은 여기서 TOPIC_NAMES/GRADE_NAMES/
    DIRECTION_KO 로 복원한다.
    """
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None, None, "no_key"

    topic = TOPIC_NAMES.get(topic_id, "이번")
    grade = GRADE_NAMES.get(grade_min, "")
    directions_ko = [DIRECTION_KO.get(d, d) for d in directions]

    body = {
        "contents": [{
            "parts": [{
                "text": PROMPT.format(topic=topic, score=score, grade=grade,
                                      directions=", ".join(directions_ko))
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

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        print(f"[comment] Gemini HTTPError {e.code}")
        return None, None, f"http_{e.code}"
    except urllib.error.URLError as e:
        print(f"[comment] Gemini URLError: {type(e).__name__}")
        return None, None, "url_error"
    except Exception as e:
        print(f"[comment] Gemini 호출 실패: {type(e).__name__}")
        return None, None, "unknown_error"

    try:
        out = json.loads(raw)
        text = out["candidates"][0]["content"]["parts"][0]["text"]
        got = json.loads(text)
    except Exception as e:
        print(f"[comment] Gemini 응답 처리 실패: {type(e).__name__}")
        return None, None, "response_parse_error"

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
        # app.js 는 ASCII payload 만 보낸다 — score(숫자), grade(등급 컷오프
        # 숫자), directions(영어 코드 배열), topic(topic id). 무엇이 실패하든
        # 앱을 멈추지 않는다: 사유는 print() 로만 남기고 {"comment": null}.
        try:
            n = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(n) or b"{}")
            score = int(req.get("score", 0))
            grade_min = int(req.get("grade", 0))
            directions = [str(x) for x in req.get("directions", [])][:10]
            topic_id = str(req.get("topic", ""))[:50]
        except Exception as e:
            print(f"[comment] do_POST 요청 파싱 실패: {type(e).__name__}")
            self._send({"comment": None})
            return

        try:
            comment, nickname, code = _ask(score, grade_min, directions, topic_id)
        except Exception as e:
            print(f"[comment] do_POST _ask 호출 실패: {type(e).__name__}")
            self._send({"comment": None})
            return

        if code == "ok":
            self._send({"comment": comment, "nickname": nickname})
        else:
            self._send({"comment": None})

    def do_GET(self):
        # ?probe=models / ?probe=test&model=... 는 실제 사용 가능한 모델을
        # 확인하기 위한 임시 조회용이다. 원인 확인 후 지운다.
        # 키 값은 절대 응답에 담지 않는다 — 모델 이름/성공 여부만 돌려준다.
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        probe = (qs.get("probe") or [""])[0]
        key = os.environ.get("GEMINI_API_KEY")

        if probe == "models":
            if not key:
                self._send({"ok": False, "probe_error": "no_key"})
                return
            try:
                req = urllib.request.Request(
                    "https://generativelanguage.googleapis.com/v1beta/models",
                    headers={"x-goog-api-key": key})
                with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                    data = json.loads(r.read().decode("utf-8"))
                models = [
                    {"name": m.get("name"),
                     "methods": m.get("supportedGenerationMethods", [])}
                    for m in data.get("models", [])
                    if "generateContent" in m.get("supportedGenerationMethods", [])
                ]
                self._send({"ok": True, "models": models})
            except urllib.error.HTTPError as e:
                self._send({"ok": False, "probe_error": f"http_{e.code}"})
            except Exception as e:
                self._send({"ok": False, "probe_error": type(e).__name__})
            return

        if probe == "test":
            if not key:
                self._send({"ok": False, "probe_error": "no_key"})
                return
            # 쿼리로 임의 모델명을 받지 않는다 — models.list 로 실제 존재를
            # 확인한 후보만 코드에 고정해 시험한다.
            results = []
            for model in PROBE_CANDIDATES:
                try:
                    body = {"contents": [{"parts": [{"text": "Reply only with OK"}]}]}
                    req = urllib.request.Request(
                        ENDPOINT.format(model=model),
                        data=json.dumps(body).encode("utf-8"),
                        headers={"Content-Type": "application/json",
                                 "x-goog-api-key": key},
                        method="POST")
                    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                        out = json.loads(r.read().decode("utf-8"))
                    text = out["candidates"][0]["content"]["parts"][0]["text"]
                    results.append({"model": model, "ok": True,
                                    "sample": text[:50]})
                except urllib.error.HTTPError as e:
                    results.append({"model": model, "ok": False,
                                    "probe_error": f"http_{e.code}"})
                except Exception as e:
                    results.append({"model": model, "ok": False,
                                    "probe_error": type(e).__name__})
            self._send({"ok": True, "results": results})
            return

        self._send({"ok": True, "key": bool(key)})
