import requests
import pymysql
import re
import urllib.parse
from datetime import datetime

# --- DB 설정 ---
DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "admin",
    "password": "chaerin",
    "database": "lottery_app",
    "charset": "utf8mb4",
    "autocommit": True
}

def parse_prize(prize_str):
    """상금 문자열을 숫자로 변환. 값이 없거나 매칭되지 않으면 None(NULL) 반환."""
    if not prize_str or str(prize_str).lower() == 'none' or str(prize_str).strip() == "":
        return None
    
    prize_str = str(prize_str).replace(",", "").strip()
    val = 0
    matched = False

    # 단위별 가중치 (큰 단위부터 체크)
    units = [
        ('억', 100000000),
        ('천만', 10000000),
        ('백만', 1000000),
        ('만', 10000),
        ('천', 1000)
    ]

    temp_str = prize_str
    for unit, multiplier in units:
        if unit in temp_str:
            m = re.search(rf'(\d+){unit}', temp_str)
            if m:
                val += int(m.group(1)) * multiplier
                temp_str = temp_str.replace(m.group(0), '')
                matched = True

    # 단위 없이 숫자만 있는 경우 처리 (예: "500")
    digits = re.sub(r'[^0-9]', '', temp_str)
    if digits:
        val += int(digits)
        matched = True

    return val if matched else None

def to_int_or_none(val):
    """일반 숫자 필드(회차, 수량 등)가 비어있으면 None(NULL) 반환."""
    if val is None or str(val).strip() == "":
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None

def format_date(date_str):
    if not date_str: return None
    date_str = str(date_str).strip()
    try:
        if len(date_str) == 8:
            return datetime.strptime(date_str, "%y-%m-%d").strftime("%Y-%m-%d")
        return date_str
    except:
        return date_str

def encode_url_safe(path):
    if not path: return ""
    base_domain = "https://www.dhlottery.co.kr/winImages"
    safe_path = urllib.parse.quote(path)
    return f"{base_domain}{safe_path}"

def sync_speetto_status():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://www.dhlottery.co.kr/st/pblcnDsctn"
    })

    try:
        print("1️⃣ 판매중인 스피또 목록 수집 중...")
        list_url = "https://www.dhlottery.co.kr/st/selectPblcnDsctn.do"
        payload = {"gdsType": "", "gdsPrice": "", "gdsStatus": "판매중"}
        
        list_res = session.get(list_url, params=payload, timeout=10)
        list_data = list_res.json()
        
        items = list_data.get('data', {}).get('list', [])
        
        if not items:
            print("❌ 수집된 목록이 없습니다. 응답 구조를 확인하세요.")
            return

        print(f"✅ 총 {len(items)}개의 스피또 발견. 상세 데이터 수집 시작...")

        conn = pymysql.connect(**DB_CONFIG)
        cur = conn.cursor()

        for item in items:
            sn = item.get('ntslWnSn')
            detail_url = f"https://www.dhlottery.co.kr/st/selectPblcnDsctnDtl.do?ntslWnSn={sn}"
            detail_res = session.get(detail_url, timeout=10)
            data = detail_res.json().get('data', {}).get('result', {})

            if not data:
                print(f"⚠️ {sn} 상세 데이터 수집 실패")
                continue

            speetto_name = data.get("stGmTypeNm", "")
            
            # ✅ 종류별 최대 등수 설정
            if "2000" in speetto_name:
                max_rank = 6
            elif "1000" in speetto_name:
                max_rank = 5
            elif "500" in speetto_name:
                max_rank = 4
            else:
                max_rank = 6 # 기본값

            mapped_data = {
                "speetto_type": speetto_name,
                "round": to_int_or_none(data.get("stEpsd")),
                "sales_end_date": data.get("stNtslEndDt"),
                "publish_qty": to_int_or_none(data.get("pblcnQty")),
                "stocking_rate": data.get("stSpmtRt"),
                "image_source": encode_url_safe(data.get("tm1StWnImgStrgPathNm")),
                "data_chg_dt": format_date(data.get("dataChgDt"))
            }

            # ✅ 1~6등 매핑 (종류별 등수 제한 적용)
            for i in range(1, 7):
                if i <= max_rank:
                    mapped_data[f"rank{i}_prize"] = parse_prize(data.get(f"stRnk{i}GdsLstcCharCn"))
                    mapped_data[f"rank{i}_total_count"] = to_int_or_none(data.get(f"stRnk{i}WnQty"))
                    mapped_data[f"rank{i}_left_count"] = to_int_or_none(data.get(f"stIvtRnk{i}Qty"))
                else:
                    # ✅ 해당 등수가 없는 경우 명시적으로 None(NULL) 처리
                    mapped_data[f"rank{i}_prize"] = None
                    mapped_data[f"rank{i}_total_count"] = None
                    mapped_data[f"rank{i}_left_count"] = None

            # SQL 작성 및 실행
            cols = ', '.join(mapped_data.keys())
            vals = ', '.join(['%s'] * len(mapped_data))
            updates = ', '.join([f"{k}=VALUES({k})" for k in mapped_data.keys() if k not in ['speetto_type', 'round']])
            
            sql = f"INSERT INTO speetto_status ({cols}) VALUES ({vals}) ON DUPLICATE KEY UPDATE {updates}"
            cur.execute(sql, list(mapped_data.values()))
            
            print(f"   ∟ 업데이트 완료: {mapped_data['speetto_type']} {mapped_data['round']}회")

        conn.close()
        print("\n🎯 모든 데이터가 종류별 등수 제한을 포함하여 성공적으로 업데이트되었습니다.")

    except Exception as e:
        print(f"❌ 오류 발생: {e}")

if __name__ == "__main__":
    sync_speetto_status()