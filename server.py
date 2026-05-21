#!/usr/bin/env python3
import csv
import json
import os
import subprocess
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
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

# 門市調撥工具：固定 32 個門市倉，與 static/transfer.html 同步
KNOWN_STORE_WAREHOUSES = {
    "大立倉", "士林倉", "微風倉", "永和倉", "台南西門倉", "美麗華倉",
    "板橋誠品倉", "夢時代倉", "彩虹台中倉", "新竹遠百倉", "新竹光復倉",
    "中壢大江倉", "高雄三多門市", "阿波羅倉", "台中金典倉", "新竹中正倉",
    "新西門倉", "台中中科倉", "台中精誠倉", "桃園台茂倉", "大葉高島屋倉",
    "花蓮門市倉", "羅東門市倉", "苗栗尚順門市倉", "桃園統領門市倉",
    "台中豐原門市倉", "板橋遠百門市倉", "新莊宏匯門市倉", "竹北遠百門市倉",
    "台中麗寶門市倉", "岡山秀泰門市倉", "新店裕隆城門市倉",
}
TRANSFER_MIN_DONOR_QTY = 3       # 來源倉庫存門檻：≥ 3 才能當捐贈方
TRANSFER_MAX_TARGET_QTY = 1      # 目標門市庫存 ≤ 1 才需要調撥
TRANSFER_STEP_FILLS = [
    "EAF3FF", "EAF7EA", "FFF4DA", "FCEBF3",
    "ECEBFF", "E8F6F7", "F4F1EA", "F0F6E8",
]

# 主機類別快速按鈕對應 cat4_id
TRANSFER_CAT4_PRESETS = {
    "CPU":    ["4001", "4002"],     # Mac mini + iMac、MacBook
    "iPhone": ["4004"],
    "iPad":   ["4005", "4006", "4041"],  # Air/Standard、mini、Pro
    "Watch":  ["4038"],
}
TRANSFER_VALID_CAT4 = {c for codes in TRANSFER_CAT4_PRESETS.values() for c in codes}
TRANSFER_TAG_PRIMARY = "primary"
TRANSFER_TAG_COMPANION = "companion"


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


