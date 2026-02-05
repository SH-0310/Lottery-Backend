import requests
import pymysql
import time

# 1. DB 접속 정보
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

def crawl_and_update():
    last_db_round = get_latest_round_in_db()
    print(f"현재 DB 최신 회차: {last_db_round}")

    # 2. 제공해주신 헤더 정보를 바탕으로 요청 설정
    url = "https://www.dhlottery.co.kr/lt645/selectPstLt645Info.do"
    params = {
        "srchLtEpsd": "all",
        "_": str(int(time.time() * 1000)) # 타임스탬프
    }
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 Edg/144.0.0.0',
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'ajax': 'true',
        'X-Requested-With': 'XMLHttpRequest',
        'Referer': 'https://www.dhlottery.co.kr/lt645/result'
    }

    try:
        print("동행복권 API 데이터 요청 중...")
        response = requests.get(url, params=params, headers=headers)
        
        # 3. JSON 데이터 파싱
        # 응답이 JSON이므로 BeautifulSoup 대신 response.json() 사용
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

            for item in lotto_list:
                epsd = item["ltEpsd"]
                
                # DB에 없는 새로운 회차만 저장
                if epsd > last_db_round:
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
                    new_count += 1
                    print(f"✅ {epsd}회차 저장 성공")

            conn.commit()
            print(f"🚀 업데이트 완료! 총 {new_count}개의 새로운 회차가 추가되었습니다.")

    except Exception as e:
        print(f"❗ 오류 발생: {e}")
    finally:
        if 'conn' in locals(): conn.close()

if __name__ == "__main__":
    crawl_and_update()