import os
import re
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd


DEFAULT_OUTPUT_RETENTION_DAYS = 14
DEFAULT_HISTORY_RETENTION_DAYS = 45
DEFAULT_PRICE_CACHE_RETENTION_DAYS = 3
DEFAULT_LOG_RETENTION_DAYS = 7
SECURE_FILE_MODE = 0o600
SECURE_DIR_MODE = 0o700
DATE_COLUMNS = [
    "run_at",
    "generated_at",
    "comparison_run_at",
    "published_at",
    "entry_time",
    "exit_time",
    "timestamp",
]
TOKEN_PATTERN = r"^\d{8,12}:[A-Za-z0-9_-]{25,}$"
CHAT_ID_PATTERN = r"^\d{6,20}$"
SECRET_VALUE_PATTERNS = [
    re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{25,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?i)(bearer\s+)([A-Za-z0-9._~+/=-]{16,})"),
    re.compile(r"(?i)\b([A-Za-z0-9_]*(?:token|secret|api[_-]?key|password|passwd)[A-Za-z0-9_]*\s*[=:]\s*)([^\s\"']{8,})"),
]
SAFE_TICKER_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,24}$")
SAFE_SEARCH_PATTERN = re.compile(r"^[0-9A-Za-z가-힣ㄱ-ㅎㅏ-ㅣ .,_+:/()%&-]{0,80}$")


def load_env_file(path):
    path = Path(path)
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def mask_secret(value, visible=4):
    if not value:
        return "없음"
    value = str(value)
    if len(value) <= visible * 2:
        return "*" * len(value)
    return f"{value[:visible]}...{value[-visible:]}"


def sanitize_secret(text, *secrets):
    sanitized = str(text)
    for secret in secrets:
        if secret:
            sanitized = sanitized.replace(str(secret), mask_secret(secret))
    for pattern in SECRET_VALUE_PATTERNS:
        def repl(match):
            if pattern.pattern.startswith("(?i)(bearer"):
                return match.group(1) + mask_secret(match.group(2))
            if "(?:token|secret|api" in pattern.pattern:
                return match.group(1) + mask_secret(match.group(2))
            return mask_secret(match.group(0))

        sanitized = pattern.sub(repl, sanitized)
    return sanitized


def enforce_https_url(url, *, allow_localhost=True):
    parsed = urlparse(str(url))
    if parsed.scheme != "https":
        host = (parsed.hostname or "").lower()
        if allow_localhost and host in {"localhost", "127.0.0.1", "::1"}:
            return str(url)
        raise ValueError("HTTPS URL만 허용됩니다.")
    return str(url)


def validate_ticker(value):
    value = str(value or "").strip().upper()
    if not SAFE_TICKER_PATTERN.match(value):
        raise ValueError("허용되지 않는 티커 형식입니다.")
    return value


def validate_search_text(value, *, max_length=80):
    value = str(value or "").strip()
    if len(value) > max_length:
        raise ValueError("검색어가 너무 깁니다.")
    if not SAFE_SEARCH_PATTERN.match(value):
        raise ValueError("검색어에 허용되지 않는 문자가 포함되어 있습니다.")
    return value


def safe_child_path(base_dir, candidate):
    base = Path(base_dir).resolve()
    path = (base / str(candidate)).resolve()
    if base != path and base not in path.parents:
        raise ValueError("허용된 폴더 밖의 경로 접근은 차단됩니다.")
    return path


def secure_file_permissions(path, mode=SECURE_FILE_MODE):
    path = Path(path)
    if not path.exists() or not path.is_file():
        return False
    current_mode = stat.S_IMODE(path.stat().st_mode)
    if current_mode != mode:
        path.chmod(mode)
        return True
    return False


def secure_directory_permissions(path, mode=SECURE_DIR_MODE):
    path = Path(path)
    if not path.exists() or not path.is_dir():
        return False
    current_mode = stat.S_IMODE(path.stat().st_mode)
    if current_mode & (stat.S_IRWXG | stat.S_IRWXO):
        path.chmod(mode)
        return True
    return False


