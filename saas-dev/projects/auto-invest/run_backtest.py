"""
バックテスト CLI ランナー

使い方:
  python run_backtest.py --bot short --years 3
  python run_backtest.py --bot medium --start 2022-01-01 --end 2024-12-31
  python run_backtest.py --bot short --years 2 --plot
  python run_backtest.py --bot short --years 3 --save

オプション:
  --bot     short / medium (default: short)
  --years   過去N年 (default: 3)
  --start   開始日 YYYY-MM-DD (--yearsより優先)
  --end     終了日 YYYY-MM-DD (default: 今日)
  --balance 初期資金 USD (default: 10000)
  --plot    エクイティカーブをグラフ表示
  --save    結果をJSONとPNGで保存
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent / "shared"))

from backtest_engine import BacktestEngine


def parse_args():
    p = argparse.ArgumentParser(description="バックテストランナー")
    p.add_argument("--bot",     default="short",
                   choices=["short", "medium", "trend", "volt", "attack"],
                   help="ボット種別 (short/medium/trend/volt/attack)")
    p.add_argument("--years",   type=int,   default=3,
                   help="過去N年分を検証 (default: 3)")
    p.add_argument("--start",   default=None,
                   help="開始日 YYYY-MM-DD")
    p.add_argument("--end",     default=None,
                   help="終了日 YYYY-MM-DD (default: 今日)")
    p.add_argument("--balance", type=float, default=10_000.0,
                   help="初期資金 USD (default: 10000)")
    p.add_argument("--interval", default="1d",
                   choices=["1d", "1h"],
                   help="バー間隔 1d=日足(default) / 1h=時間足(SHORTのみ・最大730日)")
    p.add_argument("--plot",    action="store_true",
                   help="グラフを表示する")
    p.add_argument("--save",    action="store_true",
                   help="結果をJSONとPNGファイルに保存する")
    return p.parse_args()


def main():
    args = parse_args()

    # 日付を決定
    end_date = args.end or datetime.now().strftime("%Y-%m-%d")
    if args.start:
        start_date = args.start
    else:
        start_date = (datetime.now() - timedelta(days=365 * args.years)).strftime("%Y-%m-%d")

    print(f"\n{'='*55}")
    print(f"  バックテスト開始")
    print(f"  Bot: {args.bot.upper()}  期間: {start_date} → {end_date}")
    print(f"  初期資金: ${args.balance:,.0f}")
    print(f"{'='*55}")

    # エンジン実行
    engine = BacktestEngine(bot_type=args.bot, initial_balance=args.balance)
    try:
        result = engine.run(start=start_date, end=end_date, interval=args.interval)
    except Exception as e:
        print(f"\n[ERROR] バックテスト失敗: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # レポート出力
    result.print_report()

    # 保存 / プロット
    if args.save or args.plot:
        data_dir = Path(__file__).parent / "data"
        data_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = data_dir / f"backtest_{args.bot.lower()}_{ts}"

        if args.save:
            result.save_json(str(base) + ".json")

        if args.plot or args.save:
            save_png = str(base) + ".png" if args.save else None
            result.plot(save_path=save_png)


if __name__ == "__main__":
    main()
