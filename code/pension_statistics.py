import time
import re
import pymysql
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- 1. DB 설정 (오라클 서버 주소 반영)
DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "admin",
    "password": "chaerin",
    "database": "lottery_app",
    "charset": "utf8mb4",
    "autocommit": True,
}

URL = "https://www.dhlottery.co.kr/pt720/stats"

# ---- 자리수 매핑: HTML ID -> DB Position ----
ID_TO_POSITION = {
    "wnBndDiv": "jo",    # 조
    "wnNo1Div": "100k",  # 십만
    "wnNo2Div": "10k",   # 만
    "wnNo3Div": "1k",    # 천
    "wnNo4Div": "100",   # 백
    "wnNo5Div": "10",    # 십
    "wnNo6Div": "1"      # 일
}

def _to_int_safe(text: str):
    """숫자만 추출해 int 변환 (예: '65회' -> 65)"""
    s = re.sub(r"[^\d]", "", text or "")
    return int(s) if s else 0

def ensure_table():
    """테이블 생성 확인"""
    conn = pymysql.connect(**DB_CONFIG)
    cur = conn.cursor()
    sql = """
    CREATE TABLE IF NOT EXISTS pension_digit_stats (
      position VARCHAR(10) NOT NULL,    -- jo, 100k, 10k, ...
      digit TINYINT NOT NULL,           -- 0~9 (조는 1~5)
      win_count INT NOT NULL,
      updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP 
        ON UPDATE CURRENT_TIMESTAMP,
      PRIMARY KEY (position, digit)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """
    cur.execute(sql)
    conn.close()

def insert_digit_stats_bulk(rows: list[dict]):
    """데이터 UPSERT (저장 및 갱신)"""
    if not rows:
        print("ℹ️ 저장할 데이터가 없습니다.")
        return

    conn = pymysql.connect(**DB_CONFIG)
    cur = conn.cursor()
    sql = """
        INSERT INTO pension_digit_stats (position, digit, win_count)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE
          win_count = VALUES(win_count),
          updated_at = CURRENT_TIMESTAMP
    """
    data = [(r["position"], r["digit"], r["win_count"]) for r in rows]
    cur.executemany(sql, data)
    conn.commit()
    conn.close()
    print(f"✅ 자리수 통계 {len(rows)}건 DB 저장 완료")

def crawl_pension_stats():
    """연금복권 통계 페이지 크롤링"""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 15)
    
    results = []
    
    try:
        print(f"🌐 통계 페이지 접속 중: {URL}")
        driver.get(URL)
        
        # 데이터 그리드가 로딩될 때까지 대기
        wait.until(EC.presence_of_element_located((By.ID, "wnBndDiv")))
        time.sleep(1) # JS 렌더링 안정화
        
        soup = BeautifulSoup(driver.page_source, "html.parser")
        
        # ID_TO_POSITION에 정의된 각 ID 섹션을 순회하며 파싱
        for div_id, pos_name in ID_TO_POSITION.items():
            print(f"📊 {pos_name} 데이터 수집 중...")
            container = soup.find("div", id=div_id)
            
            if not container:
                print(f"⚠️ {div_id} 섹션을 찾을 수 없습니다.")
                continue
                
            # 각 번호 상자(.result-ballBox) 추출
            ball_boxes = container.select(".result-ballBox")
            for box in ball_boxes:
                digit_tag = box.select_one(".wf-ball")
                count_tag = box.select_one(".result-txt")
                
                if digit_tag and count_tag:
                    digit = _to_int_safe(digit_tag.text)
                    win_count = _to_int_safe(count_tag.text)
                    
                    results.append({
                        "position": pos_name,
                        "digit": digit,
                        "win_count": win_count
                    })
                    
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
    finally:
        driver.quit()
        
    return results

def main():
    print("🚀 연금복권 자리수 통계 수집 프로세스 시작")
    ensure_table()
    
    stats_data = crawl_pension_stats()
    if stats_data:
        insert_digit_stats_bulk(stats_data)
        
    print("🏁 모든 작업이 완료되었습니다.")

if __name__ == "__main__":
    main()