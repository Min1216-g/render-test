# Market Scanner 최적화 리포트

생성일: 2026-06-23

## 1) 병목 원인 요약

- 모바일 업데이트 버튼이 `/api/scanner/run` 중심으로 동작해, 사용자가 누른 직후에도 무거운 스캐너 작업 상태에 묶이는 구조였다.
- Render 서버는 스캐너 실행 시 뉴스/AI/모바일 보강 작업을 한 번에 실행하면서 메모리 피크가 커질 수 있었다.
- `adaptive_news_impact_state.json` 같은 학습 상태 파일이 계속 커져 디스크와 메모리 부담이 증가했다.
- 서버 API는 결과 CSV 캐시를 무효화하긴 했지만, 사용자가 “빠른 데이터 재조회”만 하고 싶은 경우에도 무거운 스캐너 흐름과 섞여 있었다.

## 2) 삭제/축소한 것

- 모바일 뉴스 학습 상태 저장 방식을 공백 없는 JSON으로 변경해 파일 크기 증가를 줄였다.
- `adaptive_news_impact_state.json`의 관측치/패턴/키워드 누적 개수를 제한했다.
  - 관측치 기본 최대 1200개
  - 패턴 기본 최대 80개
  - 키워드 기본 최대 80개
- 서버 스캐너 실행 시 임시 캐시 무효화 후 `gc.collect()`를 호출해 큰 CSV/임시 배열 참조를 더 빨리 해제하도록 했다.
- Render 서버 스캔 기본값에서 무거운 1분봉 분석을 비활성화했다.

## 3) 구조 변경 사항

- 서버에 `POST /api/refresh/quick` 추가.
  - 무거운 스캐너를 실행하지 않는다.
  - 결과 캐시만 무효화하고 현재 최신 CSV 스냅샷을 즉시 다시 읽는다.
  - 모바일에서 먼저 호출해 “바로 반영되는 느낌”을 만든다.
- 모바일 앱 업데이트 버튼 흐름 변경.
  - 1단계: quick refresh 호출
  - 2단계: 최신 CSV 즉시 재조회
  - 3단계: 현재가 빠른 갱신
  - 4단계: 백그라운드 스캐너 실행 요청
- 서버 스캐너 실행 환경 기본 제한 추가.
  - `MARKET_SCANNER_MAX_WORKERS=4`
  - `MARKET_SCANNER_MAX_STOCKS=550`
  - `MARKET_SCANNER_ENABLE_INTRADAY_1M=false`
  - `MOBILE_INTEL_MAX_NEWS_OBSERVATIONS=1200`
- Render 설정(`render.yaml`)에도 같은 제한값을 반영했다.

## 4) 성능 개선 포인트

- 업데이트 버튼 즉시 반응:
  - 기존: 스캐너 실행 상태에 묶여 체감상 오래 대기
  - 변경: quick refresh 후 기존 최신 CSV를 먼저 즉시 재로드
- 메모리 피크 감소:
  - Render 스캐너 워커 수를 낮춰 외부 API/뉴스/분석 동시 실행 폭을 줄였다.
  - 1분봉 분석을 서버 스캔에서 꺼서 데이터 요청량과 임시 데이터 크기를 줄였다.
  - 모바일 뉴스 학습 상태 파일을 제한해 반복 실행 시 누적 메모리/디스크 부담을 낮췄다.
- 진단성 개선:
  - API 응답 헤더에 `X-Process-RSS-MB` 추가.
  - 느린 API와 핵심 API 호출 시 `[API]` 로그 출력.
  - 스캐너 단계별 `[MEM]` 로그 출력.

## 5) 검증 결과

- Python 컴파일 확인 완료.
  - `server.py`
  - `mobile_intelligence_feed.py`
  - `render_mobile_refresh.py`
  - `run_market_scanner_update.py`
- 서버 import 확인 완료.
  - 현재 로컬 결과 스냅샷: 550 rows / 545 ok rows
- iOS 앱 빌드 성공.

## 6) 추가 권장 사항

- Render 무료 Web Service에서 전체 스캐너까지 직접 오래 돌리는 구조는 여전히 한계가 있다.
- 장기적으로는 Web Service와 Scanner Worker를 분리하는 것이 가장 안정적이다.
  - Web Service: `/api/results`, `/api/status`, quick refresh만 담당
  - Cron/Worker: 스캐너 실행 후 `/api/results/upload`로 업로드
- 뉴스 원문/AI 심층 분석은 보유종목, 관심종목, 추천 후보 상위 종목만 대상으로 더 좁히는 것이 좋다.
- Render 로그에서 `[MEM] scanner-partial-data`, `[MEM] scanner-completed`, `[API] /api/results`를 보면 다음 병목을 정확히 잡을 수 있다.
