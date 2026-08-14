#!/usr/bin/env python3
"""
10分钟涨幅突破监控: 当前10m K线涨跌幅 > 左侧3根K线振幅之和 → 钉钉告警
每10分钟轮询200个USDT交易对，匹配条件推送到钉钉。
"""

import os, sys, io, json, time, base64, hashlib, hmac
import urllib.request, urllib.error, urllib.parse
from datetime import datetime, timezone, timedelta

import requests
from PIL import Image, ImageDraw, ImageFont

# Windows GBK 修复
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ============ 配置 ============
DINGTALK_WEBHOOK = os.environ.get("DINGTALK_WEBHOOK", "").strip()
DINGTALK_SECRET = os.environ.get("DINGTALK_SECRET", "").strip()
if not DINGTALK_WEBHOOK or not DINGTALK_SECRET:
    print(
        "错误: 未配置钉钉推送。请先设置环境变量 DINGTALK_WEBHOOK / DINGTALK_SECRET\n"
        "  (运行 schedule_task.ps1 可自动写入用户环境变量)"
    )
    sys.exit(1)
BINANCE_REST = "https://api.binance.com"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ============ 字体 ============
def get_font(size, bold=False):
    paths = [
        "C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/arial.ttf",
    ]
    for p in paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except:
                continue
    return ImageFont.load_default()

# ============ Binance API ============
def fetch_json(url, retries=3):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(1)

def get_top_usdt_pairs(limit=200):
    tickers = fetch_json(f"{BINANCE_REST}/api/v3/ticker/24hr")
    usdt = [t for t in tickers
            if t["symbol"].endswith("USDT")
            and "BUSD" not in t["symbol"]
            and "TUSD" not in t["symbol"]
            and "USDC" not in t["symbol"]]
    usdt.sort(key=lambda t: float(t["quoteVolume"]), reverse=True)
    return [{"symbol": t["symbol"], "lastPrice": float(t["lastPrice"]),
             "priceChangePercent": float(t["priceChangePercent"]),
             "quoteVolume": float(t["quoteVolume"])} for t in usdt[:limit]]

def get_10m_klines(symbol, limit=4):
    """获取最近 limit 根10分钟K线（Binance无10m，从5m合成）"""
    try:
        # 取足够5m K线: 每条10m=2条5m, 多取2根防对齐问题
        raw5m = fetch_json(
            f"{BINANCE_REST}/api/v3/klines?symbol={urllib.parse.quote(symbol,safe='')}&interval=5m&limit={limit * 2 + 2}"
        )
        # 转为 candle 列表
        c5 = []
        for k in raw5m:
            c5.append({
                "time":  k[0] // 1000,
                "open":  float(k[1]),
                "high":  float(k[2]),
                "low":   float(k[3]),
                "close": float(k[4]),
            })
        # 合成为10m: 每2根5m → 1根10m
        candles_10m = []
        i = 0
        while i + 1 < len(c5):
            a, b = c5[i], c5[i + 1]
            candles_10m.append({
                "time":  a["time"],
                "open":  a["open"],
                "high":  max(a["high"], b["high"]),
                "low":   min(a["low"], b["low"]),
                "close": b["close"],
            })
            i += 2
        return candles_10m[-limit:]  # 取最后 limit 根
    except Exception as e:
        return None

def check_breakout(candles):
    """
    条件: 当前K线涨跌幅 |close-open| > 0.5 × 左侧3根K线振幅(high-low)之和
    返回 dict 或 None
    """
    if len(candles) < 4:
        return None
    c0, c1, c2, c3 = candles
    change = c3["close"] - c3["open"]
    amp_sum = (c0["high"] - c0["low"]) + (c1["high"] - c1["low"]) + (c2["high"] - c2["low"])
    if amp_sum <= 0:
        return None
    ratio = abs(change) / amp_sum
    return {
        "triggered": ratio > 0.5,
        "change": change,
        "ampSum": amp_sum,
        "threshold": amp_sum * 0.5,
        "ratio": ratio,
        "direction": "up" if change > 0 else "down",
    }