def read_retention_days(env_key, default):
    raw_value = os.getenv(env_key, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError:
        return default
    return max(0, value)


def is_stale(path, retention_days, now=None):
    if retention_days <= 0:
        return False
    path = Path(path)
    if not path.exists():
        return False
    now = now or datetime.now(timezone.utc)
    modified_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    return modified_at < now - timedelta(days=retention_days)


def delete_stale_file(path, retention_days, now=None):
    path = Path(path)
    if not path.exists() or not path.is_file():
        return False
    if not is_stale(path, retention_days, now):
        return False
    path.unlink()
    return True


def cleanup_stale_directory_files(directory, retention_days, patterns=None, now=None):
    directory = Path(directory)
    if not directory.exists() or not directory.is_dir():
        return 0
    patterns = patterns or ["*"]
    removed = 0
    for pattern in patterns:
        for path in directory.glob(pattern):
            if path.is_file() and delete_stale_file(path, retention_days, now):
                removed += 1
    return removed


def trim_csv_by_date(path, retention_days, date_columns=None):
    path = Path(path)
    if retention_days <= 0 or not path.exists() or not path.is_file() or path.suffix.lower() != ".csv":
        return 0
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except Exception:
        return 0
    if df.empty:
        return 0

    date_columns = date_columns or DATE_COLUMNS
    selected_column = next((column for column in date_columns if column in df.columns), None)
    if not selected_column:
        return 0

    parsed = pd.to_datetime(df[selected_column], errors="coerce", utc=True)
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=retention_days)
    keep_mask = parsed.isna() | (parsed >= cutoff)
    removed = int((~keep_mask).sum())
    if removed <= 0:
        return 0

    df.loc[keep_mask].to_csv(path, index=False, encoding="utf-8-sig")
    secure_file_permissions(path)
    return removed


def generated_output_paths(base_dir):
    base_dir = Path(base_dir)
    names = [
        "analysis_results.csv",
        "analysis_history.csv",
        "backtest_quality_report.csv",
        "backtest_signal_summary.csv",
        "backtest_summary.csv",
        "backtest_trades.csv",
        "context_cache.json",
        "investment_horizon_recommendations.csv",
        "market_briefing_log.csv",
        "market_briefing_state.json",
        "market_scanner_results.csv",
        "canada_leader_watch_results.csv",
        "news_pulse_log.csv",
        "news_pulse_results.csv",
        "news_pulse_state.json",
        "quiet_money_backtest_quality.csv",
        "quiet_money_backtest_summary.csv",
        "quiet_money_backtest_trades.csv",
        "quiet_money_history.csv",
        "quiet_money_results.csv",
        "quiet_money_state.json",
        "signal_state.json",
        "telegram_query_state.txt",
        "today_hot_predictor_results.csv",
        "us_leader_watch_results.csv",
        "us_under20_scanner_results.csv",
    ]
    return [base_dir / name for name in names]


def cleanup_runtime_junk(base_dir, now=None):
    base_dir = Path(base_dir)
    now = now or datetime.now(timezone.utc)
    removed = 0

    # 오래된 런타임 로그 정리
    log_retention_days = read_retention_days("SECURITY_LOG_RETENTION_DAYS", DEFAULT_LOG_RETENTION_DAYS)
    removed += cleanup_stale_directory_files(
        base_dir,
        log_retention_days,
        patterns=["*.log", "*.err.log", "*.out.log"],
        now=now,
    )

    # 파이썬 캐시 정리
    for cache_dir in base_dir.rglob("__pycache__"):
        if cache_dir.is_dir():
            for pyc in cache_dir.glob("*.pyc"):
                try:
                    pyc.unlink()
                    removed += 1
                except OSError:
                    pass

    # 운영 중 생성되는 잡파일 정리
    stale_runtime_files = [
        base_dir / "market_briefing_launchd.log",
        base_dir / "market_briefing_launchd.err.log",
    ]
    for path in stale_runtime_files:
        if delete_stale_file(path, log_retention_days, now):
            removed += 1

    return removed


