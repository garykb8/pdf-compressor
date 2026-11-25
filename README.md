# pdf-compressor

適合畫冊、掃描電子書與大型 PDF 的命令列瘦身工具（基於 Ghostscript，純 Python 標準函式庫、無需安裝第三方 Python 套件）。

## 環境需求

- Python 3.9+
- [Ghostscript](https://www.ghostscript.com/)（`brew install ghostscript`）
- [qpdf](https://qpdf.sourceforge.io/)（選用，用於 `--inspect` 檢查與壓縮後完整性驗證：`brew install qpdf`）

## 內建方案 (`-p` / `--preset`)

| 方案 | 說明 | 預設檔名後綴 |
| :--- | :--- | :--- |
| `archive`（預設） | 保留原解析度 + 高畫質 JPEG（`QFactor=0.25`，4:4:4 無色度抽樣），適合畫冊收藏 | `_高畫質瘦身` |
| `balanced` | 降採樣至 200 DPI + 中高畫質 JPEG（`QFactor=0.40`），適合平板／電腦閱讀 | `_200dpi` |
| `compact` | 降採樣至 150 DPI + 標準 JPEG（`QFactor=0.60`），適合手機瀏覽或分享 | `_150dpi` |

## 使用方式

```bash
# 檢查 PDF 頁數、解析度與圖片壓縮格式（不執行壓縮）
./pdf_compressor.py --inspect book.pdf

# 高畫質收藏模式（預設，保留原解析度，另存新檔不覆蓋原檔）
./pdf_compressor.py book.pdf

# 平衡閱讀版（200 DPI）或極致輕量版（150 DPI）
./pdf_compressor.py book.pdf -p balanced
./pdf_compressor.py book.pdf -p compact

# 批次處理多個 PDF 或整個資料夾
./pdf_compressor.py *.pdf -p archive
./pdf_compressor.py ./資料夾路徑 -p balanced

# 自訂 DPI 與 JPEG 品質
./pdf_compressor.py book.pdf --dpi 250 --qfactor 0.30 -o output.pdf
```

## 特色

- **不覆蓋原檔**：預設另存新檔，若目標已存在會自動跳過（需加上 `-f` 才覆蓋）。
- **原子寫入**：壓縮過程先寫入暫存檔，中斷或失敗時自動清理，不會產生損壞的 PDF。
- **自動驗證**：若系統有安裝 `qpdf`，壓縮完成會自動檢查頁數與檔案結構完整性。
