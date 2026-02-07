import requests
import pymysql
import time
import subprocess
import os

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
        
def update_carryover_statistics(cursor, current_round):
    """방금 저장된 회차와 이전 회차를 비교하여 통계 테이블 갱신"""
    cursor.execute("""
        SELECT ltEpsd, tm1WnNo, tm2WnNo, tm3WnNo, tm4WnNo, tm5WnNo, tm6WnNo, bnsWnNo 
        FROM lotto_numbers 
        WHERE ltEpsd IN (%s, %s) 
        ORDER BY ltEpsd ASC
    """, (current_round - 1, current_round))
    
    rows = cursor.fetchall()
    if len(rows) < 2:
        return

    prev, curr = rows[0], rows[1]
    
    # 1. 집합 생성
    prev_main = {prev[f'tm{j}WnNo'] for j in range(1, 7)}
    prev_bonus = prev['bnsWnNo']
    prev_all = prev_main | {prev_bonus} # 지난주 메인 + 보너스 (총 7개)
    
    curr_main = {curr[f'tm{j}WnNo'] for j in range(1, 7)}

    # 2. 이월수 계산 (핵심 수정!)
    # match_6: 지난주 메인(6개) 중 이번 주 메인에 나온 개수
    # match_7: 지난주 전체(7개) 중 이번 주 메인에 나온 개수
    intersection_6 = prev_main & curr_main
    intersection_7 = prev_all & curr_main
    
    match_6 = len(intersection_6)
    match_7 = len(intersection_7)
    
    # [수정] 분석 API가 찾을 수 있도록 '보너스 포함 겹친 번호'를 저장합니다.
    matched_nums_str = ",".join(map(str, sorted(list(intersection_7))))

    # 3. History 테이블 저장
    cursor.execute("""
        INSERT INTO lotto_carryover_history (round, match_count, match_count_with_bonus, matched_numbers)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE match_count=%s, match_count_with_bonus=%s, matched_numbers=%s
    """, (current_round, match_6, match_7, matched_nums_str, match_6, match_7, matched_nums_str))

    # 4. Summary 테이블 누적 업데이트 (분리 업데이트)
    # [수정] 보너스 제외 통계는 match_6 기준, 보너스 포함 통계는 match_7 기준으로 각각 업데이트
    
    # 보너스 제외 컬럼 업데이트
    cursor.execute("""
        UPDATE lotto_carryover_summary 
        SET occurrence_total = occurrence_total + 1
        WHERE match_count = %s
    """, (match_6,))
    
    # 보너스 포함 컬럼 업데이트
    cursor.execute("""
        UPDATE lotto_carryover_summary 
        SET occurrence_with_bonus = occurrence_with_bonus + 1
        WHERE match_count = %s
    """, (match_7,))

    print(f"📊 {current_round}회차 통계 반영: 제외({match_6}개), 포함({match_7}개) | 번호: {matched_nums_str}")


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

            # 신규 회차가 추가되었을 때만 분석 스크립트 실행
            if new_count > 0:
                print("📈 신규 데이터 감지: 이월 조합 적중률 재분석을 시작합니다...")
                
                # 같은 폴더에 있는 파일을 실행하도록 경로 지정
                base_path = os.path.dirname(os.path.abspath(__file__))
                script_path = os.path.join(base_path, "carryover_init.py")
                
                # subprocess 실행 (들여쓰기 주의!)
                result = subprocess.run(["python3", script_path], capture_output=True, text=True)
                
                if result.returncode == 0:
                    print("✨ 모든 조합 분석 및 테이블 갱신이 성공적으로 끝났습니다.")
                else:
                    print(f"⚠️ 분석 스크립트 실행 중 오류 발생: {result.stderr}")
    except Exception as e:
        print(f"❗ 오류 발생: {e}")
    finally:
        if 'conn' in locals(): conn.close()

if __name__ == "__main__":
    crawl_and_update()