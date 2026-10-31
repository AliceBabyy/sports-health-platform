"""冒烟测试：登录 + 五模块页面 + 核心 /api 主链路。

前置：服务已启动（uvicorn main:app --port 8010）。
用法：python scripts/smoke_test.py [base_url]  默认 http://127.0.0.1:8010
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
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
    code, text = req("POST", "/api/body-metrics", {"record_date": today, "values": {"weight": 60.0}})
    check("POST /api/body-metrics upsert", code == 200, f"code={code}")

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

    print(f"\n结果：通过 {passed} / {passed + failed}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
