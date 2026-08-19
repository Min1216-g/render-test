import re
import stat
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
SECRET_FILES = [
    ".env",
    ".env.backtest",
    ".env.market_scanner",
    ".env.market_briefing",
    ".env.quiet_money",
    ".env.telegram_query",
    ".env.news_pulse",
    ".env.us_leader_watch",
    ".env.us_under20_scanner",
    ".env.canada_leader_watch",
    ".env.mobile_market",
    ".env.mobile_update",
]
SCAN_FILES = [
    "server.py",
    "render_mobile_refresh.py",
    "render_cron_runner.py",
    "run_market_scanner_update.py",
    "mobile_market_app.py",
    "bot",
    "telegram_stock_query.py",
    "quiet_money_scanner.py",
    "market_briefing_bot.py",
    "news_pulse_tracker.py",
    "market_scanner.py",
    "backtest_engine.py",
    "us_leader_watch.py",
    "canada_leader_watch.py",
    "us_under20_scanner.py",
    "today_hot_predictor.py",
    "investment_horizon_recommender.py",
    "ops_guard.py",
    ".vscode/settings.json",
    ".vscode/tasks.json",
]
SOURCE_GLOBS = ["*.py", "bot", "MarketScannerIOS/MarketScannerIOS/*.swift", "*.js"]
TOKEN_PATTERN = re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{25,}\b")
EXTERNAL_HTTP_URL_PATTERN = re.compile(r"http://(?!localhost\b|127\.0\.0\.1\b|\[::1\])[^ \t\r\n\"'<>),]+")
HTTP_REQUEST_CONTEXT_PATTERN = re.compile(r"\b(requests|HTTP)\.(get|post|put|patch|delete|request)\s*\(")
GENERIC_SECRET_PATTERN = re.compile(
    r"(?i)\b("
    r"api[_-]?key|api[_-]?secret|secret[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"app[_-]?key|app[_-]?secret|client[_-]?id|client[_-]?secret|"
    r"kis[_-]?app[_-]?key|kis[_-]?app[_-]?secret|dart[_-]?api[_-]?key|"
    r"naver[_-]?client[_-]?id|naver[_-]?client[_-]?secret|"
    r"openai[_-]?api[_-]?key|alpha[_-]?vantage[_-]?key|finnhub[_-]?key"
    r")\b"
)
ASSIGNMENT_PATTERN = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*=\s*(.+?)\s*$")
KNOWN_PLACEHOLDERS = {
    "",
    "none",
    "null",
    "false",
    "true",
    "your_api_key_here",
    "your_key_here",
    "your_secret_here",
    "YOUR_BACKTEST_BOT_TOKEN_HERE",
    "YOUR_MARKET_SCANNER_BOT_TOKEN_HERE",
    "YOUR_CHAT_ID_HERE",
}
REQUIRED_GITIGNORE_PATTERNS = [
    ".env",
    ".env.*",
    "__pycache__/",
    "*.pyc",
    ".scanner-*.log",
    "*.tmp",
]
QUERY_BOT_FILE = BASE_DIR / "telegram_stock_query.py"
QUERY_ALLOWED_CHAT_KEYS = ["QUERY_ALLOWED_CHAT_ID", "QUERY_ALLOWED_CHAT_IDS"]
ALERT_CHAT_KEYS = [
    "CHAT_ID",
    "MARKET_SCANNER_CHAT_ID",
    "BACKTEST_CHAT_ID",
    "BRIEFING_CHAT_ID",
    "QUIET_MONEY_CHAT_ID",
    "NEWS_PULSE_CHAT_ID",
    "US_LEADER_CHAT_ID",
    "US_UNDER20_CHAT_ID",
    "CANADA_LEADER_CHAT_ID",
]


def make_issue(level, message, fixable=False, fix=None):
    return {
        "level": level,
        "message": message,
        "fixable": fixable,
        "fix": fix,
    }


def mask(value):
    if len(value) <= 10:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def read_env_values():
    env_values = {}
    for filename in SECRET_FILES:
        path = BASE_DIR / filename
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env_values[key.strip()] = value.strip().strip('"').strip("'")
    return env_values