def scan_all_pairs(pairs):
    """扫描所有币种，返回触发条件的列表"""
    triggered = []
    total = len(pairs)
    print(f"Scanning {total} pairs for 10m breakout signals...")
    for i, pair in enumerate(pairs):
        symbol = pair["symbol"]
        candles = get_10m_klines(symbol, limit=4)
        if candles:
            res = check_breakout(candles)
            if res and res["triggered"]:
                pct = (res["change"] / candles[3]["open"]) * 100
                info = {
                    "symbol": symbol,
                    "direction": res["direction"],
                    "change": res["change"],
                    "changePct": round(pct, 3),
                    "ampSum": res["ampSum"],
                    "threshold": res["threshold"],
                    "ratio": round(res["ratio"], 2),
                    "close": candles[3]["close"],
                    "open": candles[3]["open"],
                    "high": candles[3]["high"],
                    "low": candles[3]["low"],
                    "volume": pair["quoteVolume"],
                    "priceChange24h": pair["priceChangePercent"],
                    "_candles": candles,
                }
                triggered.append(info)
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{total} scanned, {len(triggered)} triggered so far")
        time.sleep(0.06)

    # 按涨跌幅绝对值排序
    triggered.sort(key=lambda x: abs(x["changePct"]), reverse=True)
    return triggered

# ============ 图片生成 ============
def fmt_price(p):
    if p >= 1000: return f"${p:,.0f}"
    if p >= 1: return f"${p:,.2f}"
    if p >= 0.01: return f"${p:,.4f}"
    if p >= 1e-4: return f"${p:.6f}"
    return f"${p:.8f}"

