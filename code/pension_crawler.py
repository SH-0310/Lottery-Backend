import time
import re
import pymysql
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service # 상단에 추가

# --- 1. DB 설정 (오라클 서버 주소)
DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "admin",
    "password": "chaerin",
    "database": "lottery_app",
    "charset": "utf8mb4",
    "autocommit": True
}

def get_max_round():
    print("🔍 DB에서 현재 최대 회차 조회 중...")
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(round) FROM pension")
    result = cursor.fetchone()
    conn.close()
    res = result[0] if result[0] else 0
    print(f"✅ 현재 DB 최대 회차: {res}")
    return res

def get_latest_pension_round(driver):
    url = "https://search.naver.com/search.naver?query=연금복권"
    driver.get(url)
    wait = WebDriverWait(driver, 10)
    target = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "a._select_trigger")))
    text = target.text.strip()
    match = re.search(r"(\d+)회차", text)
    return int(match.group(1)) if match else 0

def crawl_round(driver, round_num):
    print(f"➡️ {round_num}회 크롤링 시작")
    url = f"https://search.naver.com/search.naver?query=연금복권+{round_num}회"
    driver.get(url)
    time.sleep(2)

    soup = BeautifulSoup(driver.page_source, "html.parser")

    # 1. 회차 및 날짜 정보
    header_tag = soup.select_one("a._select_trigger")
    if not header_tag or str(round_num) not in header_tag.text:
        print(f"[경고] {round_num}회차 정보를 찾을 수 없습니다.")
        return None

    date_match = re.search(r"(\d{4})\.(\d{2})\.(\d{2})", header_tag.text)
    draw_date = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}" if date_match else None
    print(f"📅 추첨일: {draw_date}")

    # 2. 당첨번호 추출 (1등: 조 + 6자리)
    win_balls = soup.select(".winning_number .ball")
    if len(win_balls) < 7:
        print(f"❌ {round_num}회 당첨번호 태그 부족")
        return None

    jo_number = win_balls[0].text.strip()
    number_part = "".join([b.text.strip() for b in win_balls[1:7]])
    first_prize = f"{jo_number}조{number_part}"

    # 3. ✅ [수정] 보너스 번호 추출 로직
    # "보너스" 텍스트를 포함한 td를 먼저 찾고, 그 부모 행(tr)에서 숫자들을 가져옵니다.
    bonus = "000000"
    bonus_row = soup.find("td", string=re.compile("보너스"))
    if bonus_row:
        parent_tr = bonus_row.find_parent("tr")
        bonus_digits = parent_tr.select("td.type_bold")
        if bonus_digits:
            bonus = "".join([d.text.strip() for d in bonus_digits])
    
    print(f"💎 1등: {first_prize} / 🌟 보너스: {bonus}")

    return {
        "round": round_num,
        "draw_date": draw_date,
        "first_prize": first_prize,
        "second_prize": number_part,
        "bonus": bonus,
        "third_prize": number_part[-5:],
        "fourth_prize": number_part[-4:],
        "fifth_prize": number_part[-3:],
        "sixth_prize": number_part[-2:],
        "seventh_prize": number_part[-1:],
    }

def insert_data(data):
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()
    sql = """
    INSERT INTO pension (round, draw_date, first_prize, second_prize, bonus, third_prize, fourth_prize,
                         fifth_prize, sixth_prize, seventh_prize)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    cursor.execute(sql, (
        data["round"], data["draw_date"], data["first_prize"], data["second_prize"], data["bonus"],
        data["third_prize"], data["fourth_prize"], data["fifth_prize"], data["sixth_prize"], data["seventh_prize"]
    ))
    conn.close()
    print(f"✅ {data['round']}회 DB 저장 완료")

def main():
    print("🎉 [Naver] 연금복권 업데이트 프로세스 시작")
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    options.binary_location = "/usr/bin/chromium-browser"
    
    # 2. ChromeDriver 서비스 경로 설정
    service = Service(executable_path="/usr/bin/chromedriver")

    # 3. 드라이버 실행
    driver = webdriver.Chrome(service=service, options=options)


    try:
        db_max = get_max_round()
        latest = get_latest_pension_round(driver)
        print(f"📊 비교 결과: DB {db_max}회 vs 네이버 {latest}회")

        if db_max >= latest:
            print("✨ 이미 모든 데이터가 최신입니다.")
        else:
            for r in range(db_max + 1, latest + 1):
                data = crawl_round(driver, r)
                if data:
                    insert_data(data)
                    time.sleep(2)
    finally:
        driver.quit()
        print("🎯 연금복권 업데이트 종료")

if __name__ == "__main__":
    main()