def check_secret_permissions():
    issues = []
    for filename in SECRET_FILES:
        path = BASE_DIR / filename
        if not path.exists():
            continue
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            issues.append(
                make_issue(
                    "HIGH",
                    f"{filename}: 권한이 느슨함({oct(mode)}), chmod 600 권장",
                    fixable=True,
                    fix=lambda p=path: p.chmod(0o600),
                )
            )
    return issues


def check_plain_tokens():
    issues = []
    for filename in SCAN_FILES:
        path = BASE_DIR / filename
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in TOKEN_PATTERN.findall(text):
            issues.append(make_issue("HIGH", f"{filename}: 코드/설정 파일에 토큰 노출 의심 {mask(match)}"))
    return issues


def is_probably_real_secret(value):
    cleaned = value.strip().strip('"').strip("'")
    if cleaned in KNOWN_PLACEHOLDERS or cleaned.lower() in KNOWN_PLACEHOLDERS:
        return False
    if len(cleaned) < 12:
        return False
    return any(char.isdigit() for char in cleaned) and any(char.isalpha() for char in cleaned)


def check_env_api_keys():
    issues = []
    for filename in SECRET_FILES:
        path = BASE_DIR / filename
        if not path.exists():
            continue

        for line_number, raw_line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
            if not raw_line.strip() or raw_line.strip().startswith("#"):
                continue

            match = ASSIGNMENT_PATTERN.match(raw_line)
            if not match:
                continue

            key, value = match.groups()
            if GENERIC_SECRET_PATTERN.search(key) and is_probably_real_secret(value):
                issues.append(make_issue("MEDIUM", f"{filename}:{line_number}: API/증권 키 감지 {key}={mask(value.strip())}"))

    return issues


def check_code_api_keys():
    issues = []
    for filename in SCAN_FILES:
        path = BASE_DIR / filename
        if not path.exists():
            continue
        for line_number, raw_line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
            if GENERIC_SECRET_PATTERN.search(raw_line) and "=" in raw_line:
                if "secrets.token_urlsafe" in raw_line or "os.getenv" in raw_line:
                    continue
                match = ASSIGNMENT_PATTERN.match(raw_line)
                if match and is_probably_real_secret(match.group(2)):
                    issues.append(make_issue("HIGH", f"{filename}:{line_number}: 코드 내 API 키 하드코딩 의심"))

    return issues


def iter_source_files():
    seen = set()
    for pattern in SOURCE_GLOBS:
        for path in BASE_DIR.glob(pattern):
            if path.is_file() and path not in seen:
                seen.add(path)
                yield path


def check_insecure_http_urls():
    issues = []
    for path in iter_source_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            if "http://" not in raw_line:
                continue
            if path.name == "security_check.py":
                continue
            if "DOCTYPE" in raw_line or "DTD" in raw_line:
                continue
            urls = EXTERNAL_HTTP_URL_PATTERN.findall(raw_line)
            if not urls and HTTP_REQUEST_CONTEXT_PATTERN.search(raw_line):
                urls = ["http://"]
            if not urls:
                continue
            issues.append(make_issue("HIGH", f"{path.relative_to(BASE_DIR)}:{line_number}: HTTPS가 아닌 URL 사용"))
    return issues


def check_dangerous_execution_patterns():
    issues = []
    patterns = [
        (re.compile(r"\bos\.system\s*\("), "os.system 사용"),
        (re.compile(r"\bshell\s*=\s*True\b"), "shell=True 사용"),
        (re.compile(r"\beval\s*\("), "eval 사용"),
        (re.compile(r"\bexec\s*\("), "exec 사용"),
        (re.compile(r"\byaml\.load\s*\("), "yaml.load 사용"),
    ]
    for path in iter_source_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            if path.name == "security_check.py":
                continue
            for pattern, label in patterns:
                if pattern.search(raw_line):
                    issues.append(make_issue("HIGH", f"{path.relative_to(BASE_DIR)}:{line_number}: 위험 실행 패턴 감지({label})"))
    return issues


def check_requests_ssl_disabled():
    issues = []
    for path in iter_source_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            if path.name == "security_check.py":
                continue
            if "verify=False" in raw_line.replace(" ", ""):
                issues.append(make_issue("HIGH", f"{path.relative_to(BASE_DIR)}:{line_number}: SSL 검증 비활성화"))
    return issues


