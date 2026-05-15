# 門市進貨查詢工具

獨立的 EPB 即時查詢 App，查「調撥入庫（INVTRNIN）」單據。與門市銷售報表 App 完全分開，互不影響。

## 同事首次安裝（最簡）

1. 開安裝頁（GitHub Pages）：`https://samwang38.github.io/store-in/`
2. 點「下載啟動檔」→ 雙擊 `啟動門市進貨查詢.command`
3. **首次會被 macOS 攔下**：在檔案上按右鍵 →「打開」→ 再按「打開」一次（之後從桌面雙擊不再跳）
4. 自動安裝到桌面資料夾「門市進貨查詢-app」、自動開瀏覽器

備援（指令安裝）：

```bash
curl -fsSL https://raw.githubusercontent.com/samwang38/store-in/main/install.sh | bash
```

## 日常使用

1. **先連公司 VPN**（需能連到 192.168.1.177；VPN 設定見 `~/Downloads/VPN設定說明.md`，伺服器 202.133.226.82:10443）
2. 雙擊桌面「門市進貨查詢-app」內的 `啟動門市進貨查詢.command`（每次自動更新到最新版）
3. 瀏覽器自動開啟 `http://127.0.0.1:8781/`，選我方倉與日期 → 查詢 / 下載 Excel
4. 關閉終端機視窗即停止

（門市銷售報表 App 用 8780，本工具用 8781，可同時開啟。）

## 環境需求

| 項目 | 需求 |
|------|------|
| OS | macOS |
| Python | 3.8 以上 |
| JDK | 1.8（`/Library/Java/JavaVirtualMachines/jdk1.8.0_251.jdk`）|
| EPBrowser lib | `/Library/EPBrowser/EPB/Shell/`（裝過 EPB 即有）|
| 網路 | 公司 VPN（192.168.1.177:8080）|
| Python 套件 | `openpyxl`（啟動檔會自動安裝）|

> 店機已裝 EPB，故 Java 與 EPB 元件皆現成；啟動檔只會額外抓本小程式與 `openpyxl`。

## 免登入

與北一區週報 App 相同：本機已連 VPN、可直接連到 EPB Web Service，網頁端不需再登入。

## 查詢條件（畫面可調）

- 我方倉：預設 SA004 士林倉，可下拉切換其他倉
- 起始日 / 結束日：預設都是當天

## 固定條件（寫死，不顯示）

對應 800AB STOREDTL 調撥入庫畫面（已比對系統匯出檔逐筆吻合）：

- 出入庫代碼 INVTRNIN（調撥入庫）→ `SRC_CODE = 'INVTRNTN'` + `MOVE_FLG = 'I'`
- 收貨方 `STORE_ID` = 我方倉（畫面可選，預設 SA004）
- 來源倉 `TO_STORE_ID` = `SA099` 總公司倉（鎖死）
- 類別1 包括 `1003` / `1001`
- 類別2 = `2001`（APL原廠）
- 類別3 = `3001`（APL主機）

## 資料來源

透過 EPB Web Service 讀取 `STOREDTL`（庫存異動明細），以 `DOC_DATE`（單據日期）篩選，單號取 `SRC_DOC_ID`。

## 輸出

- 畫面表格：單據日期、單號、來源倉、存貨代碼、型號、品名、數量
- 「下載 Excel」：同條件匯出 .xlsx
