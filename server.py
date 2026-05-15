#!/usr/bin/env python3
import csv
import json
import os
import subprocess
import urllib.parse
from datetime import date, datetime, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill


ROOT = Path(__file__).resolve().parent
STATIC_ROOT = ROOT / "static"

JAVA = "/Library/Java/JavaVirtualMachines/jdk1.8.0_251.jdk/Contents/Home/jre/bin/java"
JAVAC = "/Library/Java/JavaVirtualMachines/jdk1.8.0_251.jdk/Contents/Home/bin/javac"
JAVA_CP = f"{ROOT}:/Library/EPBrowser/EPB/Shell/lib/*:/Library/EPBrowser/EPB/Shell/shell.jar"

ORG_ID = "01"
DEFAULT_STORE = "SA004"
MAX_PURCHASE_ROWS = 1000

# 固定篩選條件（已比對使用者系統匯出檔逐筆吻合）
# 800AB「出入庫代碼 INVTRNIN 調撥入庫」對應 STOREDTL：
#   STORE_ID = 我方倉（收貨）、TO_STORE_ID = 來源倉、
#   SRC_CODE = 'INVTRNTN'（存貨調撥入庫單）、MOVE_FLG = 'I'（入庫方向）
FIXED_SRC_CODE = "INVTRNTN"     # 出入庫代碼 INVTRNIN 對應的來源單別
FIXED_MOVE_FLG = "I"            # 只取實際入庫線
FIXED_SOURCE_STORE = "SA099"    # 來源倉鎖死＝總公司倉
FIXED_CAT1 = ["1003", "1001"]   # 類別1 包括 1003 / 1001
FIXED_CAT2 = "2001"             # 類別2 = 2001 APL原廠
FIXED_CAT3 = "3001"             # 類別3 = 3001 APL主機


def json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def quote_sql(value):
    return "'" + str(value).replace("'", "''") + "'"


def in_clause(expr, values):
    return f"{expr} in ({','.join(quote_sql(v) for v in values)})"


def parse_date(value, fallback):
    if not value:
        return fallback
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def text(value):
    return "" if value is None else str(value).strip()


def number(value):
    if value in (None, ""):
        return 0.0
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return 0.0


def compile_java(source_name):
    source = ROOT / source_name
    target = ROOT / source_name.replace(".java", ".class")
    if target.exists() and target.stat().st_mtime >= source.stat().st_mtime:
        return
    proc = subprocess.run(
        [JAVAC, "-cp", JAVA_CP, str(source)],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())


def run_remote(sql, timeout=180):
    compile_java("EPBReportQuery.java")
    proc = subprocess.run(
        [
            JAVA,
            "-Dsun.net.client.defaultConnectTimeout=5000",
            "-Dsun.net.client.defaultReadTimeout=120000",
            "-cp",
            JAVA_CP,
            "EPBReportQuery",
            sql,
        ],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip())
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    if not lines:
        return [], []
    reader = csv.reader(lines, delimiter="\t")
    rows = list(reader)
    return rows[0], rows[1:]


def list_stores():
    sql = f"""
select store_id, name
from storemas
where org_id = {quote_sql(ORG_ID)}
  and status_flg = 'A'
  and store_id like 'SA%'
order by store_id
"""
    headers, rows = run_remote(sql)
    items = []
    for row in rows:
        rec = {headers[i].upper(): row[i] for i in range(len(headers))}
        store_id = text(rec.get("STORE_ID"))
        if store_id:
            items.append({"storeId": store_id, "name": text(rec.get("NAME"))})
    return {"items": items, "defaultStore": DEFAULT_STORE}


def build_purchase_sql(payload):
    today = date.today()
    start = parse_date(payload.get("startDate"), today)
    end = parse_date(payload.get("endDate"), today)
    if end < start:
        raise ValueError("結束日不可早於起始日")
    end_plus = end + timedelta(days=1)
    store_id1 = text(payload.get("storeId1"))

    conditions = [
        f"i.org_id = {quote_sql(ORG_ID)}",
        f"i.src_code = {quote_sql(FIXED_SRC_CODE)}",
        f"i.move_flg = {quote_sql(FIXED_MOVE_FLG)}",
        f"i.to_store_id = {quote_sql(FIXED_SOURCE_STORE)}",
        f"i.doc_date >= to_date({quote_sql(start.isoformat())}, 'yyyy-mm-dd')",
        f"i.doc_date < to_date({quote_sql(end_plus.isoformat())}, 'yyyy-mm-dd')",
        in_clause("i.cat1_id", FIXED_CAT1),
        f"i.cat2_id = {quote_sql(FIXED_CAT2)}",
        f"i.cat3_id = {quote_sql(FIXED_CAT3)}",
    ]
    if store_id1:
        conditions.append(f"i.store_id = {quote_sql(store_id1)}")

    where_sql = " and ".join(conditions)
    sql = f"""
select *
from (
  select
    i.doc_date,
    i.src_doc_id as doc_id,
    i.to_store_id as src_store_id,
    s.name as src_store_name,
    i.brand_id, i.stk_id, i.stk_name, i.model, i.stk_qty
  from storedtl i
  left join storemas s on s.store_id = i.to_store_id and s.org_id = i.org_id
  where {where_sql}
  order by i.doc_date, i.src_doc_id, i.stk_id
)
where rownum <= {MAX_PURCHASE_ROWS}
"""
    return sql, {"start": start, "end": end, "storeId1": store_id1}


