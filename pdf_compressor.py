#!/usr/bin/env python3
"""
pdf_compressor.py — 適合畫冊、掃描書與一般 PDF 的瘦身工具（基於 Ghostscript）

使用範例：
  ./pdf_compressor.py book.pdf                       # 預設高畫質收藏 (archive)
  ./pdf_compressor.py book.pdf -p balanced           # 200 DPI 平衡閱讀版
  ./pdf_compressor.py book.pdf -p compact            # 150 DPI 極致輕量版
  ./pdf_compressor.py *.pdf -p balanced              # 批次壓縮多個 PDF
  ./pdf_compressor.py ./資料夾 -p archive            # 壓縮整個資料夾內的 PDF
  ./pdf_compressor.py book.pdf --inspect             # 只檢查 PDF 圖片格式與解析度
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class Preset:
    name: str
    description: str
    dpi: Optional[int]  # None = 保留原解析度（不降採樣）
    qfactor: float      # Ghostscript QFactor：越小畫質越高（0.15 極高 ~ 0.75 一般）
    chroma_444: bool    # True = 4:4:4 無色度抽樣（線條與色彩更銳利），False = 4:2:0
    suffix: str


PRESETS: dict[str, Preset] = {
    "archive": Preset(
        name="archive",
        description="高畫質收藏：保留原解析度，高品質 JPEG（4:4:4），適合畫冊收藏",
        dpi=None,
        qfactor=0.25,
        chroma_444=True,
        suffix="_高畫質瘦身",
    ),
    "balanced": Preset(
        name="balanced",
        description="平衡閱讀：降採樣至 200 DPI + 中高畫質 JPEG，適合平板／電腦閱讀",
        dpi=200,
        qfactor=0.40,
        chroma_444=False,
        suffix="_200dpi",
    ),
    "compact": Preset(
        name="compact",
        description="極致輕量：降採樣至 150 DPI + 標準 JPEG，適合手機瀏覽或分享",
        dpi=150,
        qfactor=0.60,
        chroma_444=False,
        suffix="_150dpi",
    ),
}


def format_size(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024.0 or unit == "TB":
            if unit in ("B", "KB"):
                return f"{value:.0f} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{num_bytes} B"


def require_tool(name: str, brew_pkg: Optional[str] = None) -> str:
    path = shutil.which(name)
    if not path:
        hint = f"（可透過 `brew install {brew_pkg or name}` 安裝）"
        sys.exit(f"錯誤：找不到 `{name}` 指令{hint}")
    return path


def inspect_pdf(pdf_path: Path) -> None:
    size = pdf_path.stat().st_size
    print(f"\n📄 {pdf_path.name}  ({format_size(size)})")

    qpdf = shutil.which("qpdf")
    if not qpdf:
        print("  提示：安裝 qpdf (`brew install qpdf`) 可查看詳細頁數與內嵌圖片資訊。")
        return

    try:
        npages = subprocess.check_output(
            [qpdf, "--show-npages", str(pdf_path)],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        print(f"  頁數：{npages} 頁（平均每頁 {format_size(int(size / max(int(npages), 1)))}）")
    except Exception:
        pass

    try:
        raw = subprocess.check_output(
            [qpdf, "--json-stream-data=none", "--json", str(pdf_path)],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        data = json.loads(raw)
        objs = data.get("qpdf", [None, {}])[1]
        filters: dict[str, int] = {}
        resolutions: dict[str, int] = {}
        img_count = 0
        for obj in objs.values():
            if not isinstance(obj, dict):
                continue
            d = obj.get("stream", {}).get("dict", {})
            if d.get("/Subtype") == "/Image":
                img_count += 1
                flt = str(d.get("/Filter", "None"))
                filters[flt] = filters.get(flt, 0) + 1
                w, h = d.get("/Width"), d.get("/Height")
                if w and h:
                    key = f"{w}×{h}"
                    resolutions[key] = resolutions.get(key, 0) + 1

        print(f"  內嵌圖片：{img_count} 張")
        if filters:
            flt_str = ", ".join(
                f"{k} ({v}張)" for k, v in sorted(filters.items(), key=lambda x: -x[1])
            )
            print(f"  壓縮格式：{flt_str}")
        if resolutions:
            top_res = sorted(resolutions.items(), key=lambda x: -x[1])[:5]
            res_str = ", ".join(f"{k} ({v}張)" for k, v in top_res)
            print(f"  主要解析度：{res_str}")
    except Exception as exc:
        print(f"  無法解析圖片詳細資訊：{exc}")


def build_distiller_params(
    dpi: Optional[int],
    qfactor: float,
    chroma_444: bool,
) -> str:
    samples = "[1 1 1 1]" if chroma_444 else "[2 1 1 2]"
    parts = [
        "/AutoFilterColorImages false",
        "/ColorImageFilter /DCTEncode",
        "/AutoFilterGrayImages false",
        "/GrayImageFilter /DCTEncode",
        f"/ColorImageDict << /QFactor {qfactor} /Blend 1 /HSamples {samples} /VSamples {samples} >>",
        f"/GrayImageDict << /QFactor {qfactor} /Blend 1 >>",
    ]
    if dpi is None:
        parts.extend([
            "/DownsampleColorImages false",
            "/DownsampleGrayImages false",
            "/DownsampleMonoImages false",
        ])
    else:
        parts.extend([
            "/DownsampleColorImages true",
            "/ColorImageDownsampleType /Bicubic",
            f"/ColorImageResolution {dpi}",
            "/ColorImageDownsampleThreshold 1.0",
            "/DownsampleGrayImages true",
            "/GrayImageDownsampleType /Bicubic",
            f"/GrayImageResolution {dpi}",
            "/GrayImageDownsampleThreshold 1.0",
            "/DownsampleMonoImages true",
            "/MonoImageDownsampleType /Subsample",
            f"/MonoImageResolution {max(dpi * 2, 300)}",
        ])
    return "<< " + " ".join(parts) + " >> setdistillerparams"


def verify_pdf(pdf_path: Path) -> tuple[Optional[int], bool]:
    qpdf = shutil.which("qpdf")
    if not qpdf:
        return None, True
    try:
        npages = int(
            subprocess.check_output(
                [qpdf, "--show-npages", str(pdf_path)],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
        )
        check = subprocess.run(
            [qpdf, "--check", str(pdf_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return npages, check.returncode in (0, 3)  # 0=OK, 3=warnings only
    except Exception:
        return None, False


def compress_pdf(
    gs_path: str,
    input_path: Path,
    output_path: Path,
    dpi: Optional[int],
    qfactor: float,
    chroma_444: bool,
    force: bool = False,
    dry_run: bool = False,
) -> bool:
    if output_path.exists() and not force:
        print(f"⚠️  跳過：{output_path.name} 已存在（如需覆蓋請加上 --force）")
        return False

    distiller = build_distiller_params(dpi=dpi, qfactor=qfactor, chroma_444=chroma_444)

    if dry_run:
        cmd = [
            gs_path,
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.5",
            "-dNOPAUSE",
            "-dQUIET",
            "-dBATCH",
            f"-sOutputFile={output_path}",
            "-c",
            distiller,
            "-f",
            str(input_path),
        ]
        print("[dry-run]", " ".join(cmd))
        return True

    orig_size = input_path.stat().st_size
    dpi_label = f"{dpi} DPI" if dpi else "保留原解析度"
    chroma_label = "4:4:4" if chroma_444 else "4:2:0"
    print(f"\n🔄 開始壓縮：{input_path.name} ({format_size(orig_size)})")
    print(f"   設定：{dpi_label} | QFactor={qfactor} | {chroma_label}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".pdf_compressor_", suffix=".pdf", dir=str(output_path.parent)
    )
    os.close(fd)
    tmp_path = Path(tmp_name)

    cmd = [
        gs_path,
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.5",
        "-dNOPAUSE",
        "-dQUIET",
        "-dBATCH",
        f"-sOutputFile={tmp_path}",
        "-c",
        distiller,
        "-f",
        str(input_path),
    ]

    t0 = time.monotonic()
    try:
        res = subprocess.run(cmd, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            tmp_path.unlink(missing_ok=True)
            print(f"❌ 壓縮失敗：{input_path.name}\n{res.stderr.strip()}")
            return False

        tmp_path.replace(output_path)
    except KeyboardInterrupt:
        tmp_path.unlink(missing_ok=True)
        print("\n⛔ 已中斷，暫存檔已清理。")
        sys.exit(130)
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        print(f"❌ 發生錯誤：{exc}")
        return False

    elapsed = time.monotonic() - t0
    new_size = output_path.stat().st_size
    diff_pct = (1.0 - new_size / orig_size) * 100.0 if orig_size > 0 else 0.0
    npages, ok = verify_pdf(output_path)

    status = "✅ 完成" if ok else "⚠️ 完成（qpdf 檢查有異常）"
    page_info = f" | {npages} 頁" if npages is not None else ""
    print(
        f"{status}：{output_path.name} "
        f"({format_size(orig_size)} → {format_size(new_size)}, "
        f"縮減 {diff_pct:.1f}%{page_info}, 耗時 {elapsed:.1f}s)"
    )
    if new_size >= orig_size:
        print("   💡 提醒：壓縮後檔案沒有變小（原檔可能已經高度壓縮），建議保留原檔。")
    return True


def collect_pdfs(inputs: list[str]) -> list[Path]:
    pdfs: list[Path] = []
    for item in inputs:
        p = Path(item).expanduser().resolve()
        if p.is_file() and p.suffix.lower() == ".pdf":
            pdfs.append(p)
        elif p.is_dir():
            pdfs.extend(sorted(p.glob("*.pdf")))
        else:
            print(f"⚠️  找不到 PDF 檔案或資料夾：{item}")
    return pdfs


def parse_args() -> argparse.Namespace:
    preset_help = "\n".join(
        f"  {k:<10} {v.description}" for k, v in PRESETS.items()
    )
    parser = argparse.ArgumentParser(
        prog="pdf_compressor.py",
        description="PDF 智慧瘦身工具（適合畫冊、掃描電子書與大型 PDF）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"預設方案 (--preset):\n{preset_help}",
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        help="要處理的 PDF 檔案或資料夾（可一次指定多個）",
    )
    parser.add_argument(
        "-p", "--preset",
        choices=list(PRESETS.keys()),
        default="archive",
        help="壓縮方案（預設：archive 高畫質收藏）",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=None,
        help="自訂降採樣 DPI（例如 200、150；設為 0 表示強制保留原解析度）",
    )
    parser.add_argument(
        "--qfactor",
        type=float,
        default=None,
        help="自訂 JPEG QFactor（越小畫質越高，建議 0.20~0.70）",
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="指定輸出檔案路徑（僅限單一輸入檔案時使用）",
    )
    parser.add_argument(
        "--suffix",
        type=str,
        default=None,
        help="自訂輸出檔名後綴（預設依方案自動命名，如 _高畫質瘦身）",
    )
    parser.add_argument(
        "-f", "--force",
        action="store_true",
        help="若輸出檔案已存在，直接覆蓋",
    )
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="只檢查 PDF 的頁數、解析度與圖片壓縮格式，不執行壓縮",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="僅顯示將執行的 Ghostscript 指令，不實際壓縮",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pdfs = collect_pdfs(args.inputs)
    if not pdfs:
        sys.exit("錯誤：沒有找到任何可處理的 PDF 檔案。")

    if args.inspect:
        for pdf in pdfs:
            inspect_pdf(pdf)
        return

    if args.output and len(pdfs) > 1:
        sys.exit("錯誤：批次處理多個檔案時無法使用 --output，請改用 --suffix。")

    gs_path = require_tool("gs", "ghostscript")
    preset = PRESETS[args.preset]

    if args.dpi is None:
        dpi = preset.dpi
    elif args.dpi <= 0:
        dpi = None
    else:
        dpi = args.dpi

    qfactor = args.qfactor if args.qfactor is not None else preset.qfactor
    chroma_444 = preset.chroma_444 if args.qfactor is None else (qfactor <= 0.30)
    suffix = args.suffix if args.suffix is not None else preset.suffix

    for pdf in pdfs:
        if args.output:
            out_path = Path(args.output).expanduser().resolve()
        else:
            out_path = pdf.with_name(f"{pdf.stem}{suffix}{pdf.suffix}")

        compress_pdf(
            gs_path=gs_path,
            input_path=pdf,
            output_path=out_path,
            dpi=dpi,
            qfactor=qfactor,
            chroma_444=chroma_444,
            force=args.force,
            dry_run=args.dry_run,
        )


if __name__ == "__main__":
    main()