def run_remote(sql, timeout=180, read_timeout_ms=120000):
    compile_java("EPBReportQuery.java")
    proc = subprocess.run(
        [
            JAVA,
            "-Dsun.net.client.defaultConnectTimeout=5000",
            f"-Dsun.net.client.defaultReadTimeout={read_timeout_ms}",
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


def model_from_name(name):
    """從『存貨名稱』取出第一個空白前的字串當型號（同 transfer.html 規則）。"""
    value = text(name)
    return value.split()[0] if value else ""


_TRANSFER_STORE_CACHE = {"items": None, "expires": 0.0}
TRANSFER_STORE_CACHE_TTL = 1800   # 門市清單快取 30 分鐘（清單極少變動）


def list_transfer_stores():
    """回傳本工具會用的門市倉清單：[{storeId, name}, ...]，依 store_id 排序。
    結果快取於記憶體，避免每次分析都重新打一次 EPB（省一次 JVM 冷啟動）。"""
    now = time.time()
    if _TRANSFER_STORE_CACHE["items"] is not None and now < _TRANSFER_STORE_CACHE["expires"]:
        items = _TRANSFER_STORE_CACHE["items"]
    else:
        sql = f"""
select store_id, name
from storemas
where org_id = {quote_sql(ORG_ID)}
  and status_flg = 'A'
order by store_id
"""
        headers, rows = run_remote(sql)
        items = []
        for row in rows:
            rec = {headers[i].upper(): row[i] for i in range(len(headers))}
            name = text(rec.get("NAME"))
            if name in KNOWN_STORE_WAREHOUSES:
                items.append({"storeId": text(rec.get("STORE_ID")), "name": name})
        _TRANSFER_STORE_CACHE["items"] = items
        _TRANSFER_STORE_CACHE["expires"] = now + TRANSFER_STORE_CACHE_TTL
    return {
        "items": items,
        "defaultStore": DEFAULT_STORE,
        "cat4Presets": TRANSFER_CAT4_PRESETS,
    }


# 資料來源：140EB STORESUM「存貨彙總」的 STORESUM 表（與 EPB 報表同一份）。
# 效能：STORESUM 跨多店查很慢，但「單店走索引」很快；
# 因此把門市切成小批、用多執行緒平行查（各自獨立 JVM 子行程）。
# 並行度刻意壓在 6：使用者常同時開著 EPB Enterprise Browser（也是 Java），
# 8 個冷查 JVM 容易吃光記憶體導致某批失敗；6 個一波（32 家 ÷ 每批 6 = 6 批）較穩。
TRANSFER_FETCH_BATCH = 6            # 每批查幾家門市（32 家 → 6 批）
TRANSFER_MAX_WORKERS = 6           # 平行查詢的最大執行緒（壓低以與 Enterprise Browser 共存）
TRANSFER_BATCH_RETRIES = 2         # 單批失敗時的額外重試次數
TRANSFER_RETRY_BACKOFF = 2.0       # 重試前等待秒數
TRANSFER_READ_TIMEOUT_MS = 300000   # 單次 SOAP read timeout：5 分鐘
TRANSFER_SUBPROC_TIMEOUT = 360      # subprocess 超時：6 分鐘


def _fetch_storesum_batch(batch, cat4_codes, stk_ids):
    conditions = [
        f"org_id = {quote_sql(ORG_ID)}",
        in_clause("store_id", batch),
        "stk_qty > 0",
    ]
    if cat4_codes:
        conditions.append(in_clause("cat4_id", cat4_codes))
    if stk_ids:
        conditions.append(in_clause("stk_id", stk_ids))
    sql = f"""
select store_id, stk_id, name, stk_qty, cat4_id
from storesum
where {' and '.join(conditions)}
"""
    # 暫時性失敗（JVM 啟動失敗 / SOAP 逾時 / EPB 抖動）自動重試，
    # 避免「8 批裡 1 批掛掉就整個預載失敗」。
    last_err = None
    for attempt in range(TRANSFER_BATCH_RETRIES + 1):
        try:
            return run_remote(
                sql,
                timeout=TRANSFER_SUBPROC_TIMEOUT,
                read_timeout_ms=TRANSFER_READ_TIMEOUT_MS,
            )
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt < TRANSFER_BATCH_RETRIES:
                time.sleep(TRANSFER_RETRY_BACKOFF)
    raise RuntimeError(
        f"門市批次查詢失敗（{','.join(batch)}）：{last_err}"
    )


def fetch_storesum_matrix(store_ids, *, cat4_codes=None, stk_ids=None):
    """平行（多執行緒）分批查 STORESUM（140EB 存貨彙總），可選用 cat4 / stk_id 過濾以縮小範圍。
    回傳 {stk_id: {"name": ..., "cat4": ..., "qty": {store_id: qty}}}。"""
    if not store_ids:
        return {}
    cat4_codes = list(cat4_codes) if cat4_codes else []
    stk_ids = list(stk_ids) if stk_ids else []

    # 先確保 Java 已編譯，避免多執行緒第一次同時觸發編譯
    compile_java("EPBReportQuery.java")

    batches = [
        store_ids[i:i + TRANSFER_FETCH_BATCH]
        for i in range(0, len(store_ids), TRANSFER_FETCH_BATCH)
    ]
    workers = max(1, min(len(batches), TRANSFER_MAX_WORKERS))
    matrix = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(_fetch_storesum_batch, batch, cat4_codes, stk_ids)
            for batch in batches
        ]
        for future in futures:
            headers, rows = future.result()
            for row in rows:
                rec = {headers[i].upper(): row[i] for i in range(len(headers))}
                stk_id = text(rec.get("STK_ID"))
                name = text(rec.get("NAME"))
                store_id = text(rec.get("STORE_ID"))
                if not stk_id or not name or name.startswith("@"):
                    continue
                qty = int(number(rec.get("STK_QTY")))
                if qty <= 0:
                    continue
                cat4 = text(rec.get("CAT4_ID"))
                entry = matrix.setdefault(stk_id, {"name": name, "cat4": cat4, "qty": {}})
                # 若同一 stk_id 名稱 / cat4 在不同門市略有差異，沿用第一次看到的
                if not entry["name"]:
                    entry["name"] = name
                if not entry.get("cat4"):
                    entry["cat4"] = cat4
                entry["qty"][store_id] = qty
    return matrix


# 主機矩陣快取：避免「冷查 100 秒」每次重來。一次抓全 4 類主機（CPU/iPhone/iPad/Watch）
# 跨所有門市的庫存，存記憶體 5 分鐘；category 模式的分析直接從快取在記憶體篩。
TRANSFER_MATRIX_TTL = 300                          # 5 分鐘
TRANSFER_ALL_CAT4 = sorted(TRANSFER_VALID_CAT4)    # 4 類預設全部 cat4 代碼
_MATRIX_CACHE = {"matrix": None, "ts": 0.0, "expires": 0.0}
_MATRIX_LOCK = threading.Lock()


def get_host_matrix(force=False):
    """取得（或建立）主機矩陣快取：全 4 類主機 × 所有門市。
    用 lock 串行化：若預載正在跑（持鎖數十秒），後來的請求會等鎖、拿到剛填好的快取，
    不會重複對 EPB 發查詢。回傳 {"matrix": ..., "ts": float}。"""
    with _MATRIX_LOCK:
        now = time.time()
        if (not force
                and _MATRIX_CACHE["matrix"] is not None
                and now < _MATRIX_CACHE["expires"]):
            return {"matrix": _MATRIX_CACHE["matrix"], "ts": _MATRIX_CACHE["ts"]}
        stores = list_transfer_stores()["items"]
        store_ids = [s["storeId"] for s in stores]
        matrix = fetch_storesum_matrix(store_ids, cat4_codes=TRANSFER_ALL_CAT4)
        ts = time.time()
        _MATRIX_CACHE["matrix"] = matrix
        _MATRIX_CACHE["ts"] = ts
        _MATRIX_CACHE["expires"] = ts + TRANSFER_MATRIX_TTL
        return {"matrix": matrix, "ts": ts}


def _normalize_cat4(raw):
    """從 payload 取出 cat4 list：可接受 list / 逗號分隔字串 / 單一字串。
    只保留 TRANSFER_VALID_CAT4 內的代碼，並去重保序。"""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple, set)):
        values = [text(v) for v in raw]
    else:
        values = [part.strip() for part in str(raw).replace("，", ",").split(",")]
    seen, result = set(), []
    for value in values:
        value = value.strip()
        if not value or value in seen:
            continue
        if value in TRANSFER_VALID_CAT4:
            seen.add(value)
            result.append(value)
    return result