def check_requirements_pinned():
    issues = []
    path = BASE_DIR / "requirements.txt"
    if not path.exists():
        issues.append(make_issue("MEDIUM", "requirements.txt 없음: 의존성 추적 불가"))
        return issues
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "==" not in line:
            issues.append(make_issue("MEDIUM", f"requirements.txt:{line_number}: 버전 고정 필요({line})"))
    return issues


def append_gitignore_patterns(path, missing_patterns):
    existing = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    with path.open("a", encoding="utf-8") as file:
        if existing and not existing.endswith("\n"):
            file.write("\n")
        for pattern in missing_patterns:
            file.write(f"{pattern}\n")


def append_env_assignment(path, key, value):
    existing = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    with path.open("a", encoding="utf-8") as file:
        if existing and not existing.endswith("\n"):
            file.write("\n")
        file.write(f"{key}={value}\n")


def check_gitignore():
    path = BASE_DIR / ".gitignore"
    if not path.exists():
        return [
            make_issue(
                "MEDIUM",
                ".gitignore 없음: .env 파일이 git에 들어갈 수 있음",
                fixable=True,
                fix=lambda p=path: append_gitignore_patterns(p, REQUIRED_GITIGNORE_PATTERNS),
            )
        ]

    text = path.read_text(encoding="utf-8", errors="ignore")
    missing = [pattern for pattern in REQUIRED_GITIGNORE_PATTERNS if pattern not in text]
    if not missing:
        return []
    return [
        make_issue(
            "MEDIUM",
            f".gitignore 누락: {', '.join(missing)}",
            fixable=True,
            fix=lambda p=path, patterns=missing: append_gitignore_patterns(p, patterns),
        )
    ]


def check_query_allowed_chat_id():
    issues = []
    env_values = read_env_values()
    raw_value = ""
    used_key = ""
    for key in QUERY_ALLOWED_CHAT_KEYS:
        value = env_values.get(key, "").strip()
        if value:
            raw_value = value
            used_key = key
            break

    if not raw_value:
        default_chat_id = env_values.get("CHAT_ID", "").strip()
        issues.append(
            make_issue(
                "HIGH",
                "조회용 봇 허용 chat_id 미설정: .env에 QUERY_ALLOWED_CHAT_ID 1개를 명시하세요",
                fixable=bool(default_chat_id),
                fix=(lambda p=BASE_DIR / ".env", chat_id=default_chat_id: append_env_assignment(p, "QUERY_ALLOWED_CHAT_ID", chat_id)) if default_chat_id else None,
            )
        )
        return issues

    ids = [value.strip() for value in raw_value.split(",") if value.strip()]
    if len(ids) != 1:
        issues.append(
            make_issue(
                "HIGH",
                f"{used_key}: 허용 chat_id는 1개만 허용해야 함(현재 {len(ids)}개)",
            )
        )

    for chat_id in ids:
        if not chat_id.isdigit():
            issues.append(make_issue("HIGH", f"{used_key}: chat_id는 숫자여야 함"))

    return issues


def check_alert_chat_ids():
    issues = []
    env_values = read_env_values()
    for key in ALERT_CHAT_KEYS:
        value = env_values.get(key, "").strip()
        if not value:
            issues.append(make_issue("MEDIUM", f"{key}: 알림 전용 chat_id 미설정"))
            continue
        ids = [item.strip() for item in value.split(",") if item.strip()]
        if len(ids) != 1:
            issues.append(make_issue("HIGH", f"{key}: 알림 chat_id는 1개만 사용해야 함"))
        elif not ids[0].isdigit():
            issues.append(make_issue("HIGH", f"{key}: chat_id는 숫자여야 함"))
    return issues


def check_query_command_whitelist():
    issues = []
    if not QUERY_BOT_FILE.exists():
        return issues

    text = QUERY_BOT_FILE.read_text(encoding="utf-8", errors="ignore")
    if "ALLOWED_CHAT_IDS" not in text:
        issues.append(make_issue("HIGH", "telegram_stock_query.py: 허용 chat_id 체크 코드 없음"))
    if "ALLOWED_COMMANDS" not in text:
        issues.append(make_issue("HIGH", "telegram_stock_query.py: 명령어 whitelist 없음"))
    if "ALLOWED_QUERY_PREFIXES" not in text:
        issues.append(make_issue("HIGH", "telegram_stock_query.py: 허용된 조회 명령 prefix 제한 없음"))
    if "허용되지 않은 명령입니다" not in text:
        issues.append(make_issue("MEDIUM", "telegram_stock_query.py: 비허용 명령 차단 응답 없음"))
    return issues


