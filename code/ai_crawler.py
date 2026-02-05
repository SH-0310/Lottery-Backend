# ai_crawler.py
import os, json, time, random, requests, datetime, pymysql, re
from dotenv import load_dotenv  # 1. 라이브러리 불러오기

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

# ====== 환경설정 ======
# DB 연결은 환경변수로도 설정 가능 (없으면 기본값 사용)
DB = dict(
    host=os.getenv("DB_HOST", "127.0.0.1"),
    user=os.getenv("DB_USER", "admin"),
    password=os.getenv("DB_PASS", "chaerin"),
    database=os.getenv("DB_NAME", "lottery_app"),
    charset="utf8mb4",
    autocommit=True,
)

OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY    = os.getenv("GEMINI_API_KEY")
DEEPINFRA_API_KEY = os.getenv("DEEPINFRA_API_KEY")


# 주 1회 저장 키 (KST 기준 주차)
KST = datetime.timezone(datetime.timedelta(hours=9))
def week_key_kst():
    now = datetime.datetime.now(KST)
    return f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"

# 공통 프롬프트
SYSTEM = (
    "너는 한국의 로또 6/45 번호 추천 도우미다. "
    "네가 추천하는 번호는 단순 랜덤이 아니라, "
    "합리적인 근거와 추론 과정을 바탕으로 선택해야 한다. "
    "항상 JSON으로 출력하고, numbers(1~45 정수 6개, 오름차순, 중복X)와 "
    "reasoning(근거 3~6문장)을 반드시 포함해라."
)

USER = "다음주 토요일 추첨 예정인 로또의 예상 번호를 추천해줘. JSON만 출력해."

# ====== 제공자 정의 (총 4개) ======
# OpenAI, Gemini(REST), DeepInfra 2종(모두 OpenAI 호환)
PROVIDERS = [
    # 1) OpenAI
    {
        "name": "gpt-4o-mini",
        "agency": "OpenAI",
        "type": "openai_compatible",
        "url": "https://api.openai.com/v1/chat/completions",
        "key": OPENAI_API_KEY,
        "model": "gpt-4o-mini",
        "supports_json_response_format": True,
    },
    {
        "name": "gemini-2.5-flash-lite", # 이름 변경
        "agency": "Google",
        "type": "gemini_rest",
        # URL 내 모델명을 gemini-2.5-flash-lite로 교체
        "url": "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent",
        "key": GEMINI_API_KEY,
        "model": "gemini-2.5-flash-lite", # 모델 코드 변경
    },
    # 3) DeepInfra (Llama 3.1 8B Turbo)
    {
        "name": "llama-3.1-8b-turbo",
        "agency": "Meta",
        "type": "openai_compatible",
        "url": "https://api.deepinfra.com/v1/openai/chat/completions",
        "key": DEEPINFRA_API_KEY,
        "model": "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
        "supports_json_response_format": True,
    },
    # 4) DeepInfra (DeepSeek R1 Distill Llama 70B)
    {
        "name": "deepseek-v3.1",
        "agency": "DeepSeek",
        "type": "openai_compatible",
        "url": "https://api.deepinfra.com/v1/openai/chat/completions",
        "key": DEEPINFRA_API_KEY,
        "model": "deepseek-ai/DeepSeek-V3.1",
        "supports_json_response_format": True,  # ✅ V3.1은 JSON 강제 권장
    },
]

# ====== 공통 유틸 ======
def sanitize_numbers(obj):
    nums = obj.get("numbers", [])
    try:
        nums = [int(n) for n in nums]
    except Exception:
        nums = []

    # reasoning을 반드시 문자열로 보장
    reason = obj.get("reasoning", "")
    if isinstance(reason, list):
        reason = " ".join(str(x).strip() for x in reason)
    elif not isinstance(reason, str):
        reason = str(reason)
    reason = re.sub(r"\s+", " ", reason).strip()

    # ✅ 보정 없이 그대로 반환
    return nums, reason

