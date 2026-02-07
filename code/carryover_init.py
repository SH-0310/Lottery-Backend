import pymysql

# DB 설정
DB_CONFIG = {
    'host': '127.0.0.1',
    'user': 'admin',
    'password': 'chaerin', # 실제 비밀번호로 변경
    'db': 'lottery_app',
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor
}

def initialize_carryover_stats():
    conn = pymysql.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cursor:
            print("1. 기존 데이터 초기화...")
            cursor.execute("TRUNCATE TABLE lotto_carryover_history")
            cursor.execute("UPDATE lotto_carryover_summary SET occurrence_total = 0, occurrence_with_bonus = 0")

            print("2. 데이터 로드 중...")
            cursor.execute("SELECT ltEpsd, tm1WnNo, tm2WnNo, tm3WnNo, tm4WnNo, tm5WnNo, tm6WnNo, bnsWnNo FROM lotto_numbers ORDER BY ltEpsd ASC")
            rows = cursor.fetchall()

            summary_6 = {i: 0 for i in range(7)}
            summary_7 = {i: 0 for i in range(7)}
            history_data = []

            print(f"3. {len(rows)}회차 정밀 분석 시작...")
            for i in range(1, len(rows)):
                prev = rows[i-1]
                curr = rows[i]

                prev_main = {prev[f'tm{j}WnNo'] for j in range(1, 7)}
                prev_bonus = {prev['bnsWnNo']} # 보너스 번호만 따로 관리
                curr_main = {curr[f'tm{j}WnNo'] for j in range(1, 7)}

                # A. 순수 메인 이월수 (Case 1)
                main_carry = prev_main & curr_main
                
                # B. 보너스 승격수 (Case 3)
                bonus_carry = prev_bonus & curr_main

                # C. 전체 이월수 (Case 2 = A + B)
                all_carry = main_carry | bonus_carry

                match_6 = len(main_carry)
                match_7 = len(all_carry)

                # 문자열로 변환 (DB 저장용)
                matched_nums_str = ",".join(map(str, sorted(list(all_carry))))
                bonus_nums_str = ",".join(map(str, sorted(list(bonus_carry))))

                # 히스토리 데이터 생성 (새 컬럼 포함)
                history_data.append((
                    curr['ltEpsd'], 
                    match_6, 
                    match_7, 
                    matched_nums_str, 
                    bonus_nums_str  # bonus_matched_numbers 컬럼 대응
                ))

                summary_6[match_6] += 1
                summary_7[match_7] += 1

            # 4. 히스토리 일괄 삽입
            print("4. History 데이터 저장 중...")
            sql_hist = """
                INSERT INTO lotto_carryover_history 
                (round, match_count, match_count_with_bonus, matched_numbers, bonus_matched_numbers) 
                VALUES (%s, %s, %s, %s, %s)
            """
            cursor.executemany(sql_hist, history_data)

            # 5. 요약 테이블 업데이트
            print("5. Summary 데이터 업데이트 중...")
            for i in range(7):
                cursor.execute("""
                    UPDATE lotto_carryover_summary 
                    SET occurrence_total = %s, occurrence_with_bonus = %s 
                    WHERE match_count = %s
                """, (summary_6[i], summary_7[i], i))

            conn.commit()
            print("✅ 분석 및 저장이 완료되었습니다!")

    except Exception as e:
        print(f"❌ 에러 발생: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    initialize_carryover_stats()