def create_alert_image(results):
    """生成告警表格图片"""
    if not results:
        return None

    n = len(results)
    BG, HDR, ALT = (11, 14, 17), (26, 30, 36), (20, 23, 29)
    GREEN, RED, YELLOW, WHITE, GRAY = (14, 203, 129), (246, 70, 93), (240, 185, 11), (234, 236, 239), (132, 142, 156)

    cols = [
        ("#",         50),
        ("交易对",    150),
        ("方向",      80),
        ("涨跌幅%",   120),
        ("振幅和",    150),
        ("倍数",      80),
        ("当前价",    150),
        ("24h涨跌",   120),
    ]
    pad, title_h, header_h, row_h = 20, 50, 40, 40
    img_w = pad + sum(w for _, w in cols) + pad
    img_h = title_h + header_h + n * row_h + 30

    img = Image.new("RGB", (img_w, img_h), BG)
    draw = ImageDraw.Draw(img)
    ft_t = get_font(22, True)
    ft_h = get_font(16, True)
    ft_r = get_font(16)
    ft_rank = get_font(18, True)

    # Title
    draw.rectangle([(0, 0), (img_w, title_h)], fill=(20, 23, 29))
    tz = timezone(timedelta(hours=8))
    t_str = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    title = f"10m Breakout Alert | {t_str} (北京时间)"
    draw.text((pad, 12), title, fill=YELLOW, font=ft_t)

    # Header
    y = title_h
    draw.rectangle([(0, y), (img_w, y + header_h)], fill=HDR)
    x = pad
    for label, w in cols:
        tw = draw.textlength(label, font=ft_h)
        if label == "#":
            draw.text((x + (w - tw) / 2, y + 8), label, fill=GRAY, font=ft_h)
        elif label == "交易对":
            draw.text((x + 4, y + 8), label, fill=GRAY, font=ft_h)
        else:
            draw.text((x + w - tw - 4, y + 8), label, fill=GRAY, font=ft_h)
        x += w
    draw.line([(pad, y + header_h - 2), (img_w - pad, y + header_h - 2)], fill=(42, 47, 56), width=1)

    # Data
    for idx, item in enumerate(results):
        y = title_h + header_h + idx * row_h
        if idx % 2 == 0:
            draw.rectangle([(0, y), (img_w, y + row_h)], fill=ALT)
        x = pad
        rank = idx + 1
        direction = item["direction"]
        chg_pct = item["changePct"]
        pct24 = item["priceChange24h"]
        ratio = item["ratio"]

        for label, w in cols:
            if label == "#":
                c = {1: (255, 215, 0), 2: (192, 192, 192), 3: (205, 127, 50)}.get(rank, GRAY)
                t = str(rank)
                tw = draw.textlength(t, font=ft_rank)
                draw.text((x + (w - tw) / 2, y + 7), t, fill=c, font=ft_rank)
            elif label == "交易对":
                sym = item["symbol"].replace("USDT", "")
                draw.text((x + 4, y + 7), sym, fill=WHITE, font=ft_r)
            elif label == "方向":
                t = "↗ 拉升" if direction == "up" else "↘ 砸盘"
                c = GREEN if direction == "up" else RED
                draw.text((x + 4, y + 7), t, fill=c, font=ft_r)
            elif label == "涨跌幅%":
                t = f"+{chg_pct:.2f}%" if chg_pct >= 0 else f"{chg_pct:.2f}%"
                c = GREEN if chg_pct >= 0 else RED
                tw = draw.textlength(t, font=ft_h)
                draw.text((x + w - tw - 4, y + 7), t, fill=c, font=ft_h)
            elif label == "振幅和":
                t = fmt_price(item["ampSum"])
                tw = draw.textlength(t, font=ft_r)
                draw.text((x + w - tw - 4, y + 7), t, fill=GRAY, font=ft_r)
            elif label == "倍数":
                t = f"{ratio}x"
                c = YELLOW if ratio >= 3 else GREEN if ratio >= 2 else WHITE
                tw = draw.textlength(t, font=ft_h)
                draw.text((x + w - tw - 4, y + 7), t, fill=c, font=ft_h)
            elif label == "当前价":
                t = fmt_price(item["close"]).replace("$", "")
                tw = draw.textlength(t, font=ft_r)
                draw.text((x + w - tw - 4, y + 7), t, fill=WHITE, font=ft_r)
            elif label == "24h涨跌":
                t = f"+{pct24:.2f}%" if pct24 >= 0 else f"{pct24:.2f}%"
                c = GREEN if pct24 >= 0 else RED
                tw = draw.textlength(t, font=ft_r)
                draw.text((x + w - tw - 4, y + 7), t, fill=c, font=ft_r)
            x += w

    # Footer
    y = img_h - 24
    ft_txt = "条件: 当前10m涨跌幅 > 左侧3根10mK线振幅之和 | Binance | 加密和数字货币"
    tw = draw.textlength(ft_txt, font=get_font(12))
    draw.text(((img_w - tw) / 2, y), ft_txt, fill=GRAY, font=get_font(12))

    return img

# ============ 钉钉推送 ============
def dingtalk_signed_url():
    ts = str(round(time.time() * 1000))
    mac = hmac.new(DINGTALK_SECRET.encode(), f"{ts}\n{DINGTALK_SECRET}".encode(), hashlib.sha256)
    sign = urllib.parse.quote(base64.b64encode(mac.digest()), safe="")
    return f"{DINGTALK_WEBHOOK}&timestamp={ts}&sign={sign}"

def dingtalk_post(payload):
    return requests.post(dingtalk_signed_url(), json=payload, timeout=15).json()

def upload_to_imgur(img_bytes):
    try:
        r = requests.post("https://api.imgur.com/3/image",
            headers={"Authorization": "Client-ID 546c25a59c58ad7"},
            data={"image": base64.b64encode(img_bytes).decode()},
            timeout=30)
        data = r.json()
        if data.get("success") and data.get("data", {}).get("link"):
            return data["data"]["link"]
        print(f"  imgur failed: {data}")
    except Exception as e:
        print(f"  imgur error: {e}")
    return None

