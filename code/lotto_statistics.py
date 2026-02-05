import re
import time
import shutil
import traceback
import pymysql
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException, ElementClickInterceptedException

# --- 1. DB 설정 (성공했던 오라클 서버 주소 적용)
DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "admin",
    "password": "chaerin",
    "database": "lottery_app",
    "charset": "utf8mb4",
    "autocommit": True,
}

URL = "https://www.dhlottery.co.kr/lt645/stats"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

def _to_int_safe(text: str):
    # "165회" -> 165 변환
    s = re.sub(r"[^\d]", "", text or "")
    return int(s) if s else 0

def ensure_table():
    conn = pymysql.connect(**DB_CONFIG)
    cur = conn.cursor()
    sql = """
    CREATE TABLE IF NOT EXISTS lotto_number_stats (
      number TINYINT NOT NULL,           -- 1~45
      include_bonus TINYINT(1) NOT NULL, -- 1=포함, 0=미포함
      win_count INT NOT NULL,
      updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP 
        ON UPDATE CURRENT_TIMESTAMP,
      PRIMARY KEY (number, include_bonus)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """
    cur.execute(sql)
    conn.close()

def insert_stats_bulk(stats_map: dict, include_bonus: int):
    if not stats_map: return
    conn = pymysql.connect(**DB_CONFIG)
    cur = conn.cursor()
    sql = """
      INSERT INTO lotto_number_stats (number, include_bonus, win_count)
      VALUES (%s, %s, %s)
      ON DUPLICATE KEY UPDATE 
        win_count = VALUES(win_count),
        updated_at = CURRENT_TIMESTAMP
    """
    rows = [(num, include_bonus, cnt) for num, cnt in sorted(stats_map.items())]
    cur.executemany(sql, rows)
    conn.close()
    print(f"✅ DB 저장 완료: {len(rows)}개 항목 (보너스 포함 여부: {include_bonus})")

# ✅ [수정] 새로운 div 그리드 구조 파싱 함수
def parse_grid_data(html_text: str) -> dict:
    soup = BeautifulSoup(html_text, "html.parser")
    # 주신 HTML 구조: result-ballBox 안에 번호(result-ball)와 횟수(result-txt)가 있음
    items = soup.select(".result-ballBox")
    result = {}
    for item in items:
        ball = item.select_one(".result-ball")
        count_txt = item.select_one(".result-txt")
        if ball and count_txt:
            num = _to_int_safe(ball.text)
            count = _to_int_safe(count_txt.text)
            if num > 0:
                result[num] = count
    return result

# --- Selenium 설정부
def find_chrome_binary():
    for cand in ["google-chrome", "chromium-browser", "chromium", "chrome.exe"]:
        p = shutil.which(cand)
        if p: return p
    return None

def setup_driver():
    options = Options()
    options.add_argument(f"--user-agent={HEADERS['User-Agent']}")
    options.add_argument("--headless=new") # 화면 없이 실행
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    
    chrome_bin = find_chrome_binary()
    if chrome_bin: options.binary_location = chrome_bin
    
    try:
        return webdriver.Chrome(options=options)
    except Exception as e:
        raise RuntimeError(f"드라이버 구동 실패: {e}")

# --- 메인 크롤링 로직
def crawl_statistics():
    driver = setup_driver()
    wait = WebDriverWait(driver, 20)
    
    try:
        print(f"🌐 사이트 접속 중: {URL}")
        driver.get(URL)
        
        # 1. '당첨번호 통계' 탭 클릭 (id="li-2")
        print("👆 '당첨번호 통계' 탭 클릭")
        tab_btn = wait.until(EC.element_to_be_clickable((By.ID, "li-2")))
        driver.execute_script("arguments[0].click();", tab_btn)
        time.sleep(1) # 탭 전환 애니메이션 대기

        # --- A. 보너스 미포함 (include_bonus = 0) 수집
        print("📊 보너스 미포함 데이터 수집 중...")
        # 결과 테이블(noDiv)이 나타날 때까지 대기
        wait.until(EC.presence_of_element_located((By.ID, "noDiv")))
        stats_exc = parse_grid_data(driver.page_source)
        if stats_exc:
            insert_stats_bulk(stats_exc, include_bonus=0)
        
        # --- B. 보너스 포함 (include_bonus = 1) 설정 및 수집
        print("🔘 '보너스 포함 여부' 체크 중...")
        checkbox = driver.find_element(By.ID, "srchBnsYn")
        if not checkbox.is_selected():
            # 체크박스 클릭이 가려질 수 있으므로 스크립트로 클릭
            driver.execute_script("arguments[0].click();", checkbox)
        
        print("🔍 조회 버튼 클릭")
        search_btn = driver.find_element(By.ID, "btnSrch")
        driver.execute_script("arguments[0].click();", search_btn)
        
        # 데이터가 갱신될 때까지 잠시 대기
        time.sleep(2)
        wait.until(EC.presence_of_element_located((By.ID, "noDiv")))
        
        print("📊 보너스 포함 데이터 수집 중...")
        stats_inc = parse_grid_data(driver.page_source)
        if stats_inc:
            insert_stats_bulk(stats_inc, include_bonus=1)

    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        traceback.print_exc()
    finally:
        driver.quit()

def main():
    print("🚀 로또 번호별 통계 업데이트 시작")
    ensure_table()
    crawl_statistics()
    print("🎯 모든 통계 데이터 갱신 완료")

if __name__ == "__main__":
    main()