def query_purchase(payload):
    sql, meta = build_purchase_sql(payload)
    headers, rows = run_remote(sql)
    items = []
    for row in rows:
        rec = {headers[i].upper(): row[i] for i in range(len(headers))}
        src_id = text(rec.get("SRC_STORE_ID"))
        src_name = text(rec.get("SRC_STORE_NAME"))
        items.append(
            {
                "docDate": text(rec.get("DOC_DATE"))[:10],
                "docId": text(rec.get("DOC_ID")),
                "brandId": text(rec.get("BRAND_ID")),
                "sourceStore": f"{src_id} {src_name}".strip() if src_id else src_name,
                "stkId": text(rec.get("STK_ID")),
                "model": text(rec.get("MODEL")),
                "name": text(rec.get("STK_NAME")),
                "stkQty": text(rec.get("STK_QTY")),
            }
        )
    return {
        "items": items,
        "rowCount": len(items),
        "limit": MAX_PURCHASE_ROWS,
        "meta": {
            "start": meta["start"].isoformat(),
            "end": meta["end"].isoformat(),
            "storeId1": meta["storeId1"],
        },
    }


def export_purchase(payload):
    result = query_purchase(payload)
    items = result["items"]
    meta = result["meta"]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "門市進貨查詢"

    title_font = Font(name="Arial", size=14, bold=True)
    head_font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
    body_font = Font(name="Arial", size=11)
    head_fill = PatternFill("solid", fgColor="2F5597")
    center = Alignment(horizontal="center", vertical="center")

    ws["A1"] = "門市進貨查詢（調撥入庫 INVTRNIN｜APL主機）"
    ws["A1"].font = title_font
    ws.merge_cells("A1:H1")
    ws["A1"].alignment = center

    cond = f"日期 {meta['start']} ~ {meta['end']}"
    if meta["storeId1"]:
        cond += f"｜我方倉 {meta['storeId1']}"
    cond += f"｜共 {result['rowCount']} 筆"
    ws["A2"] = cond
    ws["A2"].font = body_font
    ws.merge_cells("A2:H2")

    columns = ["單據日期", "來源單據代碼", "品牌代碼", "存貨代碼", "型號", "存貨名稱", "存貨數量", "來源倉"]
    for col, label in enumerate(columns, start=1):
        cell = ws.cell(row=4, column=col, value=label)
        cell.font = head_font
        cell.fill = head_fill
        cell.alignment = center

    for idx, item in enumerate(items, start=5):
        values = [
            item["docDate"],
            item["docId"],
            item["brandId"],
            item["stkId"],
            item["model"],
            item["name"],
            number(item["stkQty"]),
            item["sourceStore"],
        ]
        for col, value in enumerate(values, start=1):
            ws.cell(row=idx, column=col, value=value).font = body_font

    widths = [12, 18, 12, 16, 18, 36, 10, 20]
    for col, width in enumerate(widths, start=1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = width
    ws.freeze_panes = "A5"

    stream = BytesIO()
    wb.save(stream)
    stream.seek(0)
    store_tag = meta["storeId1"] or "ALL"
    filename = f"門市進貨查詢_{store_tag}_{meta['start']}~{meta['end']}.xlsx"
    return filename, stream.getvalue()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False, default=json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_xlsx(self, filename, body):
        quoted_name = urllib.parse.quote(filename)
        self.send_response(200)
        self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quoted_name}")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_payload(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        return json.loads(raw or "{}")

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/api/stores":
                self.send_json(200, list_stores())
                return
        except Exception as exc:
            self.send_json(500, {"ok": False, "error": str(exc)})
            return
        super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        try:
            payload = self.read_payload()
            if parsed.path == "/api/purchase":
                self.send_json(200, query_purchase(payload))
                return
            if parsed.path == "/api/purchase/export":
                filename, body = export_purchase(payload)
                self.send_xlsx(filename, body)
                return
        except Exception as exc:
            self.send_json(500, {"ok": False, "error": str(exc)})
            return
        self.send_json(404, {"ok": False, "error": "Not found"})


def main():
    compile_java("EPBReportQuery.java")
    port = int(os.environ.get("PORT", "8781"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Purchase Live Query App: http://127.0.0.1:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