def send_result(results):
    """发送监控结果到钉钉"""
    tz = timezone(timedelta(hours=8))
    t_str = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

    if not results:
        # 无触发时静默，不发送消息
        print("  No triggers - silent pass.")
        return True

    # 生成图片
    img = create_alert_image(results)
    if not img:
        return False

    # 保存本地
    local = os.path.join(OUTPUT_DIR, "10m_breakout.png")
    img.save(local, "PNG")

    # 上传 imgur
    buf = io.BytesIO()
    img.save(buf, "PNG")
    img_bytes = buf.getvalue()
    print(f"  PNG: {len(img_bytes)/1024:.1f}KB")

    url = upload_to_imgur(img_bytes)
    if not url:
        return False
    print(f"  imgur: {url}")

    # 构建标记文本
    summary = ", ".join([f"{r['symbol'].replace('USDT','')}({r['changePct']:+.2f}%)" for r in results[:10]])
    text = (
        f"# 加密和数字货币 10m Breakout Alert\n\n"
        f"> {t_str} | 触发 {len(results)}/{200}\n\n"
        f"条件：当前10分钟涨跌幅 > 左侧3根10m K线振幅之和\n\n"
        f"![chart]({url})\n\n"
        f"**触发列表**: {summary}"
    )

    # 1. 主发送：link卡片
    r = dingtalk_post({
        "msgtype": "link",
        "link": {
            "title": f"10m Breakout | {t_str} | {len(results)}个触发",
            "text": f"条件: 当前10m涨跌幅 > 左侧3K振幅和 | 加密和数字货币\n触发: {summary[:100]}",
            "picUrl": url,
            "messageUrl": url,
        }
    })
    if r.get("errcode") == 0:
        print("  Link sent OK!")

        # 补充 markdown 消息（全量列表）
        lines = [f"# 10m Breakout 详情 | {t_str}\n"]
        for i, item in enumerate(results):
            sym = item["symbol"].replace("USDT", "")
            d_icon = "+" if item["direction"] == "up" else "-"
            lines.append(
                f"{i+1}. {sym} {d_icon}{item['changePct']:.2f}% | "
                f"振幅和={fmt_price(item['ampSum'])} | "
                f"{item['ratio']}x | "
                f"24h:{item['priceChange24h']:+.2f}%"
            )
        detail_md = "\n".join(lines)
        detail_md += f"\n\n---\n> {t_str} | Binance | 加密和数字货币"

        dingtalk_post({
            "msgtype": "markdown",
            "markdown": {"title": "10m Breakout 详情", "text": detail_md}
        })

        return True

    print(f"  Link failed: {r}")

    # 2. Fallback: markdown
    r = dingtalk_post({
        "msgtype": "markdown",
        "markdown": {"title": "10m Breakout Alert", "text": text}
    })
    return r.get("errcode") == 0

# ============ 主逻辑 ============
def main():
    print("=" * 60)
    print("10m Breakout Monitor: |C-O| > 0.5*sum(amp[3])")
    print("=" * 60)

    # Step 1: Get pairs
    print("\n[1/3] Get top USDT pairs...")
    pairs = get_top_usdt_pairs(200)
    print(f"  {len(pairs)} pairs")

    # Step 2: Scan for breakout signals
    print("\n[2/3] Scan 10m K-lines for breakouts...")
    triggered = scan_all_pairs(pairs)
    print(f"\n  => {len(triggered)} pairs triggered the condition")

    if triggered:
        print("-" * 72)
        print(f"{'#':<3} {'Symbol':<10} {'Dir':<5} {'Chg%':>8} {'AmpSum':>10} {'Ratio':>6} {'Close':>12} {'24h%':>8}")
        print("-" * 72)
        for i, r in enumerate(triggered):
            sym = r["symbol"].replace("USDT", "")
            print(f"{i+1:<3} {sym:<10} {r['direction']:<5} {r['changePct']:>+9.3f}% "
                  f"{fmt_price(r['ampSum']):>10} {r['ratio']:>5.1f}x "
                  f"{fmt_price(r['close']):>12} {r['priceChange24h']:>+7.2f}%")
        print("-" * 70)

    # Step 3: Alert
    print("\n[3/3] Send to DingTalk...")
    success = send_result(triggered)

    if success:
        print("\nDone!")
    else:
        print("\nSend failed!")

    return True

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