def _normalize_stk_ids(raw):
    """從 payload 取出 stk_id list：可接受 list / 逗號 / 空白 / 換行分隔字串。
    去重保序，全部大寫（800AB 通常為大寫）。"""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple, set)):
        parts = [text(v) for v in raw]
    else:
        # 接受逗號、空白、換行、全形逗號當分隔
        normalized = str(raw).replace("，", ",").replace("\n", ",").replace("\r", ",")
        normalized = normalized.replace("\t", ",").replace(" ", ",")
        parts = [p.strip() for p in normalized.split(",")]
    seen, result = set(), []
    for part in parts:
        code = part.strip().upper()
        if not code or code in seen:
            continue
        seen.add(code)
        result.append(code)
    return result


def build_greedy_plan(rows):
    """Greedy Set Cover：每輪挑能覆蓋最多品項、總庫存最大、名稱字典序最小的來源倉。
    Port 自 /Users/sa/Claude/work/transfer.html 的 buildGreedyPlan。"""
    remaining = {r["code"]: r for r in rows}
    plan = []
    step = 1
    while remaining:
        coverage = {}
        for row in remaining.values():
            for warehouse in row["candidates"]:
                coverage.setdefault(warehouse, []).append(row)
        if not coverage:
            break
        selected_source = None
        selected_rows = []
        selected_stock = 0
        for source, covered in coverage.items():
            cur_score = len(covered)
            sel_score = len(selected_rows)
            cur_stock = sum(r["candidates"][source] for r in covered)
            if (
                cur_score > sel_score
                or (cur_score == sel_score and cur_stock > selected_stock)
                or (
                    cur_score == sel_score
                    and cur_stock == selected_stock
                    and (selected_source is None or source < selected_source)
                )
            ):
                selected_source = source
                selected_rows = covered
                selected_stock = cur_stock
        # 排序：主要在前、缺貨重的在前
        selected_rows.sort(
            key=lambda r: (
                0 if r.get("tag") == TRANSFER_TAG_PRIMARY else 1,
                r["targetQty"],
                r["code"],
            )
        )
        primary_count = sum(1 for r in selected_rows if r.get("tag") == TRANSFER_TAG_PRIMARY)
        plan.append(
            {
                "step": step,
                "source": selected_source,
                "primaryCount": primary_count,
                "companionCount": len(selected_rows) - primary_count,
                "items": [
                    {
                        "code": r["code"],
                        "model": r["model"],
                        "name": r["name"],
                        "targetQty": r["targetQty"],
                        "sourceQty": r["candidates"][selected_source],
                        "tag": r.get("tag", TRANSFER_TAG_PRIMARY),
                    }
                    for r in selected_rows
                ],
            }
        )
        for r in selected_rows:
            remaining.pop(r["code"], None)
        step += 1
    return plan


