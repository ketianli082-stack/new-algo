"""BAS-001 只读 ALGOGENE API 联通性诊断。

只请求 /get_current_tasks，不会创建 backtest、不会发送订单。
输出和 Artifact 不包含任何密钥；仅输出响应码、响应类型、脱敏短摘要。
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path("outputs/bas001/api-diagnostic.json")


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    user = os.environ.get("ALGOGENE_USER_ID", "").strip()
    key = os.environ.get("ALGOGENE_API_KEY", "").strip()
    report = {"mode": "read_only", "endpoint": "/get_current_tasks",
              "credentials_present": bool(user and key), "status": "UNKNOWN"}

    def save():
        OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if not user or not key:
        report.update(status="MISSING_SECRETS")
        save()
        return 1

    params = urllib.parse.urlencode({"user": user, "api_key": key})
    req = urllib.request.Request(
        "https://algogene.com/rest/v1/get_current_tasks?" + params,
        method="GET", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            raw = response.read(10000).decode("utf-8", errors="replace")
            report["http_status"] = response.status
        # Do not save any raw response; account data may be private.
        obj = json.loads(raw)
        report["response_is_object"] = isinstance(obj, dict)
        if isinstance(obj, dict):
            report["api_status"] = obj.get("status") if isinstance(obj.get("status"), bool) else None
            report["res_type"] = type(obj.get("res")).__name__
            report["has_active_tasks"] = bool(obj.get("res")) if isinstance(obj.get("res"), list) else None
        report["status"] = "SUCCESS" if report.get("api_status") is True else "API_REJECTED"
    except urllib.error.HTTPError as e:
        report.update(status="HTTP_ERROR", http_status=e.code,
                      retry_after_present=bool(e.headers.get("Retry-After")))
    except urllib.error.URLError as e:
        report.update(status="NETWORK_ERROR", exception_type=type(e.reason).__name__)
    except Exception as e:
        report.update(status="OTHER_ERROR", exception_type=type(e).__name__)
    save()
    print("BAS001 READONLY API DIAGNOSTIC", report["status"],
          "HTTP", report.get("http_status"), flush=True)
    return 0 if report["status"] == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
