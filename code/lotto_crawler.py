import pymysql
import requests
from bs4 import BeautifulSoup
import time
import re

# 1. DB 연결 설정
DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "admin",
    "password": "chaerin",
    "database": "lottery_app",
    "charset": "utf8mb4",
    "autocommit": True
}

# 2. User-Agent 설정
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

# 3. 네이버 날짜 형식 (2026.01.03.) → YYYY-MM-DD 변환
def convert_draw_date_naver(date_str):
    match = re.search(r"(\d{4})\.(\d{2})\.(\d{2})", date_str)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return None

# ✅ DB에서 현재 최대 회차 확인
def get_max_round():
    connection = pymysql.connect(**DB_CONFIG)
    cursor = connection.cursor()
    cursor.execute("SELECT MAX(round) FROM lotto")
    result = cursor.fetchone()
    connection.close()
    return result[0] if result[0] else 0

# ✅ 네이버 사이트에서 최신 회차 확인
def get_latest_round():
    url = "https://search.naver.com/search.naver?query=로또"
    response = requests.get(url, headers=HEADERS, timeout=10)
    soup = BeautifulSoup(response.text, "html.parser")
    
    # 제공해주신 a._select_trigger 클래스 활용
    target = soup.select_one("a._select_trigger")
    if target:
        text = target.text.strip()
        round_match = re.search(r"(\d+)회차", text)
        if round_match:
            return int(round_match.group(1))
    return 0

# ✅ 지정 회차 네이버 크롤링 → 당첨번호 + 보너스 추출
def crawl_round_naver(round_num):
    url = f"https://search.naver.com/search.naver?query=로또+{round_num}회"
    response = requests.get(url, headers=HEADERS, timeout=10)
    soup = BeautifulSoup(response.text, "html.parser")

    # 1. 회차 및 날짜 정보 추출
    target = soup.select_one("a._select_trigger")
    if not target or str(round_num) not in target.text:
        print(f"[경고] {round_num}회차 정보를 찾을 수 없습니다.")
        return None
    
    draw_date = convert_draw_date_naver(target.text)

    # 2. 당첨번호 추출 (.winning_number 내의 .ball들)
    num_tags = soup.select(".winning_number .ball")
    if not num_tags or len(num_tags) < 6:
        print(f"❌ {round_num}회 당첨번호 태그를 찾지 못했습니다.")
        return None
    numbers = [int(n.text.strip()) for n in num_tags[:6]]

    # 3. 보너스 번호 추출 (.bonus_number 내의 .ball)
    bonus_tag = soup.select_one(".bonus_number .ball")
    if bonus_tag is None:
        print(f"❌ {round_num}회 보너스 번호를 찾지 못했습니다.")
        return None
    bonus_num = int(bonus_tag.text.strip())

    return {
        "round": round_num,
        "draw_date": draw_date,
        "numbers": numbers,
        "bonus": bonus_num
    }

# ✅ DB에 insert
def insert_lotto_data(data):
    connection = pymysql.connect(**DB_CONFIG)
    try:
        cursor = connection.cursor()
        sql = """
        INSERT INTO lotto (round, draw_date, num1, num2, num3, num4, num5, num6, bonus)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        values = (
            data["round"],
            data["draw_date"],
            data["numbers"][0],
            data["numbers"][1],
            data["numbers"][2],
            data["numbers"][3],
            data["numbers"][4],
            data["numbers"][5],
            data["bonus"]
        )
        cursor.execute(sql, values)
    finally:
        connection.close()

# ✅ 전체 실행 흐름
def main():
    print("🚀 로또 당첨번호 업데이트 시작 (대상: 네이버)")

    # 1. DB와 사이트의 회차 비교
    try:
        db_max_round = get_max_round()
    except Exception as e:
        print(f"❌ DB 접속 오류: {e}")
        return

    latest_round = get_latest_round()

    print(f"📊 현황 분석 - DB 최대: {db_max_round}회 / 네이버 최신: {latest_round}회")

    if db_max_round >= latest_round:
        print("✅ 이미 모든 데이터가 최신 상태입니다.")
        return

    # 2. 부족한 회차만큼 반복해서 크롤링 및 저장
    for r in range(db_max_round + 1, latest_round + 1):
        print(f"🔎 {r}회 수집 중...")
        try:
            data = crawl_round_naver(r)
            if data:
                insert_lotto_data(data)
                print(f"   ∟ ✅ {r}회 DB 저장 완료: {data['numbers']} + {data['bonus']}")
                time.sleep(2)  # 네이버 차단 방지용 딜레이
        except Exception as e:
            print(f"   ∟ ❌ {r}회 처리 중 에러: {e}")

    print("🏁 업데이트 프로세스 완료")

if __name__ == "__main__":
    main()