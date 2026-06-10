# -*- coding: utf-8 -*-
# input: D:\freqtrade 的 show_recent_positions 模块、live artifact、交易日历与历史回填日期范围。
# output: snapshots\YYYY-MM-DD 下的历史持仓/收益 JSON、UTF-8 控制台文本与 backfill run_meta.json。
# pos: 仓位审计仓库的历史回填入口；一旦我被更新，务必更新开头注释以及 scripts\FOLDER_README.md。

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

import pandas as pd


os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass


DEFAULT_FREQTRADE_ROOT = Path("D:/freqtrade")
DEFAULT_AUDIT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_START_DATE = "2026-02-15"
DEFAULT_END_DATE = "2026-06-07"
DEFAULT_DAYS = 8


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill historical ETF position audit snapshots."
    )
    parser.add_argument("--freqtrade-root", default=str(DEFAULT_FREQTRADE_ROOT))
    parser.add_argument("--audit-root", default=str(DEFAULT_AUDIT_ROOT))
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=DEFAULT_END_DATE)
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--artifact", default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _load_show_recent_positions(freqtrade_root: Path):
    root_text = str(freqtrade_root.resolve())
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    from user_func.strategies.research.str_etf_v1.live import show_recent_positions as srp

    return srp


def _select_generation_dates(
    trading_calendar: Iterable[str],
    start_date: str,
    end_date: str,
) -> List[str]:
    return [date_str for date_str in trading_calendar if start_date <= date_str <= end_date]


def _history_values_before(history: Any, before_date: str) -> List[float]:
    if not isinstance(history, pd.Series) or history.empty:
        return []
    series = history.dropna().copy()
    series.index = pd.to_datetime(series.index, errors="coerce")
    series = series[series.index.notna()]
    sliced = series[series.index < pd.Timestamp(before_date)]
    return [float(value) for value in sliced.values]


def _history_prediction_for_date(history: Any, date_str: str) -> Optional[float]:
    if not isinstance(history, pd.Series) or history.empty:
        return None
    series = history.dropna().copy()
    series.index = pd.to_datetime(series.index, errors="coerce")
    series = series[series.index.notna()]
    target = pd.Timestamp(date_str)
    if target not in series.index:
        return None
    value = series.loc[target]
    if isinstance(value, pd.Series):
        value = value.iloc[-1]
    if pd.isna(value):
        return None
    return float(value)


def _reset_signal_generators_before(pipeline: Any, first_date: str) -> None:
    if pipeline._signal_generator_cls is None:
        raise RuntimeError("signal generator class is not initialized")

    pipeline._signal_generators = {}
    for symbol in pipeline._symbols:
        generator = pipeline._signal_generator_cls(
            pipeline._signal_method,
            deepcopy(pipeline._signal_config),
        )
        values = _history_values_before(pipeline._prediction_history.get(symbol), first_date)
        if values:
            generator.initialize_from_history(values)
        pipeline._signal_generators[symbol] = generator

    pipeline._signals_history = {}
    pipeline._returns_history = {}
    pipeline._predictions_values_history = {}
    pipeline._dates_history = []


def _compute_daily_return_from_prices(
    prices_df: Optional[pd.DataFrame],
    date_str: str,
) -> float:
    if prices_df is None or "close" not in prices_df.columns:
        return 0.0
    target = pd.Timestamp(date_str)
    if target not in prices_df.index:
        return 0.0
    position = prices_df.index.get_indexer([target])[0]
    if position <= 0:
        return 0.0
    previous_close = float(prices_df["close"].iloc[position - 1])
    current_close = float(prices_df["close"].iloc[position])
    if previous_close == 0.0:
        return 0.0
    return current_close / previous_close - 1.0