def _build_candidates(matrix, target_store_id, id_to_name, tag):
    """從 matrix 篩出符合本店≤1、來源≥3 的候選，每筆標上 tag。
    tag 可為字串，或 callable(info)->tag（依該品項資料決定主/搭）。"""
    tag_fn = tag if callable(tag) else (lambda info: tag)
    results = []
    for stk_id, info in matrix.items():
        target_qty = info["qty"].get(target_store_id, 0)
        if target_qty > TRANSFER_MAX_TARGET_QTY:
            continue
        donors = []
        for sid, qty in info["qty"].items():
            if sid == target_store_id:
                continue
            if qty >= TRANSFER_MIN_DONOR_QTY:
                donors.append({"warehouse": id_to_name[sid], "qty": qty})
        if not donors:
            continue
        donors.sort(key=lambda d: (-d["qty"], d["warehouse"]))
        best = donors[0]
        results.append(
            {
                "code": stk_id,
                "model": model_from_name(info["name"]),
                "name": info["name"],
                "targetQty": target_qty,
                "source": best["warehouse"],
                "sourceQty": best["qty"],
                "otherStock": "、".join(f"{d['warehouse']}({d['qty']})" for d in donors),
                "candidates": {d["warehouse"]: d["qty"] for d in donors},
                "tag": tag_fn(info),
            }
        )
    return results


