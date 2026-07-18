# BackTest version2

LTH의 `trade_original.md`와 트레이딩헬퍼 계산 로직을 대조해 만든 독립 백테스터입니다. 이 저장소는 LTH 웹앱과 별도로 설치·실행·배포할 수 있습니다.

## 가장 쉬운 실행

프로젝트 루트에서 다음 명령을 실행합니다. 외부 패키지 설치는 필요하지 않습니다.

```bash
python3 -m lth_backtest.cli serve --open
```

브라우저가 자동으로 열리지 않으면 터미널에 표시된 `http://127.0.0.1:8765`로 접속합니다.

브라우저 UI에서 할 수 있는 작업:

- TQQQ/SOXL, 20/40분할과 기존 호환용 실험적 30분할
- 복리/단리, 기간, 원금, 매도 기준 변경
- 장중 고가 기준과 종가 전용 기준의 결과 자동 비교
- 수수료, 매도 비용, 슬리피지, 무위험 수익률 설정
- 전략/종목 거치식/QLD 거치식 자산 곡선과 낙폭 확인
- CAGR, MDD, 변동성, Sharpe, Sortino, Calmar, 노출도, 회전율
- 모든 체결의 주문가·체결가·현금·수량·T값 추적
- 라운드/월별/연도별 결과와 랜덤 기간 견고성 분석
- JSON, 체결 CSV, 단독 실행형 HTML 리포트 내보내기
- version2 전용 Yahoo 조정 OHLCV 다운로드

브라우저의 `TQQQ · SOXL · QLD 전체 데이터 받기` 버튼은 세 종목의 전체 가용 이력을 오늘 날짜까지 한 번에 갱신합니다.

서버 종료는 실행한 터미널에서 `Ctrl+C`입니다.

## CLI

기존 CSV로 실행:

```bash
python3 -m lth_backtest.cli run TQQQ 40 20000 2020-01-01 2024-12-31 \
  --csv data/TQQQ.csv \
  --json-out results/tqqq.json \
  --html-out results/tqqq.html \
  --csv-out-dir results/tqqq-csv
```

다운로드부터 실행까지:

```bash
python3 -m lth_backtest.cli all SOXL 20 20000 2020-01-01 2024-12-31
```

세 종목 전체 이력만 오늘까지 갱신:

```bash
python3 -m lth_backtest.cli download-all
```

랜덤 기간 비교와 HTML 리포트:

```bash
python3 -m lth_backtest.cli random \
  --symbols TQQQ SOXL --splits 20 40 \
  --start-date 2020-01-01 --end-date 2024-12-31 \
  --count 100 --min-days 60 --seed 42 \
  --html-out results/random.html
```

주요 옵션은 `python3 -m lth_backtest.cli run --help`로 확인합니다. 패키지를 설치했다면 같은 명령을 `lth-backtest run ...` 형태로 실행할 수 있습니다.

## 가격 데이터

필수 CSV 열:

```text
date,open,high,low,close,adj_close,volume
```

- 소문자 헤더와 Yahoo 형식의 `Date`, `Adj Close`를 모두 읽습니다.
- `Adj Close`가 `Close`와 다르면 같은 조정비율을 시가·고가·저가·종가에 적용합니다.
- 중복 날짜, 0 이하 가격, `high < open/close/low`, `low > open/close/high`는 즉시 거부합니다.
- 기본 데이터와 새로 다운로드한 데이터는 저장소의 `data` 디렉터리에 저장합니다.
- 사용자 CSV는 브라우저의 가격 CSV 입력란에 경로를 직접 입력할 수 있습니다.

## 정확한 체결 규칙

| 주문 | 체결 조건 | 기본 체결가 |
|---|---|---|
| LOC 매수 | `당일 종가 <= 주문가` | 당일 종가 |
| LOC 매도 | `당일 종가 >= 주문가` | 당일 종가 |
| 최종 LIMIT 매도 | `당일 고가 >= 목표가` | 목표 지정가 |
| MOC | 거래일 존재 | 당일 종가 |

최종 LIMIT 주문과 LOC 주문은 장 시작 전에 동시에 제출된 것으로 봅니다. LIMIT 매도는 장중 고가로 먼저 판정하고, LOC는 종가로 판정합니다. 따라서 고가가 최종 목표가를 넘은 뒤 종가가 내려오면 다음이 같은 날 함께 발생할 수 있습니다.

1. 시작 보유량 중 최종 지정가에 예약한 수량 매도
2. 쿼터 LOC 매도는 종가가 별지점 이상일 때만 체결
3. 수량이 남으면 종가가 조건을 만족한 LOC 매수 체결

이 경우 T값도 문서의 `직전 T × 0.25 + 매수 효과` 순서로 계산합니다.

더 자세한 전략 대응표와 한계는 [METHODOLOGY.md](./METHODOLOGY.md)에 있습니다.

## 검증

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile lth_backtest/*.py
node --check lth_backtest/static/app.js
```

테스트에는 장중 고가 전용 체결, 지정가 매도 후 당일 LOC 재매수, LOC 종가 판정, 리버스 첫날 복귀, 수수료, 반올림, 조정 OHLC, 중복·비정상 데이터 거부가 포함됩니다.

## 중요한 한계

- Yahoo 일봉 고가는 보통 정규장 OHLC입니다. `trade_original.md`가 의도한 프리장·애프터장까지 포함하려면 해당 세션을 합친 고가가 들어 있는 사용자 CSV가 필요합니다.
- 일봉만으로는 고가와 저가가 발생한 순서, 호가 스프레드, 거래정지, 부분체결, 주문 거절을 재구성할 수 없습니다.
- LOC는 공식 종가에 전량 체결된다고 가정합니다. 실제 증권사별 LOC 처리와 주문 제출 시각은 다를 수 있습니다.
- 문서의 추가 하락구간 “큰수 매수”는 정확한 가격 사다리 공식이 없고 현재 웹앱도 주문을 산출하지 않으므로 임의로 만들지 않았습니다.
- 30분할은 기존 백테스트 호환을 위해 기울기와 리버스 비율을 보간한 실험 모델입니다. 공식 문서와 현재 웹앱이 명시적으로 지원하는 값은 20/40분할입니다.
- 본 도구는 연구용이며 미래 수익이나 실제 체결을 보장하지 않습니다.
