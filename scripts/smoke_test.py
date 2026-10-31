"""冒烟测试：登录 + 五模块页面 + 核心 /api 主链路。

前置：服务已启动（uvicorn main:app --port 8010）。
用法：python scripts/smoke_test.py [base_url]  默认 http://127.0.0.1:8010
"""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from http.cookiejar import CookieJar
from pathlib import Path

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010"
USERNAME, PASSWORD = "admin", "admin123"

passed = 0
failed = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  ✔ {name}")
    else:
        failed += 1
        print(f"  ✘ {name}  {detail}")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """不跟随 3xx，直接返回重定向状态码，便于断言 303。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main() -> None:
    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    login_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), NoRedirect())
    no_redirect = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()), NoRedirect())

    def req(method: str, path: str, body=None, headers=None) -> tuple[int, str]:
        data = json.dumps(body).encode() if body is not None else None
        h = {"Content-Type": "application/json"}
        if headers:
            h.update(headers)
        r = urllib.request.Request(BASE + path, data=data, method=method, headers=h)
        try:
            with opener.open(r, timeout=15) as resp:
                return resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            return -1, str(e)

    print("== 认证 ==")
    code, _ = req("GET", "/login")
    check("GET /login 可访问", code == 200, f"got {code}")
    data = urllib.parse.urlencode({"username": USERNAME, "password": PASSWORD}).encode()
    r = urllib.request.Request(BASE + "/login", data=data, method="POST")
    try:
        with login_opener.open(r, timeout=15) as resp:
            login_code, login_loc = resp.status, resp.headers.get("Location", "")
    except urllib.error.HTTPError as e:
        login_code, login_loc = e.code, e.headers.get("Location", "")
    check("POST /login 登录成功并跳转", login_code == 303 and login_loc == "/body", f"code={login_code} loc={login_loc}")

    print("== 五模块页面 ==")
    for path, marker in [
        ("/body", "身材数据"),
        ("/training", "健身训练"),
        ("/swim", "游泳记录"),
        ("/dance", "舞蹈记录"),
        ("/cycle", "生理周期"),
    ]:
        code, html = req("GET", path)
        check(f"GET {path} 200 且含页面标记", code == 200 and marker in html, f"code={code}")

    print("== 未登录拦截 ==")
    jar2 = CookieJar()
    opener2 = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar2), NoRedirect())
    try:
        with opener2.open(BASE + "/body", timeout=15) as resp:
            guard_code = resp.status
    except urllib.error.HTTPError as e:
        guard_code = e.code
    check("未登录访问业务页被拦截(303)", guard_code == 303, f"got {guard_code}")

    print("== 注册链路（新用户，基础信息） ==")
    suffix = str(int(time.time()))[-6:]
    reg_user = "smokereg" + suffix
    reg_body = urllib.parse.urlencode({
        "username": reg_user, "password": "pass1234",
        "display_name": "冒烟注册", "gender": "女", "age": "28",
    }).encode()
    jar3 = CookieJar()
    reg_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar3), NoRedirect())
    r = urllib.request.Request(BASE + "/register", data=reg_body, method="POST")
    try:
        with reg_opener.open(r, timeout=15) as resp:
            reg_code, reg_loc = resp.status, resp.headers.get("Location", "")
    except urllib.error.HTTPError as e:
        reg_code, reg_loc = e.code, e.headers.get("Location", "")
    check("POST /register 注册成功并跳转 /body", reg_code == 303 and reg_loc == "/body", f"code={reg_code} loc={reg_loc}")
    try:
        with reg_opener.open(BASE + "/body", timeout=15) as resp:
            reg_body_page = resp.status
    except urllib.error.HTTPError as e:
        reg_body_page = e.code
    check("注册用户会话可直接访问 /body", reg_body_page == 200, f"code={reg_body_page}")

    print("== 核心 API ==")
    code, text = req("GET", "/api/body-metrics/latest")
    ok = code == 200 and "bmi" in text
    check("GET /api/body-metrics/latest", ok, f"code={code}")

    code, _ = req("GET", "/api/body-metrics/trend?metric=weight&range=month")
    check("GET /api/body-metrics/trend", code == 200, f"code={code}")

    code, text = req("GET", "/api/swim-records/stats")
    check("GET /api/swim-records/stats", code == 200, f"code={code}")

    code, text = req("GET", "/api/dance-records/stats")
    check("GET /api/dance-records/stats", code == 200, f"code={code}")

    today = date.today().isoformat()
    code, _ = req("GET", "/api/cycle/calendar?month=" + today[:7])
    check("GET /api/cycle/calendar", code == 200, f"code={code}")

    code, text = req("GET", "/api/training/plans/" + today)
    check("GET /api/training/plans/{date}", code == 200, f"code={code}")

    print("== 写链路（临时数据，测后即删） ==")
    # 4 表拆分：分 4 组写入（昨日基础只填体重 → 今日身高应继承昨日体重所在行的身高？不，
    # 继承按字段回溯：今日只填身高，体重应沿用昨日的体重）
    day1 = (date.today() - timedelta(days=1)).isoformat()
    code, _ = req("POST", "/api/body-metrics/basic", {
        "record_date": day1,
        "values": {"weight": 60.0},
    })
    check("POST /api/body-metrics/basic（昨日仅体重）", code == 200, f"code={code}")
    code, _ = req("POST", "/api/body-metrics/basic", {
        "record_date": today,
        "values": {"height": 165.0},
    })
    check("POST /api/body-metrics/basic（今日仅身高）", code == 200, f"code={code}")
    code, text = req("GET", "/api/body-metrics/latest")
    ok = code == 200 and '"weight"' in text and '"height"' in text and "bmi" in text
    check("GET /api/body-metrics/latest 合并 4 组字段", ok, f"code={code}")
    try:
        payload = json.loads(text)
        inherited_ok = payload.get("weight", {}).get("value") == 60.0 and payload.get("height", {}).get("value") == 165.0
        bmi_ok = payload.get("bmi") is not None
    except Exception:  # noqa: BLE001
        inherited_ok = bmi_ok = False
    check("未填字段继承最近值（体重=60 沿用）且 BMI 可算", inherited_ok and bmi_ok, f"text={text[:200]}")

    code, _ = req("POST", "/api/body-metrics/goal", {
        "record_date": today,
        "values": {"target_weight": 55.0, "target_body_fat": 20.0},
    })
    check("POST /api/body-metrics/goal", code == 200, f"code={code}")
    code, _ = req("POST", "/api/body-metrics/girth", {
        "record_date": today,
        "values": {"waist": 68.0, "chest": 88.0, "arm": 30.0, "hip": 92.0},
    })
    check("POST /api/body-metrics/girth", code == 200, f"code={code}")
    code, _ = req("POST", "/api/body-metrics/target", {
        "record_date": today,
        "values": {"target_waist": 65.0},
    })
    check("POST /api/body-metrics/target", code == 200, f"code={code}")

    code, _ = req("POST", "/api/body-metrics/basic", {
        "record_date": today,
        "values": {"waist": 99.0},
    })
    check("POST /api/body-metrics/basic 拒绝不属于该组的字段", code == 400, f"code={code}")

    code, text = req("GET", "/api/body-metrics/latest")
    ok = code == 200 and '"target_weight"' in text and '"target_waist"' in text and '"waist"' in text
    check("GET /api/body-metrics/latest 含目标与围度字段", ok, f"code={code}")

    code, text = req("GET", "/api/body-metrics")
    ok = code == 200 and '"total"' in text
    check("GET /api/body-metrics 列表（按日期合并）", ok, f"code={code}")

    code, _ = req("GET", "/api/body-metrics/trend?metric=body_fat&range=month")
    check("GET /api/body-metrics/trend(非 weight 指标)", code == 200, f"code={code}")
    code, _ = req("GET", "/api/body-metrics/trend?metric=target_weight&range=month")
    check("GET /api/body-metrics/trend 拒绝目标值", code == 400, f"code={code}")

    code, text = req("POST", "/api/training/plans/" + today, {
        "items": [
            {"exercise_name": "深蹲", "body_part": None, "weight_kg": None, "sets": None, "reps": None,
             "target_weight_kg": 65.0, "checked": False},
            {"exercise_name": "卧推", "body_part": "胸", "weight_kg": 40.0, "sets": 3, "reps": "10+8+6",
             "target_weight_kg": None, "checked": False},
        ]
    })
    check("POST /api/training/plans 计划（可空字段+reps字符串）", code == 200, f"code={code}")
    code, text = req("GET", "/api/training/plans/" + today)
    item_reps_ok = False
    body_part_null_ok = False
    try:
        payload = json.loads(text)
        items = (payload.get("plan") or {}).get("items") or []
        for it in items:
            if it.get("exercise_name") == "卧推" and it.get("reps") == "10+8+6":
                item_reps_ok = True
            if it.get("exercise_name") == "深蹲" and it.get("body_part") is None and it.get("weight_kg") is None:
                body_part_null_ok = True
    except Exception:  # noqa: BLE001
        pass
    check("GET /api/training/plans reps 原样返回且可空字段为 null", code == 200 and item_reps_ok and body_part_null_ok, f"code={code}")
    code, _ = req("DELETE", "/api/training/plans/" + today)
    check("DELETE /api/training/plans", code == 200, f"code={code}")

    code, text = req("POST", "/api/swim-records", {
        "record_date": today, "distance_m": 500, "duration_s": 660,
        "avg_heart_rate": 130, "total_strokes": 300, "main_stroke": "freestyle", "laps": 10, "calories": 200,
    })
    check("POST /api/swim-records", code == 200, f"code={code}")
    swim_id = json.loads(text).get("id") if code == 200 else None

    code, text = req("POST", "/api/dance-records", {
        "record_date": today, "dance_type": "爵士", "stars": 4, "style": "测试",
        "duration_s": 600, "avg_heart_rate": 120, "max_heart_rate": 150, "calories": 300,
    })
    check("POST /api/dance-records", code == 200, f"code={code}")
    dance_id = json.loads(text).get("id") if code == 200 else None

    # 清理
    if swim_id:
        code, _ = req("DELETE", f"/api/swim-records/{swim_id}")
        check("DELETE /api/swim-records", code == 200, f"code={code}")
    if dance_id:
        code, _ = req("DELETE", f"/api/dance-records/{dance_id}")
        check("DELETE /api/dance-records", code == 200, f"code={code}")
    code, _ = req("DELETE", "/api/body-metrics?record_date=" + today)
    check("DELETE /api/body-metrics(按日)", code == 200, f"code={code}")
    code, _ = req("DELETE", "/api/body-metrics?record_date=" + day1)
    check("DELETE /api/body-metrics(按日·昨日)", code == 200, f"code={code}")

    print(f"\n结果：通过 {passed} / {passed + failed}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
