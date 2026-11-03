# 临时校验：计划态必填/合法性校验（游泳缺主泳姿、非法泳姿；舞蹈缺星级）应被拒绝；合法计划可创建。
import json
import urllib.parse
import urllib.request
from datetime import date
from http.cookiejar import CookieJar

BASE = "http://127.0.0.1:8010"
USERNAME, PASSWORD = "admin", "admin123"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def main():
    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), NoRedirect())
    data = urllib.parse.urlencode({"username": USERNAME, "password": PASSWORD}).encode()
    try:
        opener.open(BASE + "/login", data=data)
    except urllib.error.HTTPError as e:
        if e.code != 303:
            raise
    today = date.today().isoformat()

    def post(path, body):
        req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with opener.open(req) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    cases = [
        ("swim 计划缺主泳姿应 400",
         "/api/swim-records", {"record_date": today, "status": "planned", "distance_m": 1000, "duration_s": 1800},
         None, "主泳姿"),
        ("swim 非法主泳姿应 400",
         "/api/swim-records", {"record_date": today, "status": "planned", "distance_m": 1000, "duration_s": 1800, "main_stroke": "doggy"},
         None, "主泳姿不合法"),
        ("swim 计划合法应 2xx",
         "/api/swim-records", {"record_date": today, "status": "planned", "distance_m": 1000, "duration_s": 1800, "main_stroke": "freestyle", "remark": "校验备注"},
         True, None),
        ("dance 计划缺星级应 400",
         "/api/dance-records", {"record_date": today, "status": "planned", "dance_type": "爵士"},
         None, "舞种与星级"),
        ("dance 计划合法应 2xx",
         "/api/dance-records", {"record_date": today, "status": "planned", "dance_type": "爵士", "stars": 4, "remark": "校验备注"},
         True, None),
    ]
    cleanup = []
    failed = 0
    for name, path, body, expect_ok, hint in cases:
        code, text = post(path, body)
        if expect_ok is True:
            ok = 200 <= code < 300
            if ok:
                try:
                    rid = json.loads(text).get("id")
                    if rid:
                        cleanup.append((path, rid))
                except Exception:
                    pass
        else:
            ok = code == 400 and (hint in text or hint in json.dumps(text, ensure_ascii=False))
        print(("  ✔ " if ok else "  ✘ ") + name + f"  [{code}] {text[:80]}")
        if not ok:
            failed += 1
    for path, rid in cleanup:
        req = urllib.request.Request(BASE + path + "/" + str(rid), method="DELETE")
        try:
            opener.open(req)
        except Exception:
            pass
    print("结果：", "通过" if failed == 0 else f"失败 {failed}", f"{len(cases) - failed}/{len(cases)}")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
