# Telegram Research Lab

별도 Telegram 기반 AI Research 테스트 시스템입니다. 기존 모바일 앱, 기존 Scanner, 기존 AI SCORE 로직을 교체하지 않고 `market_scanner_results.csv`를 읽기 전용으로 참고합니다.

## 참고 구조

- TauricResearch TradingAgents: Technical, Fundamental, News/Sentiment, Bull, Bear, Risk, Final Decision 구조를 아이디어로만 참고
- 라이선스: TauricResearch/TradingAgents GitHub 기준 Apache-2.0
- 논문: `TradingAgents: Multi-Agents LLM Financial Trading Framework`

TradingAgents 코드는 복사하지 않았고, 현재 프로젝트 데이터 구조에 맞춰 독립 Research Engine으로 새로 구현했습니다.

## 보안

Bot Token은 코드에 저장하지 않습니다.

```bash
export TELEGRAM_BOT_TOKEN="새 BotFather 토큰"
export RESEARCH_ALLOWED_CHAT_ID="8749935590"
```

토큰은 GitHub, README, 로그, Telegram 메시지에 출력하지 않습니다. 현재 노출된 토큰이 있다면 운영 전에 BotFather에서 새 토큰으로 교체해야 합니다.

## 실행

CLI 테스트:

```bash
python3 -m research_lab.cli research NVDA
python3 -m research_lab.cli compare NVDA
python3 -m research_lab.cli hot --limit 10
python3 -m research_lab.cli history
python3 -m research_lab.cli stats
python3 -m research_lab.cli detail NVDA
```

Telegram Bot:

```bash
python3 -m research_lab.telegram_bot
```

## Telegram 명령어

- `/research TICKER`
- `/compare TICKER`
- `/hot`
- `/research history`
- `/research stats`
- `/research detail TICKER`
- `/comparison start 40`
- `/comparison sample 6`
- `/comparison update`
- `/comparison report`

허용 Chat ID는 기본값 `8749935590`이며, 다른 Chat ID 요청은 `ACCESS_DENIED`로 처리합니다.

## Paper Testing

Research 결과는 `research_lab/data/research_history.jsonl`에 저장됩니다. 분석 당시 가격을 `entry_reference`로 저장하고, `/research stats` 또는 `paper-update` 실행 시 1D/3D/5D/10D 경과 여부를 확인해 이후 수익률만 기록합니다.

분석 당시 이후에 생긴 데이터를 과거 판단에 섞지 않도록, 과거 Research 점수와 판단은 재계산하지 않습니다.

## Existing AI vs Research AI 비교 테스트

이 비교 시스템은 기존 scanner 결과 CSV를 같은 시점의 snapshot으로 읽고, 동일한 `reference_timestamp`와 `reference_price`를 기준으로 기존 AI와 Research AI의 판단을 저장합니다.

```bash
python3 -m research_lab.cli comparison sample --limit 6
python3 -m research_lab.cli comparison start --limit 40
python3 -m research_lab.cli comparison update
python3 -m research_lab.cli comparison report
python3 -m research_lab.cli daily due
python3 -m research_lab.cli daily run --send-telegram
python3 -m research_lab.cli daily cumulative --days 30
```

저장 위치:

```text
research_lab/data/comparison_history.jsonl
```

비교 항목:

- 방향성: UP / DOWN / SIDEWAYS
- 예상 강도: 약한 상승 / 보통 상승 / 강한 상승 / 하락/관망
- 위험 판단: LOW / MEDIUM / HIGH
- 1H / 장마감 / 1D / 3D / 5D 수익률
- 급등주, 급락주, 거래량 급증, 뉴스 발생 종목, 이미 많이 오른 종목

중요 원칙:

- 기존 `market_scanner.py`, 모바일 앱, 기존 SCORE 계산식은 수정하지 않습니다.
- Research는 기존 CSV를 읽기 전용으로만 사용합니다.
- 이후 평가를 업데이트할 때도 과거 Research 판단은 재계산하지 않습니다.
- 처음에는 최대 40개 정도의 다양한 표본으로 시작하고, 최소 100개 이상의 샘플이 쌓인 뒤 성능을 판단합니다.

## 장마감 Daily Winner

장 종료 후 자동 runner가 실행되면 당일 `comparison_history.jsonl`에 저장된 같은 snapshot 기준 분석을 불러와 실제 종가/장중 고가/저가를 조회하고 Daily Winner를 계산합니다.

```bash
python3 -m research_lab.daily_runner
```

수동 점검:

```bash
python3 -m research_lab.cli daily due
python3 -m research_lab.cli daily run
python3 -m research_lab.cli daily calculate --market US --date 2026-08-18
python3 -m research_lab.cli daily cumulative --days 7
python3 -m research_lab.cli daily cumulative --days 14
python3 -m research_lab.cli daily cumulative --days 30
```

저장 위치:

```text
research_lab/data/daily_comparison_results.jsonl
```

중복 방지:

- `US_DAILY_RESULT_YYYY-MM-DD`
- `KOREA_DAILY_RESULT_YYYY-MM-DD`

이미 저장된 Daily Result는 다시 생성하거나 Telegram으로 중복 전송하지 않습니다. 서버 재시작 후에도 같은 저장 파일을 확인해서 중복 전송을 막습니다.

Daily Score는 Direction, Return, Risk, Momentum, News, Continuation 항목으로 계산하고, `DATA_UNAVAILABLE` 항목은 제외한 뒤 남은 항목 비율로 재계산합니다.