def _build_backfill_context(
    srp: Any,
    artifact_dir: Path,
    replay_dates: List[str],
) -> Dict[str, Any]:
    from user_func.strategies.research.str_etf_v1.live.daily_inference_pipeline import (
        DailyInferencePipeline,
    )

    pipeline = DailyInferencePipeline(artifact_dir)
    with contextlib.redirect_stdout(io.StringIO()):
        pipeline.initialize()

    history_end_date = srp._infer_prediction_history_end_date(pipeline)
    _reset_signal_generators_before(pipeline, replay_dates[0])

    factors_cache, prices_cache_runtime = srp._load_runtime_caches(pipeline)
    prices_cache = {
        symbol: srp._prepare_price_frame_for_returns(price_df)
        for symbol, price_df in prices_cache_runtime.items()
    }
    for benchmark_symbol in srp._BENCHMARK_SYMBOLS:
        if benchmark_symbol not in prices_cache:
            benchmark_prices = srp._load_price_frame_for_symbol(benchmark_symbol)
            if benchmark_prices is not None:
                prices_cache[benchmark_symbol] = benchmark_prices

    display_results: List[Dict[str, Any]] = []
    replay_records_by_date: Dict[str, Dict[str, Any]] = {}
    prev_weights = {symbol: 0.0 for symbol in getattr(pipeline, "_symbols", [])}

    for date_str in replay_dates:
        predictions: Dict[str, float] = {}
        signals: Dict[str, float] = {}
        daily_returns: Dict[str, float] = {}

        for symbol in pipeline._symbols:
            prediction = None
            daily_return = 0.0

            if history_end_date and date_str <= history_end_date:
                prediction = _history_prediction_for_date(
                    pipeline._prediction_history.get(symbol),
                    date_str,
                )
                daily_return = _compute_daily_return_from_prices(
                    prices_cache.get(symbol),
                    date_str,
                )
            elif symbol in factors_cache:
                try:
                    prediction, daily_return = pipeline._predict_single_symbol(
                        symbol,
                        date_str,
                        factors_df_cache=factors_cache.get(symbol),
                        prices_df_cache=prices_cache_runtime.get(symbol),
                    )
                except Exception:
                    prediction = None

            if prediction is None:
                continue

            predictions[symbol] = float(prediction)
            daily_returns[symbol] = float(daily_return or 0.0)
            signal = pipeline._signal_generators[symbol].update(float(prediction))
            signals[symbol] = float(max(signal, 0.0))

        raw_weights = pipeline._compute_weights(signals, daily_returns, predictions)
        weights = {
            symbol: float(raw_weights.get(symbol, 0.0))
            for symbol in pipeline._symbols
        }
        raw_target_weights = (
            pipeline._compute_target_weights(signals, predictions)
            if hasattr(pipeline, "_compute_target_weights")
            else pipeline._compute_weights(signals, daily_returns)
        )
        target_weights = {
            symbol: float(raw_target_weights.get(symbol, 0.0))
            for symbol in pipeline._symbols
        }
        current_prev_weights = prev_weights.copy()

        pipeline._update_history(date_str, signals, daily_returns, predictions)

        top_positions = sorted(
            [
                {
                    "symbol": symbol,
                    "weight": round(weight, 4),
                    "signal": signals.get(symbol, 0.0),
                    "prediction": round(predictions.get(symbol, 0.0), 6),
                }
                for symbol, weight in weights.items()
                if weight > 0
            ],
            key=lambda item: item["weight"],
            reverse=True,
        )
        target_positions = sorted(
            [
                {
                    "symbol": symbol,
                    "weight": round(weight, 4),
                    "signal": signals.get(symbol, 0.0),
                    "prediction": round(predictions.get(symbol, 0.0), 6),
                }
                for symbol, weight in target_weights.items()
                if weight > 0
            ],
            key=lambda item: (item["weight"], item["prediction"]),
            reverse=True,
        )

        replay_records_by_date[date_str] = {
            "signal_date": date_str,
            "predictions": predictions,
            "signals": signals,
            "weights": weights,
            "target_weights": target_weights,
            "prev_weights": current_prev_weights,
            "daily_returns": daily_returns,
            "n_predicted": len(predictions),
            "n_with_signal": sum(1 for signal in signals.values() if signal > 0),
            "target_positions": target_positions,
        }
        prev_weights = weights.copy()

        display_results.append(
            {
                "date": date_str,
                "predictions": predictions,
                "signals": signals,
                "weights": weights,
                "target_weights": target_weights,
                "top_positions": top_positions,
                "target_positions": target_positions,
                "n_predicted": len(predictions),
                "n_with_signal": sum(1 for signal in signals.values() if signal > 0),
            }
        )

    return {
        "display_results": display_results,
        "replay_records_by_date": replay_records_by_date,
        "prices_cache": prices_cache,
        "trading_calendar": srp.load_trading_calendar(),
        "effective_fee_rate": srp._resolve_effective_fee_rate(pipeline),
        "history_end_date": history_end_date,
    }


def _save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def _positions_payload(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "date": result["date"],
            "top_positions": result["top_positions"],
            "n_predicted": result["n_predicted"],
            "n_with_signal": result["n_with_signal"],
        }
        for result in results
    ]


def _render_report(
    srp: Any,
    artifact_dir: Path,
    requested_start: str,
    requested_end: str,
    generation_dates: List[str],
    window_results: List[Dict[str, Any]],
    performance_summary: Mapping[str, Any],
    benchmark_summary: Mapping[str, Any],
    history_end_date: Optional[str],
) -> str:
    window_dates = [item["date"] for item in window_results]
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        print(f"[init] Artifact: {artifact_dir}")
        print(f"[init] Backfill requested: {requested_start} → {requested_end}")
        print(
            f"[init] Trading dates: {generation_dates[0]} → "
            f"{generation_dates[-1]} ({len(generation_dates)} days)"
        )
        print(f"[init] Artifact prediction_history end: {history_end_date}")
        print(f"[init] Snapshot date: {window_dates[-1]}")
        print(f"[init] Display dates: {' → '.join(window_dates)}")
        srp.print_comparison_table(window_results)
        srp.print_portfolio_performance_table(performance_summary)
        srp.print_benchmark_performance_table(benchmark_summary, window_dates)
    return buffer.getvalue()


