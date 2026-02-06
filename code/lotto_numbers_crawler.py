import requests
import pymysql
import time

# 1. DB 접속 정보 (기존 유지)
DB_CONFIG = {
    'host': '127.0.0.1',
    'user': 'admin',
    'password': 'chaerin',
    'db': 'lottery_app',
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor
}

def get_latest_round_in_db():
    conn = pymysql.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT MAX(ltEpsd) as last_round FROM lotto_numbers")
            result = cursor.fetchone()
            return result['last_round'] if result['last_round'] else 0
    finally:
        conn.close()

# --- [추가된 함수: 이월수 통계 업데이트] ---
def update_carryover_statistics(cursor, current_round):
    """방금 저장된 회차와 이전 회차를 비교하여 통계 테이블 갱신"""
    # 1. 이번 회차와 이전 회차 번호 가져오기
    cursor.execute("""
        SELECT ltEpsd, tm1WnNo, tm2WnNo, tm3WnNo, tm4WnNo, tm5WnNo, tm6WnNo, bnsWnNo 
        FROM lotto_numbers 
        WHERE ltEpsd IN (%s, %s) 
        ORDER BY ltEpsd ASC
    """, (current_round - 1, current_round))
    
    rows = cursor.fetchall()
    if len(rows) < 2:
        return # 이전 회차 데이터가 없으면 계산 불가

    prev, curr = rows[0], rows[1]
    
    # 2. 이월수 계산 (Set 집합 연산 사용)
    prev_set_6 = {prev[f'tm{j}WnNo'] for j in range(1, 7)}
    prev_set_7 = prev_set_6 | {prev['bnsWnNo']} # 보너스 포함
    curr_set_6 = {curr[f'tm{j}WnNo'] for j in range(1, 7)}

    match_6 = len(prev_set_6 & curr_set_6)
    match_7 = len(prev_set_7 & curr_set_6)
    matched_nums = ",".join(map(str, sorted(list(prev_set_6 & curr_set_6))))

    # 3. History 테이블 저장
    cursor.execute("""
        INSERT INTO lotto_carryover_history (round, match_count, match_count_with_bonus, matched_numbers)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE match_count=%s, match_count_with_bonus=%s, matched_numbers=%s
    """, (current_round, match_6, match_7, matched_nums, match_6, match_7, matched_nums))

    # 4. Summary 테이블 누적 업데이트
    # (주의: 만약 스크립트를 실수로 중복 실행할 경우를 대비해 
    # 실제 앱 운영시에는 '이미 처리된 회차인지' 체크하는 로직이 있으면 더 안전합니다.)
    cursor.execute("""
        UPDATE lotto_carryover_summary 
        SET occurrence_total = occurrence_total + 1,
            occurrence_with_bonus = occurrence_with_bonus + 1
        WHERE match_count = %s
    """, (match_6,))
    print(f"📊 {current_round}회차 이월수 통계 반영 완료 (이월수: {match_6}개)")

# ----------------------------------------------

def crawl_and_update():
    last_db_round = get_latest_round_in_db()
    print(f"현재 DB 최신 회차: {last_db_round}")

    url = "https://www.dhlottery.co.kr/lt645/selectPstLt645Info.do"
    params = {"srchLtEpsd": "all", "_": str(int(time.time() * 1000))}
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 Edg/144.0.0.0',
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'ajax': 'true',
        'X-Requested-With': 'XMLHttpRequest',
        'Referer': 'https://www.dhlottery.co.kr/lt645/result'
    }

    try:
        response = requests.get(url, params=params, headers=headers)
        res_json = response.json()
        lotto_list = res_json.get("data", {}).get("list", [])

        if not lotto_list:
            print("가져온 데이터가 없습니다.")
            return

        conn = pymysql.connect(**DB_CONFIG)
        new_count = 0

        with conn.cursor() as cursor:
            # SQL 문 구성 (기존 컬럼명 유지)
            sql = """
            INSERT INTO lotto_numbers (
                winType0, winType1, winType2, winType3, gmSqNo, ltEpsd, ltRflYmd, 
                tm1WnNo, tm2WnNo, tm3WnNo, tm4WnNo, tm5WnNo, tm6WnNo, bnsWnNo,
                rnk1WnNope, rnk1WnAmt, rnk1SumWnAmt,
                rnk2WnNope, rnk2WnAmt, rnk2SumWnAmt,
                rnk3WnNope, rnk3WnAmt, rnk3SumWnAmt,
                rnk4WnNope, rnk4WnAmt, rnk4SumWnAmt,
                rnk5WnNope, rnk5WnAmt, rnk5SumWnAmt,
                sumWnNope, rlvtEpsdSumNtslAmt, wholEpsdSumNtslAmt, excelRnk
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, 
                %s, %s, %s, %s, %s, %s, %s, 
                %s, %s, %s, 
                %s, %s, %s, 
                %s, %s, %s, 
                %s, %s, %s, 
                %s, %s, %s, 
                %s, %s, %s, %s
            )
            """

            # 최신 회차가 위로 오므로 뒤집어서 과거 순으로 처리해야 
            # 이전 회차와 비교하며 통계를 쌓기에 좋습니다.
            for item in reversed(lotto_list): 
                epsd = item["ltEpsd"]
                
                if epsd > last_db_round:
                    # [A] 기본 당첨 번호 저장
                    raw_date = str(item["ltRflYmd"])
                    formatted_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
                    
                    params_tuple = (
                    item["winType0"], item["winType1"], item["winType2"], item["winType3"], 
                    item["gmSqNo"], item["ltEpsd"], formatted_date,
                    item["tm1WnNo"], item["tm2WnNo"], item["tm3WnNo"], item["tm4WnNo"], 
                    item["tm5WnNo"], item["tm6WnNo"], item["bnsWnNo"],
                    item["rnk1WnNope"], item["rnk1WnAmt"], item["rnk1SumWnAmt"],
                    item["rnk2WnNope"], item["rnk2WnAmt"], item["rnk2SumWnAmt"],
                    item["rnk3WnNope"], item["rnk3WnAmt"], item["rnk3SumWnAmt"],
                    item["rnk4WnNope"], item["rnk4WnAmt"], item["rnk4SumWnAmt"],
                    item["rnk5WnNope"], item["rnk5WnAmt"], item["rnk5SumWnAmt"],
                    item["sumWnNope"], item["rlvtEpsdSumNtslAmt"], item["wholEpsdSumNtslAmt"], 
                    item["excelRnk"]
                    )
                    cursor.execute(sql, params_tuple)

                    # (기존 params_tuple 및 execute 로직 유지)
                    # cursor.execute(sql, params_tuple)
                    
                    # [B] 이월수 통계 자동 업데이트 호출!
                    update_carryover_statistics(cursor, epsd)
                    
                    new_count += 1
                    print(f"✅ {epsd}회차 저장 및 통계 업데이트 성공")

            conn.commit()
            print(f"🚀 전체 업데이트 완료! 총 {new_count}개의 데이터가 처리되었습니다.")

    except Exception as e:
        print(f"❗ 오류 발생: {e}")
    finally:
        if 'conn' in locals(): conn.close()

if __name__ == "__main__":
    crawl_and_update()