def save_db(week_key, provider, agency, numbers, reasoning, raw):
    conn = pymysql.connect(**DB)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO ai_recommendations(week_key, provider, agency, numbers_json, reasoning, raw_response)
        VALUES(%s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
          numbers_json = VALUES(numbers_json),
          reasoning    = VALUES(reasoning),
          raw_response = VALUES(raw_response),
          agency       = VALUES(agency)
        """,
        (week_key, provider, agency, json.dumps(numbers, ensure_ascii=False), reasoning, json.dumps(raw, ensure_ascii=False)),
    )
    conn.close()

# ====== 호출 함수들 ======
def ask_openai_compatible(p, retries=2):
    """OpenAI 호환(chat.completions) 엔드포인트용"""
    if not p.get("key"):
        raise RuntimeError(f"{p['name']}: API 키가 설정되지 않았습니다.")

    headers = {"Authorization": f"Bearer {p['key']}", "Content-Type": "application/json"}
    payload = {
        "model": p["model"],
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user",   "content": USER},
        ],
        "max_tokens": 280,
        "temperature": 0.7,
    }
    if p.get("supports_json_response_format"):
        payload["response_format"] = {"type": "json_object"}

    last_err = None
    for attempt in range(retries + 1):
        try:
            r = requests.post(p["url"], headers=headers, json=payload, timeout=45)
            if r.status_code != 200:
                print(f"[{p['name']}] HTTP {r.status_code}: {r.text[:400]}")
                last_err = RuntimeError(f"http {r.status_code}")
                # 첫 시도 실패 시 response_format 제거 재시도(미지원인 모델 대비)
                if attempt == 0 and payload.get("response_format"):
                    payload.pop("response_format", None)
                time.sleep(1 + attempt)
                continue

            data = r.json()
            choices = data.get("choices")
            if not choices:
                print(f"[{p['name']}] Unexpected body (no choices): {json.dumps(data)[:400]}")
                last_err = RuntimeError("no choices in response")
                time.sleep(1 + attempt)
                continue

            content = choices[0]["message"]["content"]
            text = strip_code_fences(content)
            try:
                j = json.loads(text)
            except Exception:
                m = re.search(r"\{.*\}", text, flags=re.DOTALL)
                if m:
                    try:
                        j = json.loads(m.group(0))
                    except Exception:
                        j = {"numbers": [], "reasoning": text}
                else:
                    j = {"numbers": [], "reasoning": text}
            j = normalize_payload(j)
            return j, data


        except Exception as e:
            print(f"[{p['name']}] exception: {e}")
            last_err = e
            time.sleep(1 + attempt)

    raise last_err or RuntimeError("ask_openai_compatible failed")

def ask_gemini_rest(p, retries=2):
    if not p.get("key"):
        raise RuntimeError(f"{p['name']}: API 키가 설정되지 않았습니다.")

    url = f"{p['url']}?key={p['key']}"
    body = {
        "contents": [{"parts": [{"text": f"{SYSTEM}\n\n{USER}"}]}],
        "generationConfig": {
            "maxOutputTokens": 280,
            "temperature": 0.7,
            # 👇 JSON만 받기
            "response_mime_type": "application/json"
        }
    }

    last_err = None
    for attempt in range(retries + 1):
        try:
            r = requests.post(url, headers={"Content-Type": "application/json"}, json=body, timeout=45)
            if r.status_code != 200:
                print(f"[{p['name']}] HTTP {r.status_code}: {r.text[:400]}")
                last_err = RuntimeError(f"http {r.status_code}")
                # 503/과부하 등 일시 에러에는 지수 백오프
                time.sleep(1.5 ** attempt)
                continue

            data = r.json()
            candidates = data.get("candidates") or []
            if not candidates:
                print(f"[{p['name']}] Unexpected body (no candidates): {json.dumps(data)[:400]}")
                last_err = RuntimeError("no candidates")
                time.sleep(1.5 ** attempt)
                continue

            parts = candidates[0].get("content", {}).get("parts", [])
            text = "".join(pt.get("text","") for pt in parts if isinstance(pt, dict)).strip()
            # response_mime_type 덕분에 여기 text는 JSON 문자열일 확률이 매우 높음
            try:
                j = json.loads(strip_code_fences(text))
            except Exception:
                j = {"numbers": [], "reasoning": text}

            j = normalize_payload(j)
            return j, data

        except Exception as e:
            print(f"[{p['name']}] exception: {e}")
            last_err = e
            time.sleep(1.5 ** attempt)

    raise last_err or RuntimeError("ask_gemini_rest failed")

def ask_provider(p):
    if p["type"] == "openai_compatible":
        return ask_openai_compatible(p)
    elif p["type"] == "gemini_rest":
        return ask_gemini_rest(p)
    else:
        raise RuntimeError(f"Unknown provider type: {p['type']}")

# ====== 메인 루틴 ======
def fetch_all_providers():
    wk = week_key_kst()
    for p in PROVIDERS:
        try:
            j, raw = ask_provider(p)
            nums, reason = sanitize_numbers(j)
            save_db(wk, p["name"], p.get("agency","unknown"), nums, reason, raw)
            print(f"[OK] {p['name']} -> {wk} / {nums}")
        except Exception as e:
            # 완전 실패 시에도 빈 레코드라도 남기고 싶다면 여기서 처리
            print(f"[FAIL] {p['name']}: {e}")

def strip_code_fences(text: str) -> str:
    if not isinstance(text, str):
        return text
    t = text.strip()
    # ```json ... ``` 또는 ``` ... ```
    if t.startswith("```"):
        # 앞뒤 펜스 제거
        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()

def normalize_payload(j: dict) -> dict:
    """reasoning을 항상 str로, numbers는 list[int]로 정규화"""
    if not isinstance(j, dict):
        return {"numbers": [], "reasoning": str(j)}

    # reasoning
    r = j.get("reasoning", "")
    if isinstance(r, list):
        r = " ".join([str(x).strip() for x in r if isinstance(x, (str,int,float))]).strip()
    elif not isinstance(r, str):
        r = str(r).strip()
    j["reasoning"] = r

    # numbers
    nums = j.get("numbers", [])
    if not isinstance(nums, list):
        nums = []
    cleaned = []
    for n in nums:
        try:
            cleaned.append(int(str(n).strip()))
        except Exception:
            pass
    j["numbers"] = cleaned
    return j


if __name__ == "__main__":
    fetch_all_providers()