def validate_secret_env_format(env_files):
    import re

    issues = []
    token_keys = {
        "BOT_TOKEN",
        "MARKET_SCANNER_BOT_TOKEN",
        "BACKTEST_BOT_TOKEN",
        "BRIEFING_BOT_TOKEN",
        "QUIET_MONEY_BOT_TOKEN",
        "QUERY_BOT_TOKEN",
        "NEWS_PULSE_BOT_TOKEN",
        "US_LEADER_BOT_TOKEN",
        "US_UNDER20_BOT_TOKEN",
        "CANADA_LEADER_BOT_TOKEN",
        "MOBILE_UPDATE_BOT_TOKEN",
    }
    chat_keys = {
        "CHAT_ID",
        "MARKET_SCANNER_CHAT_ID",
        "BACKTEST_CHAT_ID",
        "BRIEFING_CHAT_ID",
        "QUIET_MONEY_CHAT_ID",
        "QUERY_DEFAULT_CHAT_ID",
        "QUERY_ALLOWED_CHAT_ID",
        "NEWS_PULSE_CHAT_ID",
        "US_LEADER_CHAT_ID",
        "US_UNDER20_CHAT_ID",
        "CANADA_LEADER_CHAT_ID",
        "MOBILE_UPDATE_CHAT_ID",
    }

    for env_file in env_files:
        path = Path(env_file)
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key in token_keys and value and not re.match(TOKEN_PATTERN, value):
                issues.append(f"{path.name}:{key} format mismatch")
            if key in chat_keys and value and not re.match(CHAT_ID_PATTERN, value):
                issues.append(f"{path.name}:{key} must be numeric")
    return issues


def enforce_runtime_security(base_dir, env_files=None, output_files=None, cleanup=True, quiet=True):
    base_dir = Path(base_dir)
    os.umask(0o077)

    env_files = [Path(path) for path in (env_files or [])]
    for path in env_files:
        secure_file_permissions(path)
    format_issues = validate_secret_env_format(env_files)

    secure_directory_permissions(base_dir / ".price_cache")

    output_files = [Path(path) for path in (output_files or generated_output_paths(base_dir))]
    for path in output_files:
        if path.exists() and path.is_file():
            secure_file_permissions(path)

    if not cleanup:
        return {"deleted_files": 0, "trimmed_rows": 0, "deleted_cache_files": 0}

    output_retention_days = read_retention_days("SECURITY_OUTPUT_RETENTION_DAYS", DEFAULT_OUTPUT_RETENTION_DAYS)
    history_retention_days = read_retention_days("SECURITY_HISTORY_RETENTION_DAYS", DEFAULT_HISTORY_RETENTION_DAYS)
    cache_retention_days = read_retention_days("SECURITY_PRICE_CACHE_RETENTION_DAYS", DEFAULT_PRICE_CACHE_RETENTION_DAYS)

    deleted_files = 0
    trimmed_rows = 0
    now = datetime.now(timezone.utc)
    for path in output_files:
        if delete_stale_file(path, output_retention_days, now):
            deleted_files += 1
            continue
        trimmed_rows += trim_csv_by_date(path, history_retention_days)

    deleted_cache_files = cleanup_stale_directory_files(
        base_dir / ".price_cache",
        cache_retention_days,
        patterns=["*.pkl", "*.csv", "*.json"],
        now=now,
    )
    deleted_junk_files = cleanup_runtime_junk(base_dir, now=now)

    result = {
        "deleted_files": deleted_files,
        "trimmed_rows": trimmed_rows,
        "deleted_cache_files": deleted_cache_files,
        "deleted_junk_files": deleted_junk_files,
        "format_issues": format_issues,
    }
    if not quiet and (deleted_files or trimmed_rows or deleted_cache_files or deleted_junk_files or format_issues):
        print(
            "보안 정리: "
            f"오래된 파일 {deleted_files}개 삭제, "
            f"오래된 CSV 행 {trimmed_rows}개 삭제, "
            f"캐시 {deleted_cache_files}개 삭제, "
            f"런타임 잡파일 {deleted_junk_files}개 삭제",
            flush=True,
        )
        if format_issues:
            print("보안 경고: 환경변수 형식 오류 -> " + ", ".join(format_issues), flush=True)
    return result