def _write_snapshot(
    srp: Any,
    audit_root: Path,
    artifact_dir: Path,
    requested_start: str,
    requested_end: str,
    generation_dates: List[str],
    window_results: List[Dict[str, Any]],
    context: Mapping[str, Any],
    history_end_date: Optional[str],
    dry_run: bool,
) -> None:
    snapshot_date = window_results[-1]["date"]
    window_dates = [item["date"] for item in window_results]
    snapshot_dir = audit_root / "snapshots" / snapshot_date
    if dry_run:
        print(f"[dry-run] would write {snapshot_dir}")
        return

    performance_summary = srp._compute_recent_portfolio_performance(
        replay_records_by_date=context["replay_records_by_date"],
        prices_cache=context["prices_cache"],
        realized_dates=window_dates,
        trading_calendar=context["trading_calendar"],
        fee_rate=context["effective_fee_rate"],
        verbose=False,
    )
    benchmark_summary = srp._compute_benchmark_performance(
        prices_cache=context["prices_cache"],
        realized_dates=window_dates,
        trading_calendar=context["trading_calendar"],
        verbose=False,
    )

    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "show_recent_positions.txt").write_text(
        _render_report(
            srp=srp,
            artifact_dir=artifact_dir,
            requested_start=requested_start,
            requested_end=requested_end,
            generation_dates=generation_dates,
            window_results=window_results,
            performance_summary=performance_summary,
            benchmark_summary=benchmark_summary,
            history_end_date=history_end_date,
        ),
        encoding="utf-8",
    )
    _save_json(
        snapshot_dir / f"recent_positions_{snapshot_date}.json",
        _positions_payload(window_results),
    )
    _save_json(
        snapshot_dir / f"recent_performance_{snapshot_date}.json",
        {
            "realized_dates": performance_summary["realized_dates"],
            "fee_rate": float(performance_summary["fee_rate"]),
            "portfolio": performance_summary["portfolio"],
            "benchmarks": benchmark_summary,
        },
    )
    _save_json(
        snapshot_dir / "run_meta.json",
        {
            "status": "success",
            "backfill": True,
            "captured_at_utc": datetime.utcnow().isoformat(timespec="microseconds") + "Z",
            "snapshot_date": snapshot_date,
            "requested_start_date": requested_start,
            "requested_end_date": requested_end,
            "actual_start_date": generation_dates[0],
            "actual_end_date": generation_dates[-1],
            "display_dates": window_dates,
            "display_window_days": len(window_dates),
            "artifact_dir": str(artifact_dir),
            "history_end_date": history_end_date,
        },
    )
    print(f"[write] {snapshot_date}: {snapshot_dir}")


def main() -> None:
    args = _parse_args()
    if args.days <= 0:
        raise SystemExit("--days must be positive")

    freqtrade_root = Path(args.freqtrade_root).resolve()
    audit_root = Path(args.audit_root).resolve()
    srp = _load_show_recent_positions(freqtrade_root)

    artifact_dir = srp._resolve_artifact_dir(args.artifact, srp._LIVE_DIR)
    if artifact_dir is None:
        raise SystemExit("artifact not found")

    trading_calendar = srp.load_trading_calendar()
    generation_dates = _select_generation_dates(
        trading_calendar,
        args.start_date,
        args.end_date,
    )
    if not generation_dates:
        raise SystemExit("no trading dates selected")

    print(
        f"[init] selected {len(generation_dates)} trading dates: "
        f"{generation_dates[0]} -> {generation_dates[-1]}"
    )
    context = _build_backfill_context(
        srp=srp,
        artifact_dir=artifact_dir,
        replay_dates=generation_dates,
    )
    results_by_date = {
        result["date"]: result
        for result in context["display_results"]
    }

    for index, snapshot_date in enumerate(generation_dates):
        window_dates = generation_dates[max(0, index - args.days + 1): index + 1]
        window_results = [results_by_date[date_str] for date_str in window_dates]
        _write_snapshot(
            srp=srp,
            audit_root=audit_root,
            artifact_dir=artifact_dir,
            requested_start=args.start_date,
            requested_end=args.end_date,
            generation_dates=generation_dates,
            window_results=window_results,
            context=context,
            history_end_date=context["history_end_date"],
            dry_run=bool(args.dry_run),
        )


if __name__ == "__main__":
    main()
