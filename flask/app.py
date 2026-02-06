from flask import Flask, jsonify, request, Response
import pymysql
import json
from datetime import datetime, date
from decimal import Decimal
from werkzeug.middleware.proxy_fix import ProxyFix
import logging

app = Flask(__name__)

# 1. 로드밸런서 설정 (앞에 LB가 1대 있을 때)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)

# 2. 로그 설정 (에러 방지를 위해 표준 포맷 사용)
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
)

# 3. 요청 로그 기록 (함수 하나로 통합)
@app.before_request
def log_request_info():
    # request.remote_addr에 실제 IP가 담기게 됩니다 (ProxyFix 덕분)
    client_ip = request.remote_addr
    method = request.method
    path = request.path
    app.logger.info(f"CONNECTED IP: {client_ip} - {method} {path}")

    
# DB 접속 정보
DB_CONFIG = {
    'host': '127.0.0.1',
    'user': 'admin',
    'password': 'chaerin',
    'db': 'lottery_app',
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor
}


@app.route('/lotto/latest', methods=['GET'])
def get_latest_lotto():
    try:
        with pymysql.connect(**DB_CONFIG) as conn:
            with conn.cursor() as cursor:
                # ✅ lotto 대신 lotto_numbers 테이블에서 최신 회차(ltEpsd DESC) 1건 조회
                cursor.execute("SELECT * FROM lotto_numbers ORDER BY ltEpsd DESC LIMIT 1")
                result = cursor.fetchone()
                
                if result:
                    # ✅ 기존에 정의하신 상세 포맷터(format_lotto_numbers_result)를 사용하여 반환
                    formatted = format_lotto_numbers_result(result)
                    return jsonify(formatted)
                
                return jsonify({"error": "No data found"}), 404
    except Exception as e:
        print(f"Error in /lotto/latest: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/lotto/round/<int:round_number>', methods=['GET'])
def get_lotto_by_round(round_number):
    try:
        with pymysql.connect(**DB_CONFIG) as conn:
            with conn.cursor() as cursor:
                # 1. lotto_numbers 테이블에서 해당 회차 데이터만 정확히 조회
                sql = """
                    SELECT 
                        ltEpsd, ltRflYmd, 
                        tm1WnNo, tm2WnNo, tm3WnNo, tm4WnNo, tm5WnNo, tm6WnNo, bnsWnNo,
                        rnk1WnAmt, rnk1WnNope, rnk2WnAmt, wholEpsdSumNtslAmt
                    FROM lotto_numbers 
                    WHERE ltEpsd = %s
                """
                cursor.execute(sql, (round_number,))
                row = cursor.fetchone()
                
                if row:
                    # 2. 요청하신 JSON 형식으로 직접 매핑
                    result = {
                        "round": row["ltEpsd"],
                        "draw_date": row["ltRflYmd"].isoformat() if isinstance(row["ltRflYmd"], (date, datetime)) else str(row["ltRflYmd"]),
                        "numbers": [
                            row["tm1WnNo"], row["tm2WnNo"], row["tm3WnNo"], 
                            row["tm4WnNo"], row["tm5WnNo"], row["tm6WnNo"]
                        ],
                        "bonus": row["bnsWnNo"],
                        "first_prize_amt": int(row["rnk1WnAmt"]),
                        "first_winner_count": int(row["rnk1WnNope"]),
                        "second_prize_amt": int(row["rnk2WnAmt"]),
                        "total_sales": int(row["wholEpsdSumNtslAmt"])
                    }
                    return jsonify(result)
                
                return jsonify({"error": "Round not found"}), 404
    except Exception as e:
        app.logger.error(f"Error in /lotto/round/{round_number}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/lotto/count', methods=['GET'])
def get_lotto_count():
    try:
        with pymysql.connect(**DB_CONFIG) as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) as count FROM lotto")
                result = cursor.fetchone()
                return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/lotto/gaps', methods=['GET'])
def get_lotto_gaps():
    """
    로또 번호별 모든 미출현 통계 조회 (보너스 포함/제외 데이터 전체 포함)
    """
    try:
        # 45개 번호 전체를 조회하므로 복잡한 WHERE 절은 일단 생략하고 
        # 모든 컬럼을 가져옵니다.
        sql = """
            SELECT 
                number, 
                weeks_since, last_round, last_date,
                weeks_since_with_bonus, last_round_with_bonus, last_date_with_bonus
            FROM lotto_gap_stats_main
            ORDER BY number ASC
        """

        with pymysql.connect(**DB_CONFIG) as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(sql)
                rows = cursor.fetchall()

        # ✅ date/datetime 객체를 JSON 전송 가능하도록 문자열로 변환
        formatted_rows = [format_speetto_status_result(row) for row in rows]

        return app.response_class(
            response=json.dumps(formatted_rows, ensure_ascii=False),
            status=200,
            mimetype='application/json'
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/lotto/ai', methods=['GET'])
def get_ai_recommendations():
    """
    ai_recommendations 테이블에서 agency, numbers_json, reasoning 컬럼을 반환
    - 기본: 최신 4건 (id DESC)
    - 쿼리 파라미터:
        - limit: 반환 개수 (예: ?limit=4)
    """
    try:
        limit = request.args.get('limit', default=4, type=int)
        if limit is None or limit <= 0:
            limit = 4

        sql = """
            SELECT agency, numbers_json, reasoning
            FROM ai_recommendations
            ORDER BY id DESC
            LIMIT %s
        """

        with pymysql.connect(**DB_CONFIG) as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(sql, (limit,))
                rows = cursor.fetchall()

        # numbers_json은 DB에 문자열(JSON)로 저장되어 있을 수 있으므로,
        # 그대로 전달(문자열)합니다. 클라이언트에서 필요 시 파싱하세요.
        return app.response_class(
            response=json.dumps(rows, ensure_ascii=False),
            status=200,
            mimetype='application/json'
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/lotto/number-stats', methods=['GET'])
def get_lotto_number_stats():
    """
    lotto_number_stats 조회
    - numbers: 1,7,23
    - includeBonus: true | false
    - minCount/maxCount: win_count 범위
    - order: win_desc | win_asc | num_asc | num_desc | bonus_asc | bonus_desc
    - limit: 최대 개수
    """
    numbers_param    = request.args.get('numbers')
    include_bonus_q  = request.args.get('includeBonus')
    min_count        = request.args.get('minCount', type=int)
    max_count        = request.args.get('maxCount', type=int)
    limit            = request.args.get('limit', type=int)
    order            = (request.args.get('order') or 'win_desc').lower()

    order_map = {
        'win_desc':   '`win_count` DESC, `number` ASC, `include_bonus` ASC',
        'win_asc':    '`win_count` ASC,  `number` ASC, `include_bonus` ASC',
        'num_asc':    '`number` ASC,     `include_bonus` ASC',
        'num_desc':   '`number` DESC,    `include_bonus` ASC',
        'bonus_asc':  '`include_bonus` ASC, `number` ASC',
        'bonus_desc': '`include_bonus` DESC, `number` ASC',
    }
    order_by = order_map.get(order, order_map['win_desc'])

    where_clauses = []
    params = []

    # numbers IN (...)
    if numbers_param:
        nums = [x.strip() for x in numbers_param.split(',') if x.strip().isdigit()]
        if nums:
            placeholders = ",".join(["%s"] * len(nums))
            where_clauses.append(f"`number` IN ({placeholders})")
            params.extend(int(n) for n in nums)

    # include_bonus = 1/0
    if include_bonus_q is not None:
        val_str = str(include_bonus_q).strip().lower()
        val = 1 if val_str in ('1', 'true', 't', 'yes', 'y') else 0
        where_clauses.append("`include_bonus` = %s")
        params.append(val)

    # win_count 범위
    if min_count is not None:
        where_clauses.append("`win_count` >= %s")
        params.append(min_count)
    if max_count is not None:
        where_clauses.append("`win_count` <= %s")
        params.append(max_count)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    # LIMIT 구성 (값 없으면 아예 문구 제거)
    limit_sql = ""
    if isinstance(limit, int) and limit > 0:
        limit_sql = "LIMIT %s"
        params.append(limit)

    sql = f"""
        SELECT `number`, `include_bonus`, `win_count`
        FROM `lotto_number_stats`
        {where_sql}
        ORDER BY {order_by}
        {limit_sql}
    """

    try:
        with pymysql.connect(**DB_CONFIG) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        return app.response_class(
            response=json.dumps(rows, ensure_ascii=False),
            status=200,
            mimetype='application/json'
        )
    except Exception as e:
        # 필요하면 아래 주석을 잠시 해제해서 실제 SQL/파라미터를 확인하세요.
        # return jsonify({"error": str(e), "sql": sql, "params": params}), 500
        return jsonify({"error": str(e)}), 500


@app.route('/shops/in_bounds', methods=['GET'])
def get_shops_in_bounds():
    try:
        min_lat = float(request.args.get('minLat'))
        max_lat = float(request.args.get('maxLat'))
        min_lng = float(request.args.get('minLng'))
        max_lng = float(request.args.get('maxLng'))
        lotto_only = request.args.get('lottoOnly') == 'true'

        with pymysql.connect(**DB_CONFIG) as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                # 기본 쿼리
                query = """
                    SELECT
                        shop_id,
                        shop_name,
                        location,
                        phone,
                        lat AS latitude,
                        lng AS longitude,
                        COALESCE(lotto_winner, 0)     AS lotto_winner,
                        COALESCE(lotto_winner_2nd, 0) AS lotto_winner_2nd
                    FROM lottery_shops
                    WHERE lat BETWEEN %s AND %s
                    AND lng BETWEEN %s AND %s
                """
                params = [min_lat, max_lat, min_lng, max_lng]

                # lottoOnly 파라미터가 true일 경우 필터 추가
                #if lotto_only:
                #    query += " AND lotto = 1"

                cursor.execute(query, params)
                result = cursor.fetchall()

                return app.response_class(
                    response=json.dumps(result, ensure_ascii=False),
                    status=200,
                    mimetype='application/json'
                )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/shops/total/in_bounds', methods=['GET'])
def get_total_shops_in_bounds():
    """
    안드로이드 앱의 지도를 축소했을 때 데이터 폭증을 막기 위해 
    복권별 당첨 횟수 필터를 적용한 통합 조회 API
    """
    try:
        # 1. 위치 파라미터 수신
        min_lat = float(request.args.get('minLat'))
        max_lat = float(request.args.get('maxLat'))
        min_lng = float(request.args.get('minLng'))
        max_lng = float(request.args.get('maxLng'))

        # 2. 복권 종류별 필터 파라미터 수신 (기본값 0)
        mw_lotto = request.args.get('minWins_lotto', default=0, type=int)
        mw_pension = request.args.get('minWins_pension', default=0, type=int)
        mw_speetto = request.args.get('minWins_speetto', default=0, type=int)

        # 3. SQL 쿼리 (2등 및 보너스 당첨 정보 포함)
        sql = """
            SELECT 
                ltShpId AS shop_id, 
                conmNm AS shop_name, 
                shpTelno AS phone,
                bplcRdnmDaddr AS location, 
                shpLat AS latitude, 
                shpLot AS longitude,
                
                -- 판매 여부
                l645LtNtslYn AS lotto_yn, 
                pt720NtslYn AS pension_yn,
                st20LtNtslYn AS speetto2000_yn, 
                st10LtNtslYn AS speetto1000_yn, 
                st5LtNtslYn AS speetto500_yn,
                
                -- 당첨 정보 (1등, 2등, 보너스 통합)
                COALESCE(rank1_lotto, 0) AS lotto_winner,
                COALESCE(rank2_lotto, 0) AS lotto_winner_2nd,
                COALESCE(rank1_pension, 0) AS pension_winner,
                COALESCE(rank2_pension, 0) AS pension_winner_2nd,
                COALESCE(rankB_pension, 0) AS pension_winner_bonus,
                COALESCE(rank1_speetto2000, 0) AS s2000_winner,
                COALESCE(rank1_speetto1000, 0) AS s1000_winner,
                COALESCE(rank1_speetto500, 0) AS s500_winner
            FROM shops
            WHERE shpLat BETWEEN %s AND %s
              AND shpLot BETWEEN %s AND %s
              
              -- [필터 1] 로또 1등 당첨 횟수 기준
              AND COALESCE(rank1_lotto, 0) >= %s
              
              -- [필터 2] 연금복권 1등 당첨 횟수 기준
              AND COALESCE(rank1_pension, 0) >= %s
              
              -- [필터 3] 스피또(2000+1000+500) 1등 합계 기준
              AND (
                COALESCE(rank1_speetto2000, 0) + 
                COALESCE(rank1_speetto1000, 0) + 
                COALESCE(rank1_speetto500, 0)
              ) >= %s
        """
        
        # SQL 파라미터 매핑
        params = [min_lat, max_lat, min_lng, max_lng, mw_lotto, mw_pension, mw_speetto]

        with pymysql.connect(**DB_CONFIG) as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(sql, params)
                results = cursor.fetchall()

        # JSON 직렬화 가공 (날짜/소수점 처리)
        formatted_results = [format_speetto_status_result(row) for row in results]

        return app.response_class(
            response=json.dumps(formatted_results, ensure_ascii=False),
            status=200,
            mimetype='application/json'
        )

    except Exception as e:
        print(f"Error in /shops/total/in_bounds: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/pension/latest', methods=['GET'])
def get_latest_pension():
    try:
        with pymysql.connect(**DB_CONFIG) as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM pension ORDER BY round DESC LIMIT 1")
                result = cursor.fetchone()
                if result:
                    return app.response_class(
                        response=json.dumps(format_pension_result(result), ensure_ascii=False, indent=2),
                        status=200,
                        mimetype='application/json'
                    )
                return jsonify({"error": "No data found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/pension/round/<int:round_number>', methods=['GET'])
def get_pension_by_round(round_number):
    try:
        with pymysql.connect(**DB_CONFIG) as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM pension WHERE round = %s", (round_number,))
                result = cursor.fetchone()
                if result:
                    return app.response_class(
                        response=json.dumps(format_pension_result(result), ensure_ascii=False, indent=2),
                        status=200,
                        mimetype='application/json'
                    )
                return jsonify({"error": "Round not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/pension/count', methods=['GET'])
def get_pension_count():
    try:
        with pymysql.connect(**DB_CONFIG) as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) as count FROM pension")
                result = cursor.fetchone()
                return app.response_class(
                    response=json.dumps(result, ensure_ascii=False, indent=2),
                    status=200,
                    mimetype='application/json'
                )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/pension/digit-stats', methods=['GET'])
def get_pension_digit_stats():
    """
    pension_digit_stats 조회
    - positions: jo,100k,10k,1k,100,10,1
    - digits:    0..9
    - minCount/maxCount: win_count 범위
    - order: win_desc | win_asc | pos_asc | pos_desc | digit_asc | digit_desc
    - limit: 최대 개수
    """
    positions_param = request.args.get('positions')
    digits_param    = request.args.get('digits')
    min_count       = request.args.get('minCount', type=int)
    max_count       = request.args.get('maxCount', type=int)
    limit           = request.args.get('limit', type=int)
    order           = (request.args.get('order') or 'win_desc').lower()

    order_map = {
        'win_desc':  '`win_count` DESC, `position` ASC, `digit` ASC',
        'win_asc':   '`win_count` ASC,  `position` ASC, `digit` ASC',
        'pos_asc':   '`position` ASC,   `digit` ASC',
        'pos_desc':  '`position` DESC,  `digit` ASC',
        'digit_asc': '`digit` ASC,      `position` ASC',
        'digit_desc':'`digit` DESC,     `position` ASC',
    }
    order_by = order_map.get(order, order_map['win_desc'])

    where_clauses = []
    params = []

    if positions_param:
        pos_list = [p.strip() for p in positions_param.split(',') if p.strip()]
        if pos_list:
            placeholders = ",".join(["%s"] * len(pos_list))
            where_clauses.append(f"`position` IN ({placeholders})")
            params.extend(pos_list)

    if digits_param:
        digs = [x.strip() for x in digits_param.split(',') if x.strip().isdigit()]
        if digs:
            placeholders = ",".join(["%s"] * len(digs))
            where_clauses.append(f"`digit` IN ({placeholders})")
            params.extend(int(d) for d in digs)

    if min_count is not None:
        where_clauses.append("`win_count` >= %s")
        params.append(min_count)
    if max_count is not None:
        where_clauses.append("`win_count` <= %s")
        params.append(max_count)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    limit_sql = ""
    if isinstance(limit, int) and limit > 0:
        limit_sql = "LIMIT %s"
        params.append(limit)

    sql = f"""
        SELECT `position`, `digit`, `win_count`
        FROM `pension_digit_stats`
        {where_sql}
        ORDER BY {order_by}
        {limit_sql}
    """

    try:
        with pymysql.connect(**DB_CONFIG) as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
        return app.response_class(
            response=json.dumps(rows, ensure_ascii=False),
            status=200,
            mimetype='application/json'
        )
    except Exception as e:
        # 필요하면 아래 주석을 잠시 해제해서 실제 SQL/파라미터를 확인하세요.
        # return jsonify({"error": str(e), "sql": sql, "params": params}), 500
        return jsonify({"error": str(e)}), 500



@app.route("/speetto", methods=["GET"])
def get_speetto_data():
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    cursor.execute("""
        SELECT 
            speetto_type, round,
            first_prize, first_count,
            second_prize, second_count,
            third_prize, third_count,
            stocking_rate,
            image_source
        FROM speetto
        ORDER BY speetto_type DESC, round DESC
    """)
    rows = cursor.fetchall()
    conn.close()

    # 한글 깨짐 방지용 JSON 직렬화
    response_json = json.dumps(rows, ensure_ascii=False)
    return Response(response_json, content_type='application/json; charset=utf-8')

@app.route('/speetto/status', methods=['GET'])
def get_speetto_status():
    try:
        with pymysql.connect(**DB_CONFIG) as conn:
            with conn.cursor() as cursor:
                # DictCursor 설정이 DB_CONFIG에 있으므로 row는 딕셔너리 형태입니다.
                sql = "SELECT * FROM speetto_status ORDER BY speetto_type DESC, round DESC"
                cursor.execute(sql)
                results = cursor.fetchall()
                
                if results:
                    # 모든 행에 대해 향상된 포맷터 적용
                    formatted_results = [format_speetto_status_result(row) for row in results]
                    
                    return app.response_class(
                        response=json.dumps(formatted_results, ensure_ascii=False),
                        status=200,
                        mimetype='application/json'
                    )
                return jsonify({"error": "No data found"}), 404
    except Exception as e:
        # 에러 발생 시 로그를 찍어주면 디버깅이 더 쉬워집니다.
        print(f"Error in /speetto/status: {e}")
        return jsonify({"error": str(e)}), 500

def format_speetto_status_result(row):
    """
    모든 컬럼을 순회하며 JSON 직렬화가 불가능한 객체(datetime, date, decimal)를 변환합니다.
    """
    for key, value in row.items():
        # datetime 또는 date 객체인 경우 ISO 포맷 문자열로 변환
        if isinstance(value, (datetime, date)):
            row[key] = value.isoformat()
        # Decimal 객체인 경우 float으로 변환
        elif isinstance(value, Decimal):
            row[key] = float(value)
    return row


@app.route('/lotto/all', methods=['GET'])
def get_all_lotto():
    """
    모든 로또 회차 데이터를 한 번에 조회
    - 안드로이드 앱에서 초기 실행 시 전체 데이터를 로컬에 저장하기 위한 용도
    - 최신 회차부터 내림차순 정렬
    """
    try:
        with pymysql.connect(**DB_CONFIG) as conn:
            with conn.cursor() as cursor:
                # 모든 회차 정보를 최신순으로 가져옴
                cursor.execute("SELECT * FROM lotto ORDER BY round DESC")
                results = cursor.fetchall()
                
                if results:
                    # 기존에 작성하신 format_lotto_result 함수를 활용하여 데이터 가공
                    formatted_results = [format_lotto_result(row) for row in results]
                    
                    # 한글 깨짐 방지 및 효율적인 전송을 위해 json.dumps 사용
                    return app.response_class(
                        response=json.dumps(formatted_results, ensure_ascii=False),
                        status=200,
                        mimetype='application/json'
                    )
                return jsonify({"error": "No data found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def format_pension_result(row):
    return {
        "round": row["round"],
        "draw_date": row["draw_date"].isoformat(),
        "first_prize": row.get("first_prize"),
        "second_prize": row.get("second_prize"),
        "third_prize": row.get("third_prize"),
        "fourth_prize": row.get("fourth_prize"),
        "fifth_prize": row.get("fifth_prize"),
        "sixth_prize": row.get("sixth_prize"),
        "seventh_prize": row.get("seventh_prize"),
        "bonus": row.get("bonus")
    }

def format_lotto_result(row):
    return {
        "round": row["round"],
        "draw_date": row["draw_date"].isoformat(),
        "numbers": [row["num1"], row["num2"], row["num3"], row["num4"], row["num5"], row["num6"]],
        "bonus": row["bonus"]
    }



#@app.route('/api/interviews', methods=['GET'])
#def get_winner_interviews():
#    """
#    winner_interviews 테이블의 모든 데이터를 조회합니다.
#    - 최신순(id DESC)으로 정렬하여 반환합니다.
#    """
#    try:
#        with pymysql.connect(**DB_CONFIG) as conn:
#            with conn.cursor() as cursor:
#                # 1. 모든 인터뷰 데이터를 최신순으로 조회
#                sql = """
#                    SELECT 
#                        id, 
#                        title, 
#                        lotto_type, 
#                        round_num, 
#                        store_name, 
#                        content, 
#                        created_at 
#                    FROM winner_interviews 
#                    ORDER BY id DESC
#                """
#                cursor.execute(sql)
#                results = cursor.fetchall()
#                
#                if not results:
#                    return jsonify([])
#                
#                # 2. format_speetto_status_result를 사용하여 
#                # created_at(datetime) 객체를 문자열로 변환합니다.
#                formatted_results = [format_speetto_status_result(row) for row in results]
#                
#                # 3. 한글 깨짐 방지를 위해 ensure_ascii=False 설정 후 반환
#                return app.response_class(
#                    response=json.dumps(formatted_results, ensure_ascii=False),
#                    status=200,
#                    mimetype='application/json'
#                )
#                
#    except Exception as e:
#        # 서버 로그에 에러 출력
#        print(f"Error in /api/interviews: {e}")
#        return jsonify({"error": str(e)}), 500


@app.route('/lotto/numbers/all', methods=['GET'])
def get_all_lotto_numbers():
    try:
        with pymysql.connect(**DB_CONFIG) as conn:
            with conn.cursor() as cursor:
                # ✅ 포인트 1: ltEpsd DESC를 통해 최신 회차부터 내림차순 정렬
                sql = "SELECT * FROM lotto_numbers ORDER BY ltEpsd DESC"
                cursor.execute(sql)
                results = cursor.fetchall()
                
                if results:
                    # ✅ 포인트 2: 기존 앱 호환성 + 누락 데이터 처리 포맷터 적용
                    formatted_results = [format_lotto_numbers_result(row) for row in results]
                    
                    return app.response_class(
                        response=json.dumps(formatted_results, ensure_ascii=False),
                        status=200,
                        mimetype='application/json'
                    )
                return jsonify({"error": "No data found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def format_lotto_numbers_result(row):
    # 1. 안드로이드 기존 모델 호환용 필드
    formatted = {
        "round": row["ltEpsd"],
        "draw_date": row["ltRflYmd"].isoformat() if isinstance(row["ltRflYmd"], (date, datetime)) else row["ltRflYmd"],
        "numbers": [row["tm1WnNo"], row["tm2WnNo"], row["tm3WnNo"], row["tm4WnNo"], row["tm5WnNo"], row["tm6WnNo"]],
        "bonus": row["bnsWnNo"]
    }

    # 2. 이월(0명)과 누락(데이터 없음) 판별 로직
    # 모든 주요 수치가 0이면 데이터가 아예 없는 '누락' 회차로 판단합니다.
    is_data_missing = (row.get("rnk1WnAmt", 0) == 0 and 
                       row.get("rnk1WnNope", 0) == 0 and 
                       row.get("wholEpsdSumNtslAmt", 0) == 0)

    # 3. 추가 상세 정보 처리 (누락 시 null 반환)
    detail_keys = {
        "first_prize_amt": "rnk1WnAmt",
        "first_winner_count": "rnk1WnNope",
        "second_prize_amt": "rnk2WnAmt",
        "total_sales": "wholEpsdSumNtslAmt"
    }

    for key, db_col in detail_keys.items():
        val = row.get(db_col, 0)
        if is_data_missing:
            formatted[key] = None # 데이터 자체가 없으면 null
        elif db_col == "rnk1WnNope" and val == 0:
            formatted[key] = 0    # 다른 데이터는 있는데 당첨자만 0이면 '이월'
        else:
            formatted[key] = int(val) if isinstance(val, (int, float, Decimal)) else val
            
    return formatted


@app.route('/lotto/carryover/stats', methods=['GET'])
def get_carryover_stats():
    """이월수 개수별 이론 vs 실제 확률 및 히스토리"""
    try:
        count = request.args.get('count', default=1, type=int)
        include_bonus = request.args.get('includeBonus', default='false').lower() == 'true'
        
        # 이론적 확률 데이터 (상수)
        probs = {
            False: {0: 40.06, 1: 42.41, 2: 14.94, 3: 2.40, 4: 0.18, 5: 0.01, 6: 0.00},
            True:  {0: 27.83, 1: 42.22, 2: 21.01, 3: 7.01, 4: 1.52, 5: 0.15, 6: 0.00}
        }

        with pymysql.connect(**DB_CONFIG) as conn:
            with conn.cursor() as cursor:
                # 1. 실제 발생 빈도 합계 및 특정 개수 조회
                col = "occurrence_with_bonus" if include_bonus else "occurrence_total"
                cursor.execute(f"SELECT SUM({col}) as total FROM lotto_carryover_summary")
                total_sum = cursor.fetchone()['total'] or 0
                
                cursor.execute(f"SELECT {col} as count, updated_at FROM lotto_carryover_summary WHERE match_count = %s", (count,))
                target = cursor.fetchone()
                
                occ_count = target['count'] if target else 0
                actual_prob = round((occ_count / total_sum) * 100, 2) if total_sum > 0 else 0

                # 2. 최근 히스토리 10건
                hist_col = "match_count_with_bonus" if include_bonus else "match_count"
                cursor.execute(f"SELECT round, matched_numbers FROM lotto_carryover_history WHERE {hist_col} = %s ORDER BY round DESC LIMIT 10", (count,))
                history = cursor.fetchall()

                result = {
                    "theoretical_prob": f"{probs[include_bonus].get(count, 0)}%",
                    "actual_prob": f"{actual_prob}%",
                    "history": history,
                    "last_updated": target['updated_at'].isoformat() if target and target['updated_at'] else None
                }
                return app.response_class(json.dumps(result, ensure_ascii=False), mimetype='application/json')
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.route('/lotto/carryover/analysis', methods=['GET'])
def analyze_carryover_candidates():
    """지난주 번호별 이월 성향 및 선택 번호 간 궁합 분석"""
    try:
        # 유저가 선택해본 번호들 (예: ?pick=3,15)
        pick_param = request.args.get('pick')
        picks = [int(x.strip()) for x in pick_param.split(',')] if pick_param else []

        with pymysql.connect(**DB_CONFIG) as conn:
            with conn.cursor() as cursor:
                # 1. 지난주 당첨 번호 가져오기
                cursor.execute("SELECT * FROM lotto_numbers ORDER BY ltEpsd DESC LIMIT 1")
                latest = cursor.fetchone()
                last_week = [latest[f'tm{i}WnNo'] for i in range(1, 7)]
                
                # 2. 지난주 번호 각각의 '이월 파워' 분석
                individual_analysis = []
                for num in last_week:
                    cursor.execute("SELECT COUNT(*) as cnt FROM lotto_carryover_history WHERE FIND_IN_SET(%s, matched_numbers)", (str(num),))
                    carry_cnt = cursor.fetchone()['cnt']
                    individual_analysis.append({"number": num, "total_carry_count": carry_cnt})
                
                # 성적순 정렬
                individual_analysis = sorted(individual_analysis, key=lambda x: x['total_carry_count'], reverse=True)

                # 3. 궁합(Chemistry) 분석: 선택된 번호들이 동시에 이월된 적이 있는가?
                chemistry = None
                if len(picks) >= 2:
                    where_clause = " AND ".join([f"FIND_IN_SET('{p}', matched_numbers)" for p in picks])
                    cursor.execute(f"SELECT round, matched_numbers FROM lotto_carryover_history WHERE {where_clause}")
                    co_occur = cursor.fetchall()
                    chemistry = {
                        "pair": picks,
                        "co_occurrence_count": len(co_occur),
                        "common_history": co_occur,
                        "evaluation": "🔥 찰떡궁합" if len(co_occur) >= 3 else "❄️ 생소한 조합"
                    }

                result = {
                    "last_round": latest['ltEpsd'],
                    "individual_power": individual_analysis,
                    "synergy": chemistry
                }
                return app.response_class(json.dumps(result, ensure_ascii=False), mimetype='application/json')
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/promotions', methods=['GET'])
def get_promotions():
    try:
        # ✅ get_db_connection() 대신 다른 코드들처럼 DB_CONFIG를 직접 사용합니다.
        with pymysql.connect(**DB_CONFIG) as conn:
            with conn.cursor() as cursor:
                sql = """
                    SELECT 
                        icon, 
                        title, 
                        description, 
                        target_url 
                    FROM promotions 
                    WHERE is_active = 1 
                    ORDER BY priority ASC, id DESC
                """
                cursor.execute(sql)
                results = cursor.fetchall()
                
                if not results:
                    return jsonify([])
                
                # ✅ 중요: 날짜나 소수점 데이터가 있을 수 있으므로 직렬화 가공을 거칩니다.
                formatted_results = [format_speetto_status_result(row) for row in results]
                
                return app.response_class(
                    response=json.dumps(formatted_results, ensure_ascii=False),
                    status=200,
                    mimetype='application/json'
                )
                
    except Exception as e:
        # 에러 메시지를 확인하기 위해 로그 출력
        print(f"Error in /api/promotions: {e}")
        return jsonify({"error": str(e)}), 500


# ✅ 헬스 체크
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "working", "timestamp": datetime.now().isoformat()}), 200

if __name__ == '__main__':
    # host='0.0.0.0'은 외부(로드 밸런서)의 접근을 허용한다는 뜻입니다.
    app.run(host='0.0.0.0', port=5000)