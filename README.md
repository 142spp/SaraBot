# SachikoBot

Discord 서버에서 멘션 기반으로 동작하는 AI 봇입니다. 사용자가 봇을 멘션하면 최근 대화, 서버/유저 상태, 보이스 채널, 음악 재생 상태, 저장된 기억, 과거 채팅 기록을 컨텍스트로 구성하고 OpenAI 모델이 필요한 도구를 호출해 요청을 처리합니다.

## 주요 기능

- 멘션 기반 대화 및 최근 채널 맥락 반영
- 이미지 첨부 이해 및 후속 질문용 이미지 관찰 기록 저장
- OpenAI 이미지 생성/편집
- 유저/서버 단위 기억 저장 및 삭제
- Discord 보이스 채널 입장/퇴장
- YouTube 검색 기반 음악 재생, 스킵, 대기열 확인
- 채널 기록 DB 적재, 키워드/의미 기반 과거 대화 검색
- 특정 사용자 대화 샘플 기반 성향 분석
- `N년 전 오늘` 과거 대화 소환 및 선택적 일일 자동 포스팅
- Tavily 기반 웹 검색
- YouTube 자막 기반 영상 요약
- 읽기 전용 SQL을 통한 채팅 기록 집계 질문 처리
- 유저별 친밀도 상태를 내부적으로 반영한 응답 온도 조절

## 구조

```text
src/
  main.py                    # 애플리케이션 진입점, 의존성 조립
  config.py                  # 환경 변수 로딩
  scheduler.py               # N년 전 오늘 자동 포스팅
  discord_adapter/           # Discord 이벤트, 메시지 파싱, 응답 전송
  core/                      # Agent loop, context, policy, tool executor
  tools/                     # LLM function calling 도구 구현
  services/                  # OpenAI, 음악, 보이스, 검색, 아카이브 등 도메인 서비스
  storage/                   # PostgreSQL 연결 및 repository
  utils/                     # 로깅
```

요청 처리 흐름은 다음과 같습니다.

```text
Discord on_message
  -> mention/message parser
  -> BotCore
  -> ContextBuilder
  -> LLMService
  -> PolicyLayer
  -> ToolExecutor
  -> tool result
  -> LLMService
  -> respond_text
  -> Discord reply
```

`Agent`는 최대 10단계까지 tool call loop를 수행합니다. 최종 사용자 응답은 `respond_text` 도구가 성공하면 종료됩니다.

## 요구 사항

- Python 3.11 이상 권장
- PostgreSQL
- `pgvector` 확장
- FFmpeg
- Discord Bot Token
- OpenAI API Key
- 선택 기능용 Tavily API Key

음악 재생은 `discord.py[voice]`, `yt-dlp`, FFmpeg에 의존합니다. 서버에 `ffmpeg` 바이너리가 설치되어 있어야 합니다.

## 설치

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

PostgreSQL DB에는 `pgvector` 확장이 필요합니다.

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

애플리케이션은 시작 시 필요한 테이블을 자동 생성합니다. 단, `vector` 타입 자체는 DB에 확장이 먼저 설치되어 있어야 합니다.

## 환경 변수

프로젝트 루트에 `.env` 파일을 만들고 아래 값을 설정합니다.

```env
DISCORD_TOKEN=...
OPENAI_API_KEY=...
DATABASE_URL=postgresql://user:password@host:5432/dbname

# 선택
DATABASE_URL_RO=postgresql://readonly_user:password@host:5432/dbname
OPENAI_MODEL=gpt-5.4-mini
LOG_LEVEL=INFO
LOG_DIR=logs
TAVILY_API_KEY=...
RECALL_CHANNEL_ID=0
RECALL_HOUR_KST=21
```

환경 변수 설명:

- `DISCORD_TOKEN`: Discord 봇 토큰입니다.
- `OPENAI_API_KEY`: OpenAI Chat, Embedding, Image API에 사용합니다.
- `DATABASE_URL`: 쓰기 가능한 PostgreSQL 접속 문자열입니다.
- `DATABASE_URL_RO`: `run_sql` 도구 전용 읽기 전용 접속 문자열입니다. 비어 있으면 SQL 기능은 비활성화됩니다.
- `OPENAI_MODEL`: 기본값은 `gpt-5.4-mini`입니다.
- `LOG_LEVEL`: 기본값은 `INFO`입니다.
- `LOG_DIR`: 로그 파일 저장 디렉터리입니다. 기본값은 `logs`입니다.
- `TAVILY_API_KEY`: 비어 있으면 웹 검색 기능이 비활성화됩니다.
- `RECALL_CHANNEL_ID`: `N년 전 오늘` 자동 포스팅 채널 ID입니다. `0`이면 비활성화됩니다.
- `RECALL_HOUR_KST`: 자동 포스팅 실행 시각입니다. 기본값은 KST 21시입니다.

## Discord 설정

Discord Developer Portal에서 봇에 다음 Privileged Gateway Intents를 켜야 합니다.

- Message Content Intent
- Server Members Intent

코드에서는 다음 intents를 사용합니다.

- `message_content`
- `members`
- `voice_states`

봇에는 최소한 메시지를 읽고 보내는 권한이 필요합니다. 보이스/음악 기능을 쓰려면 대상 보이스 채널에서 `Connect`, `Speak` 권한도 필요합니다.

## 실행

```bash
. .venv/bin/activate
python src/main.py
```

또는 가상환경의 Python을 직접 사용할 수 있습니다.

```bash
.venv/bin/python src/main.py
```

실행 중 로그는 콘솔과 `logs/` 디렉터리에 기록됩니다.

## 채팅 기록 적재와 검색

봇에게 현재 채널 기록 저장을 요청하면 `ingest_channel_history` 도구가 현재 채널의 메시지를 DB에 저장합니다. 이후 과거 대화 검색, 사용자 분석, `N년 전 오늘`, 의미 검색이 이 데이터를 사용합니다.

이미 저장된 채널은 마지막 메시지 이후만 증분 적재합니다. 적재된 메시지는 시간 간격과 메시지 수 기준으로 청크화되고 `text-embedding-3-small` 임베딩이 저장됩니다.

## 데이터베이스 테이블

시작 시 `src/storage/db.py`가 아래 테이블을 생성합니다.

- `memories`: 유저/서버 단위 기억
- `guild_configs`: 서버별 페르소나 설정
- `user_affinity`: 유저별 내부 친밀도 점수
- `messages`: 적재된 Discord 메시지
- `message_chunks`: 의미 검색과 `N년 전 오늘`에 쓰는 대화 청크 및 임베딩

`run_sql` 도구는 `DATABASE_URL_RO`를 사용하며 쿼리를 읽기 전용 트랜잭션으로 실행합니다. 결과는 최대 100행으로 제한됩니다.

## 주요 제한값

- Agent loop: 최대 10단계
- LLM 호출 timeout: 30초
- 웹 검색 timeout: 15초
- 음악 대기열: 서버당 최대 50곡
- 음악 검색/재생 대상 길이: 10분 이하
- 이미지 생성: 유저당 하루 20장
- 이미지 편집 입력: 최대 4장
- 최근 채널 맥락: 요청 직전 메시지 20개
- 대화 청크 기준: 10분 이상 간격 또는 20메시지마다 분리