def analyze_transfer(payload):
    """產生候選清單與 Greedy Set Cover 計畫。
    payload 可包含：
      storeId               目標門市的 store_id（必填）
      mode                  "category" or "stk_id"（預設 "category"）
      primaryCategories     主機需求 cat4 清單（mode=category 時必填，至少一）
      stkIds                指定需求 stk_id 清單（mode=stk_id 時必填，至少一）
      companionCategories   建議搭配 cat4 清單（選填）"""
    if not isinstance(payload, dict):
        payload = {}
    target_store_id = text(payload.get("storeId"))
    mode = text(payload.get("mode")) or "category"
    force_refresh = bool(payload.get("refresh"))

    stores = list_transfer_stores()["items"]
    if not any(s["storeId"] == target_store_id for s in stores):
        raise ValueError("請選擇本店門市")

    primary_cat4 = _normalize_cat4(payload.get("primaryCategories"))
    primary_stk_ids = _normalize_stk_ids(payload.get("stkIds"))
    companion_cat4 = _normalize_cat4(payload.get("companionCategories"))

    if mode not in ("category", "stk_id"):
        raise ValueError(f"未知的查詢模式：{mode}")
    if mode == "category" and not primary_cat4:
        raise ValueError("主機需求模式請至少選一個主機類別")
    if mode == "stk_id" and not primary_stk_ids:
        raise ValueError("指定需求模式請至少輸入一個存貨代碼")

    id_to_name = {s["storeId"]: s["name"] for s in stores}
    store_ids = [s["storeId"] for s in stores]

    if mode == "category":
        # 主、搭都是 cat4 過濾 → 用「全 4 類主機」的記憶體快取，在記憶體篩出需要的 cat4，
        # 依各品項的 cat4 標主/搭。冷查只發生一次（背景預載），之後吃快取幾乎瞬間。
        primary_set = set(primary_cat4)
        companion_set = {c for c in companion_cat4 if c not in primary_set}
        wanted = primary_set | companion_set
        cache = get_host_matrix(force=force_refresh)
        data_time = cache["ts"]
        sub_matrix = {
            stk_id: info
            for stk_id, info in cache["matrix"].items()
            if info.get("cat4") in wanted
        }
        candidates = _build_candidates(
            sub_matrix, target_store_id, id_to_name,
            lambda info: (
                TRANSFER_TAG_PRIMARY if info.get("cat4") in primary_set
                else TRANSFER_TAG_COMPANION
            ),
        )
        companion_cat4 = sorted(companion_set)
    else:
        # 指定需求：主要走 stk_id 查詢；搭配（若有）另跑一輪 cat4 查詢（即時，不吃快取）
        primary_matrix = fetch_storesum_matrix(store_ids, stk_ids=primary_stk_ids)
        primary_candidates = _build_candidates(
            primary_matrix, target_store_id, id_to_name, TRANSFER_TAG_PRIMARY
        )
        companion_candidates = []
        if companion_cat4:
            companion_matrix = fetch_storesum_matrix(store_ids, cat4_codes=companion_cat4)
            companion_candidates = _build_candidates(
                companion_matrix, target_store_id, id_to_name, TRANSFER_TAG_COMPANION
            )
        # 合併：相同 stk_id 出現在兩邊時，主要 tag 優先
        merged = {}
        for row in primary_candidates:
            merged[row["code"]] = row
        for row in companion_candidates:
            if row["code"] not in merged:
                merged[row["code"]] = row
        candidates = list(merged.values())
        data_time = time.time()
    # 排序：主要在前、缺貨重的在前、來源庫存多的在前
    candidates.sort(
        key=lambda r: (
            0 if r.get("tag") == TRANSFER_TAG_PRIMARY else 1,
            r["targetQty"],
            -r["sourceQty"],
            r["code"],
        )
    )

    plan = build_greedy_plan(candidates)
    warehouses = {w for row in candidates for w in row["candidates"].keys()}
    primary_count = sum(1 for r in candidates if r.get("tag") == TRANSFER_TAG_PRIMARY)
    return {
        "items": candidates,
        "plan": plan,
        "rowCount": len(candidates),
        "primaryCount": primary_count,
        "companionCount": len(candidates) - primary_count,
        "warehouseCount": len(warehouses),
        "stepCount": len(plan),
        "targetStore": id_to_name[target_store_id],
        "targetStoreId": target_store_id,
        "mode": mode,
        "primaryCategories": primary_cat4,
        "stkIds": primary_stk_ids,
        "companionCategories": companion_cat4,
        "dataTime": datetime.fromtimestamp(data_time).isoformat(timespec="seconds"),
    }


def _xlsx_thin_border():
    from openpyxl.styles import Border, Side
    side = Side(style="thin", color="FFD9E2EC")
    return Border(left=side, right=side, top=side, bottom=side)


def _xlsx_style_header(ws, last_col):
    head_font = Font(name="Arial", size=10, bold=True, color="FFFFFFFF")
    head_fill = PatternFill("solid", fgColor="FF1F4E78")
    align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    border = _xlsx_thin_border()
    for col in range(1, last_col + 1):
        cell = ws.cell(row=1, column=col)
        cell.font = head_font
        cell.fill = head_fill
        cell.alignment = align
        cell.border = border


def _xlsx_style_body(ws):
    body_font = Font(name="Arial", size=10, color="FF1F2933")
    align = Alignment(vertical="center", wrap_text=True)
    border = _xlsx_thin_border()
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.font = body_font
            cell.alignment = align
            cell.border = border


