import pymysql
from itertools import combinations

# DB 설정
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
            # --- 1. 기존 데이터 초기화 ---
            print("1. 모든 통계 데이터 초기화 중...")
            cursor.execute("TRUNCATE TABLE lotto_carryover_history")
            cursor.execute("TRUNCATE TABLE lotto_carryover_combo_analysis")
            cursor.execute("UPDATE lotto_carryover_summary SET occurrence_total = 0, occurrence_with_bonus = 0")

            # --- 2. 기본 데이터 로드 ---
            cursor.execute("SELECT ltEpsd, tm1WnNo, tm2WnNo, tm3WnNo, tm4WnNo, tm5WnNo, tm6WnNo, bnsWnNo FROM lotto_numbers ORDER BY ltEpsd ASC")
            rows = cursor.fetchall()
            if not rows:
                print("❌ 분석할 로또 데이터가 없습니다.")
                return

            # --- 3. 히스토리 및 요약 테이블 생성 ---
            summary_6 = {i: 0 for i in range(7)}
            summary_7 = {i: 0 for i in range(7)}
            history_data = []

            print(f"2. {len(rows)}회차 히스토리 분석 시작...")
            for i in range(1, len(rows)):
                prev, curr = rows[i-1], rows[i]
                prev_main = {prev[f'tm{j}WnNo'] for j in range(1, 7)}
                prev_bonus = {prev['bnsWnNo']}
                curr_main = {curr[f'tm{j}WnNo'] for j in range(1, 7)}

                main_carry = prev_main & curr_main
                bonus_carry = prev_bonus & curr_main
                all_carry = main_carry | bonus_carry

                match_6, match_7 = len(main_carry), len(all_carry)
                history_data.append((
                    curr['ltEpsd'], match_6, match_7,
                    ",".join(map(str, sorted(list(all_carry)))),
                    ",".join(map(str, sorted(list(bonus_carry))))
                ))
                summary_6[match_6] += 1
                summary_7[match_7] += 1

            # 히스토리/요약 저장
            cursor.executemany("INSERT INTO lotto_carryover_history (round, match_count, match_count_with_bonus, matched_numbers, bonus_matched_numbers) VALUES (%s, %s, %s, %s, %s)", history_data)
            for i in range(7):
                cursor.execute("UPDATE lotto_carryover_summary SET occurrence_total = %s, occurrence_with_bonus = %s WHERE match_count = %s", (summary_6[i], summary_7[i], i))
            
            print("✅ 히스토리 및 요약 업데이트 완료.")

            # --- 4. [핵심] 최신 회차 조합 분석 (Combo Analysis) ---
            latest = rows[-1]
            target_round = latest['ltEpsd']
            last_main = [latest[f'tm{j}WnNo'] for j in range(1, 7)]
            last_bonus = latest['bnsWnNo']
            
            print(f"3. {target_round}회차 기반 모든 번호 조합(1~6개) 적중률 분석 시작...")

            for include_bonus in [0, 1]:
                candidates = last_main + ([last_bonus] if include_bonus else [])
                bonus_tag = "보너스 포함" if include_bonus else "보너스 제외"
                
                for r in range(1, 7):
                    if r > len(candidates): continue
                    print(f"   > {bonus_tag}: {r}개 조합 분석 중...")
                    
                    for combo in combinations(candidates, r):
                        combo = sorted(list(combo))
                        combo_str = ",".join(map(str, combo))
                        
                        # 과거 기회(Opportunity) 찾기
                        # 해당 조합이 메인+보너스(7개)에 모두 포함되었던 회차들
                        where_clauses = [f"FIND_IN_SET({n}, CONCAT_WS(',', tm1WnNo, tm2WnNo, tm3WnNo, tm4WnNo, tm5WnNo, tm6WnNo, bnsWnNo))" for n in combo]
                        sql_appear = f"SELECT ltEpsd FROM lotto_numbers WHERE {' AND '.join(where_clauses)} AND ltEpsd < %s"
                        cursor.execute(sql_appear, (target_round,))
                        opp_rounds = [row['ltEpsd'] for row in cursor.fetchall()]
                        
                        total_appear = len(opp_rounds)
                        success_rounds = []

                        # 실제 이월 성공 여부 확인
                        if total_appear > 0:
                            for rd in opp_rounds:
                                next_rd = rd + 1
                                check_clauses = [f"FIND_IN_SET({n}, CONCAT_WS(',', tm1WnNo, tm2WnNo, tm3WnNo, tm4WnNo, tm5WnNo, tm6WnNo))" for n in combo]
                                sql_check = f"SELECT COUNT(*) as ok FROM lotto_numbers WHERE ltEpsd = %s AND {' AND '.join(check_clauses)}"
                                cursor.execute(sql_check, (next_rd,))
                                if cursor.fetchone()['ok'] > 0:
                                    success_rounds.append(next_rd)

                        total_occur = len(success_rounds)
                        hit_rate = round((total_occur / total_appear) * 100, 2) if total_appear > 0 else 0
                        history_str = ",".join(map(str, sorted(success_rounds, reverse=True)))

                        # 결과 저장
                        cursor.execute("""
                            INSERT INTO lotto_carryover_combo_analysis 
                            (target_round, combo_count, include_bonus, numbers_combo, total_occur, total_appear, hit_rate, history_rounds)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """, (target_round, r, include_bonus, combo_str, total_occur, total_appear, hit_rate, history_str))

            conn.commit()
            print(f"🎉 모든 분석이 완료되었습니다! (기준 회차: {target_round}회)")

    except Exception as e:
        print(f"❌ 에러 발생: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    initialize_carryover_stats()