def check_tokens_in_env_only():
    issues = []
    env_values = read_env_values()
    token_keys = [
        "BOT_TOKEN",
        "MARKET_SCANNER_BOT_TOKEN",
        "BACKTEST_BOT_TOKEN",
        "BRIEFING_BOT_TOKEN",
        "QUIET_MONEY_BOT_TOKEN",
        "NEWS_PULSE_BOT_TOKEN",
        "US_LEADER_BOT_TOKEN",
        "US_UNDER20_BOT_TOKEN",
        "CANADA_LEADER_BOT_TOKEN",
        "QUERY_BOT_TOKEN",
    ]
    missing = [key for key in token_keys if not env_values.get(key, "").strip()]
    for key in missing:
        issues.append(make_issue("MEDIUM", f"{key}: .env 계열 파일에 토큰 미설정"))
    return issues


def check_runtime_guard_enabled():
    issues = []
    guarded_files = [
        "bot",
        "telegram_stock_query.py",
        "quiet_money_scanner.py",
        "market_briefing_bot.py",
        "news_pulse_tracker.py",
        "market_scanner.py",
        "backtest_engine.py",
        "us_leader_watch.py",
        "us_under20_scanner.py",
        "today_hot_predictor.py",
        "investment_horizon_recommender.py",
    ]
    for filename in guarded_files:
        path = BASE_DIR / filename
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "enforce_runtime_security" not in text:
            issues.append(make_issue("HIGH", f"{filename}: 공통 보안/오래된 정보 정리 장치 미적용"))
    return issues


def collect_issues():
    issues = []
    issues.extend(check_secret_permissions())
    issues.extend(check_plain_tokens())
    issues.extend(check_env_api_keys())
    issues.extend(check_code_api_keys())
    issues.extend(check_insecure_http_urls())
    issues.extend(check_dangerous_execution_patterns())
    issues.extend(check_requests_ssl_disabled())
    issues.extend(check_requirements_pinned())
    issues.extend(check_gitignore())
    issues.extend(check_query_allowed_chat_id())
    issues.extend(check_alert_chat_ids())
    issues.extend(check_query_command_whitelist())
    issues.extend(check_tokens_in_env_only())
    issues.extend(check_runtime_guard_enabled())
    return issues


def apply_fixes(issues):
    fixed = 0
    for issue in issues:
        if issue["fixable"] and issue["fix"]:
            issue["fix"]()
            fixed += 1
    return fixed


def print_issues(issues):
    severity_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    for issue in sorted(issues, key=lambda item: severity_order.get(item["level"], 99)):
        fix_label = "자동수정 가능" if issue["fixable"] else "수동확인 필요"
        print(f"- [{issue['level']}] {issue['message']} ({fix_label})")


def summarize_issues(issues):
    counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for issue in issues:
        level = issue.get("level", "LOW")
        counts[level] = counts.get(level, 0) + 1

    summary = ", ".join(
        f"{level} {count}"
        for level, count in [("HIGH", counts.get("HIGH", 0)), ("MEDIUM", counts.get("MEDIUM", 0)), ("LOW", counts.get("LOW", 0))]
        if count
    )
    return summary or "이슈 없음"


def run_security_check(fix_mode=False):
    issues = collect_issues()
    fixed = 0

    if fix_mode and issues:
        fixed = apply_fixes(issues)
        issues = collect_issues()

    return {
        "ok": not issues,
        "fixed": fixed,
        "issues": issues,
        "summary": summarize_issues(issues),
    }


def main():
    fix_mode = "--fix" in sys.argv
    result = run_security_check(fix_mode=fix_mode)
    issues = result["issues"]
    fixed = result["fixed"]

    if fix_mode and fixed:
        print(f"자동 수정 완료: {fixed}개")

    if issues:
        print("보안 점검 결과: 확인 필요")
        print_issues(issues)
        return

    print("보안 점검 결과: 기본 점검 통과")


if __name__ == "__main__":
    main()