def _tag_label(tag):
    return "搭" if tag == TRANSFER_TAG_COMPANION else "主"


def _apply_tag_cell_style(cell, tag):
    """主：深藍底白字；搭：灰底深字。"""
    if tag == TRANSFER_TAG_COMPANION:
        cell.fill = PatternFill("solid", fgColor="FFE4E7EC")
        cell.font = Font(name="Arial", size=10, bold=True, color="FF617083")
    else:
        cell.fill = PatternFill("solid", fgColor="FF1F5F99")
        cell.font = Font(name="Arial", size=10, bold=True, color="FFFFFFFF")
    cell.alignment = Alignment(horizontal="center", vertical="center")


def export_transfer_suggestion(payload):
    result = analyze_transfer(payload)
    items = result["items"]
    store_name = result["targetStore"]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = (store_name + "調撥建議清單")[:31]

    headers = [
        "標籤", "存貨代碼", "型號", "存貨名稱",
        f"{store_name}現有庫存", "建議調撥來源", "來源倉庫存數量",
        "其他庫存≥3的倉庫（庫存量）",
    ]
    widths = [6, 14, 18, 58, 14, 18, 16, 70]
    for col, label in enumerate(headers, start=1):
        ws.cell(row=1, column=col, value=label)
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = widths[col - 1]

    for idx, row in enumerate(items, start=2):
        tag = row.get("tag", TRANSFER_TAG_PRIMARY)
        ws.cell(row=idx, column=1, value=_tag_label(tag))
        ws.cell(row=idx, column=2, value=row["code"])
        ws.cell(row=idx, column=3, value=row["model"])
        ws.cell(row=idx, column=4, value=row["name"])
        ws.cell(row=idx, column=5, value=row["targetQty"])
        ws.cell(row=idx, column=6, value=row["source"])
        ws.cell(row=idx, column=7, value=row["sourceQty"])
        ws.cell(row=idx, column=8, value=row["otherStock"])

    _xlsx_style_header(ws, last_col=len(headers))
    _xlsx_style_body(ws)

    # 標籤欄上色 + 庫存著色（targetQty=0 紅、=1 橘；sourceQty 綠）
    red_fill = PatternFill("solid", fgColor="FFFDE2E1")
    amber_fill = PatternFill("solid", fgColor="FFFFE8CC")
    green_fill = PatternFill("solid", fgColor="FFD9F2DD")
    for idx, row in enumerate(items, start=2):
        _apply_tag_cell_style(ws.cell(row=idx, column=1), row.get("tag"))
        target_cell = ws.cell(row=idx, column=5)
        target_cell.fill = red_fill if row["targetQty"] == 0 else amber_fill
        ws.cell(row=idx, column=7).fill = green_fill

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    stream = BytesIO()
    wb.save(stream)
    stream.seek(0)
    filename = f"{store_name}調撥建議清單.xlsx"
    return filename, stream.getvalue()


