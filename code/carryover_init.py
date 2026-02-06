import pymysql

# DB 설정 (기존 정보 사용)
DB_CONFIG = {
    'host': '127.0.0.1',
    'user': 'admin',
    'password': 'chaerin',
    'db': 'lottery_app',
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor
}

def initialize_carryover_stats():
    conn = pymysql.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cursor:
            print("1. 기존 통계 데이터 초기화 중...")
            cursor.execute("TRUNCATE TABLE lotto_carryover_history")
            cursor.execute("UPDATE lotto_carryover_summary SET occurrence_total = 0, occurrence_with_bonus = 0")

            print("2. 전체 로또 당첨 번호 로드 중...")
            cursor.execute("SELECT ltEpsd, tm1WnNo, tm2WnNo, tm3WnNo, tm4WnNo, tm5WnNo, tm6WnNo, bnsWnNo FROM lotto_numbers ORDER BY ltEpsd ASC")
            rows = cursor.fetchall()

            summary_6 = {i: 0 for i in range(7)}
            summary_7 = {i: 0 for i in range(7)}
            history_data = []

            print(f"3. 총 {len(rows)}회차 데이터 분석 시작...")
            for i in range(1, len(rows)):
                prev = rows[i-1]
                curr = rows[i]

                # 비교군 생성 (지난주 번호들)
                prev_set_6 = {prev[f'tm{j}WnNo'] for j in range(1, 7)}
                prev_set_7 = prev_set_6 | {prev['bnsWnNo']} # 보너스 포함

                # 이번주 당첨번호 6개
                curr_set_6 = {curr[f'tm{j}WnNo'] for j in range(1, 7)}

                match_6 = len(prev_set_6 & curr_set_6)
                match_7 = len(prev_set_7 & curr_set_6)
                # prev_set_7(보너스 포함)을 사용하여 교집합을 구해야 보너스 번호가 섞여 들어갑니다.
                matched_nums = ",".join(map(str, sorted(list(prev_set_7 & curr_set_6))))

                # 히스토리 리스트에 추가
                history_data.append((curr['ltEpsd'], match_6, match_7, matched_nums))

                # 요약 데이터 카운트
                summary_6[match_6] += 1
                summary_7[match_7] += 1

            # 4. 히스토리 일괄 삽입 (Batch Insert)
            print("4. 분석 결과 DB 저장 중 (History)...")
            sql_hist = "INSERT INTO lotto_carryover_history (round, match_count, match_count_with_bonus, matched_numbers) VALUES (%s, %s, %s, %s)"
            cursor.executemany(sql_hist, history_data)

            # 5. 요약 테이블 업데이트
            print("5. 분석 결과 DB 저장 중 (Summary)...")
            for i in range(7):
                cursor.execute("""
                    UPDATE lotto_carryover_summary 
                    SET occurrence_total = %s, occurrence_with_bonus = %s 
                    WHERE match_count = %s
                """, (summary_6[i], summary_7[i], i))

            conn.commit()
            print("✅ 모든 통계 초기화가 성공적으로 완료되었습니다!")

    except Exception as e:
        print(f"❌ 에러 발생: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    initialize_carryover_stats()