def export_transfer_plan(payload):
    result = analyze_transfer(payload)
    plan = result["plan"]
    store_name = result["targetStore"]

    wb = openpyxl.Workbook()
    overview = wb.active
    overview.title = "調撥計畫總覽"

    overview_headers = [
        "優先順序", "來源倉庫", "標籤", "存貨代碼", "型號", "存貨名稱",
        f"{store_name}現有", "來源倉庫存",
    ]
    overview_widths = [10, 18, 6, 14, 18, 58, 12, 12]
    for col, label in enumerate(overview_headers, start=1):
        overview.cell(row=1, column=col, value=label)
        overview.column_dimensions[openpyxl.utils.get_column_letter(col)].width = overview_widths[col - 1]

    rowno = 2
    row_meta = []  # (rowno, step_color, tag)
    for block in plan:
        color = TRANSFER_STEP_FILLS[(block["step"] - 1) % len(TRANSFER_STEP_FILLS)]
        for item in block["items"]:
            tag = item.get("tag", TRANSFER_TAG_PRIMARY)
            overview.cell(row=rowno, column=1, value=block["step"])
            overview.cell(row=rowno, column=2, value=block["source"])
            overview.cell(row=rowno, column=3, value=_tag_label(tag))
            overview.cell(row=rowno, column=4, value=item["code"])
            overview.cell(row=rowno, column=5, value=item["model"])
            overview.cell(row=rowno, column=6, value=item["name"])
            overview.cell(row=rowno, column=7, value=item["targetQty"])
            overview.cell(row=rowno, column=8, value=item["sourceQty"])
            row_meta.append((rowno, color, tag))
            rowno += 1

    _xlsx_style_header(overview, last_col=len(overview_headers))
    _xlsx_style_body(overview)
    for r, color, tag in row_meta:
        fill = PatternFill("solid", fgColor=f"FF{color}")
        for c in range(1, len(overview_headers) + 1):
            if c == 3:
                continue  # 標籤欄稍後另外上色
            overview.cell(row=r, column=c).fill = fill
        _apply_tag_cell_style(overview.cell(row=r, column=3), tag)
    overview.freeze_panes = "A2"
    if overview.max_row >= 2:
        overview.auto_filter.ref = overview.dimensions

    summary = wb.create_sheet("調撥摘要")
    summary_headers = ["優先順序", "來源倉庫", "主品項", "搭品項", "可調品項數", "涵蓋型號"]
    summary_widths = [10, 18, 10, 10, 12, 80]
    for col, label in enumerate(summary_headers, start=1):
        summary.cell(row=1, column=col, value=label)
        summary.column_dimensions[openpyxl.utils.get_column_letter(col)].width = summary_widths[col - 1]

    for idx, block in enumerate(plan, start=2):
        models = sorted({item["model"] for item in block["items"] if item["model"]})
        summary.cell(row=idx, column=1, value=block["step"])
        summary.cell(row=idx, column=2, value=block["source"])
        summary.cell(row=idx, column=3, value=block.get("primaryCount", 0))
        summary.cell(row=idx, column=4, value=block.get("companionCount", 0))
        summary.cell(row=idx, column=5, value=len(block["items"]))
        summary.cell(row=idx, column=6, value="、".join(models))

    _xlsx_style_header(summary, last_col=len(summary_headers))
    _xlsx_style_body(summary)
    for idx in range(2, len(plan) + 2):
        color = TRANSFER_STEP_FILLS[(idx - 2) % len(TRANSFER_STEP_FILLS)]
        fill = PatternFill("solid", fgColor=f"FF{color}")
        for c in range(1, len(summary_headers) + 1):
            summary.cell(row=idx, column=c).fill = fill
    summary.freeze_panes = "A2"
    if summary.max_row >= 2:
        summary.auto_filter.ref = summary.dimensions

    stream = BytesIO()
    wb.save(stream)
    stream.seek(0)
    filename = f"{store_name}調撥計畫.xlsx"
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
            if parsed.path == "/api/transfer/stores":
                self.send_json(200, list_transfer_stores())
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
            if parsed.path == "/api/transfer/prewarm":
                cache = get_host_matrix(force=bool(payload.get("refresh")))
                self.send_json(200, {
                    "ok": True,
                    "dataTime": datetime.fromtimestamp(cache["ts"]).isoformat(timespec="seconds"),
                    "count": len(cache["matrix"]),
                })
                return
            if parsed.path == "/api/transfer/analyze":
                self.send_json(200, analyze_transfer(payload))
                return
            if parsed.path == "/api/transfer/suggestion/export":
                filename, body = export_transfer_suggestion(payload)
                self.send_xlsx(filename, body)
                return
            if parsed.path == "/api/transfer/plan/export":
                filename, body = export_transfer_plan(payload)
                self.send_xlsx(filename, body)
                return
        except Exception as exc:
            self.send_json(500, {"ok": False, "error": str(exc)})
            return
        self.send_json(404, {"ok": False, "error": "Not found"})


def main():
    compile_java("EPBReportQuery.java")
    port = int(os.environ.get("PORT", "8781"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Purchase Live Query App: http://127.0.0.1:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
