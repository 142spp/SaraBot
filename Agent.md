# Agent.md

## 1. 프로젝트 개요

이 프로젝트는 Discord 서버에서 동작하는 멘션 기반 AI 봇이다.

사용자는 봇을 멘션하여 자연어로 요청한다. 봇은 사용자의 메시지, 서버 상태, 보이스 채널 상태, 음악 재생 상태, 최근 대화 맥락을 바탕으로 LLM에게 판단을 맡긴다. LLM은 필요한 기능을 function call 형태로 요청하고, 실제 기능 실행은 봇 코드의 Tool Layer가 수행한다.

핵심 원칙은 다음과 같다.

> LLM은 판단한다.  
> 코드는 검증한다.  
> Tool Layer가 실행한다.  
> LLM은 실행 결과를 읽고 다음 행동 또는 최종 답변을 결정한다.

---

## 2. 전체 아키텍처

```text
Discord Message Event
        ↓
Mention Detector
        ↓
Bot Core
        ↓
Context Builder
        ↓
LLM Agent
        ↓
Function Call Proposal
        ↓
Policy Layer
        ↓
Tool Executor
        ↓
Tool Result
        ↓
LLM Agent
        ↓
Final Response
        ↓
Discord Reply
```

각 계층의 역할은 명확히 분리한다.

```text
Discord Adapter
- Discord 이벤트 수신
- 멘션 감지
- 메시지/유저/서버 ID 추출
- Discord API 호출 래핑

Bot Core
- 전체 요청 흐름 제어
- rate limit 확인
- quick command 처리
- agent loop 실행
- 최종 응답 전송

Context Builder
- LLM에게 전달할 현재 상태 구성
- 서버 설정, 유저 상태, 보이스 상태, 음악 상태, 최근 메시지 수집

LLM Agent
- 사용자 요청 해석
- function call 결정
- tool result를 읽고 후속 판단
- 최종 자연어 응답 생성

Policy Layer
- 권한 검사
- 서버 설정 검사
- 현재 상태 검사
- 위험 기능 차단
- tool argument 검증

Tool Executor
- 실제 기능 실행
- Discord voice 연결
- 음악 검색 및 재생
- 메모리 저장/삭제
- 대화 요약
- 실행 결과 반환

Services
- LLMService
- MusicService
- MemoryService
- PermissionService
- VoiceService
```

---

## 3. 기본 입력 흐름

봇은 기본적으로 멘션된 메시지만 처리한다.

예시:

```text
@봇 이거 설명해줘
@봇 나 있는 방 들어와
@봇 요아소비 노래 틀어줘
@봇 지금 큐 보여줘
@봇 오늘 대화 요약해줘
```

멘션되지 않은 일반 메시지는 기본적으로 무시한다. 단, 추후 서버 설정에 따라 특정 채널에서는 자동 응답을 허용할 수 있다.

---

## 4. Agent Loop

LLM은 한 번의 요청에서 여러 번 tool을 호출할 수 있다.

예시 요청:

```text
@봇 나 있는 방 들어와서 요아소비 아무거나 틀어줘
```

예상 루프:

```text
1. LLM: get_user_voice_channel 호출
2. Tool: 사용자의 현재 보이스 채널 반환
3. LLM: join_voice 호출
4. Tool: 봇이 보이스 채널 입장
5. LLM: search_music 호출
6. Tool: 검색 결과 반환
7. LLM: play_music 호출
8. Tool: 음악 재생 또는 큐 추가
9. LLM: 최종 답변 생성
```

의사 코드:

```python
async def run_agent_loop(request: BotRequest) -> str:
    messages = build_initial_messages(request)
    tool_results = []

    for step in range(MAX_AGENT_STEPS):
        llm_response = await llm_service.call(
            messages=messages,
            tools=get_available_tools(request),
        )

        if not llm_response.tool_calls:
            return llm_response.content

        for tool_call in llm_response.tool_calls:
            policy_result = await policy.check(request, tool_call)

            if not policy_result.ok:
                result = {
                    "ok": False,
                    "error": policy_result.reason,
                }
            else:
                result = await tool_executor.execute(request, tool_call)

            messages.append({
                "role": "assistant",
                "tool_call": tool_call,
            })

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })

            tool_results.append(result)

    return "요청을 처리하다가 단계가 너무 길어져서 중단했어."
```

기본 제한값:

```text
MAX_AGENT_STEPS = 5
MAX_TOOL_CALLS_PER_TURN = 5
LLM_TIMEOUT_SECONDS = 30
TOOL_TIMEOUT_SECONDS = 20
```

---

## 5. 요청 객체

Discord 메시지는 내부적으로 `BotRequest`로 변환한다.

```python
@dataclass
class BotRequest:
    guild_id: int
    channel_id: int
    message_id: int
    user_id: int
    display_name: str
    content: str
    clean_content: str
    is_admin: bool
    user_voice_channel_id: int | None
    replied_message_id: int | None
    attachments: list
```

`content`에는 원본 메시지를 저장하고, `clean_content`에는 봇 멘션을 제거한 사용자 요청만 저장한다.

예시:

```text
원본: @봇 나 있는 방 들어와서 노래 틀어줘
clean_content: 나 있는 방 들어와서 노래 틀어줘
```

---

## 6. Context Builder

LLM에게 넘길 context는 필요한 만큼만 구성한다. 전체 서버 로그를 무작정 보내지 않는다.

기본 context:

```json
{
  "guild": {
    "id": "123",
    "name": "친구 서버",
    "persona": "친구처럼 반말하되 선 넘지 않기",
    "memory_enabled": true,
    "music_enabled": true
  },
  "user": {
    "id": "456",
    "display_name": "동근",
    "is_admin": false,
    "voice_channel": {
      "id": "789",
      "name": "일반 음성방"
    }
  },
  "bot_state": {
    "in_voice_channel": false,
    "voice_channel": null
  },
  "music_state": {
    "current_track": null,
    "queue_length": 0,
    "is_playing": false
  },
  "recent_messages": [
    {
      "author": "친구A",
      "content": "노래 뭐 듣지"
    },
    {
      "author": "동근",
      "content": "요아소비 ㄱ?"
    }
  ]
}
```

원칙:

```text
- 최근 메시지는 기본 10~30개만 포함한다.
- 민감한 채널의 메시지는 context에 포함하지 않는다.
- 사용자가 명시적으로 요청한 경우에만 긴 대화 요약을 수행한다.
- 음성 녹음/STT는 명시적 동의 없이는 수행하지 않는다.
```

---

## 7. Tool 설계 원칙

Tool은 작고 명확해야 한다.

나쁜 예:

```text
do_anything(command: string)
execute_shell(command: string)
control_discord(action: string)
```

좋은 예:

```text
respond_text(message)
join_voice()
leave_voice()
play_music(query)
skip_music()
show_queue()
summarize_recent_chat(limit)
remember_user_preference(content)
forget_user_memory(memory_id)
```

LLM에게 서버의 저수준 권한을 직접 주지 않는다.

금지할 tool:

```text
execute_shell
run_python
read_env
read_file_arbitrary
write_file_arbitrary
delete_file
raw_sql
raw_discord_api
```

필요한 경우에도 반드시 별도 관리자 권한, allowlist, 확인 절차를 둔다.

---

## 8. 기본 Tool 목록

### 8.1 respond_text

사용자에게 텍스트로 답변한다.

```json
{
  "name": "respond_text",
  "description": "사용자에게 일반 텍스트로 답변한다.",
  "parameters": {
    "type": "object",
    "properties": {
      "message": {
        "type": "string"
      }
    },
    "required": ["message"]
  }
}
```

---

### 8.2 get_user_voice_channel

사용자가 현재 들어가 있는 보이스 채널 정보를 가져온다.

```json
{
  "name": "get_user_voice_channel",
  "description": "요청한 사용자가 현재 접속해 있는 보이스 채널 정보를 가져온다.",
  "parameters": {
    "type": "object",
    "properties": {},
    "required": []
  }
}
```

---

### 8.3 join_voice

사용자의 현재 보이스 채널에 봇이 입장한다.

```json
{
  "name": "join_voice",
  "description": "사용자가 현재 접속해 있는 보이스 채널에 봇이 입장한다.",
  "parameters": {
    "type": "object",
    "properties": {},
    "required": []
  }
}
```

실행 전 검사:

```text
- 사용자가 보이스 채널에 있는가?
- 봇에게 Connect 권한이 있는가?
- 봇에게 Speak 권한이 있는가?
- 서버에서 voice 기능이 활성화되어 있는가?
```

---

### 8.4 leave_voice

봇이 현재 보이스 채널에서 퇴장한다.

```json
{
  "name": "leave_voice",
  "description": "봇이 현재 접속 중인 보이스 채널에서 퇴장한다.",
  "parameters": {
    "type": "object",
    "properties": {},
    "required": []
  }
}
```

---

### 8.5 search_music

검색어를 기반으로 재생 가능한 음악 후보를 찾는다.

```json
{
  "name": "search_music",
  "description": "검색어를 기반으로 음악 후보를 검색한다.",
  "parameters": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string"
      },
      "limit": {
        "type": "integer",
        "default": 5
      }
    },
    "required": ["query"]
  }
}
```

주의:

```text
- LLM이 직접 URL을 검증하지 않는다.
- MusicService가 검색, 필터링, 스트림 추출을 담당한다.
- 검색 결과는 title, duration, source, url/id 정도만 반환한다.
```

---

### 8.6 play_music

음악을 현재 큐에 추가하고, 재생 중인 곡이 없으면 바로 재생한다.

```json
{
  "name": "play_music",
  "description": "검색어 또는 검색 결과 ID를 기반으로 음악을 큐에 추가하고 재생한다.",
  "parameters": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string"
      },
      "result_id": {
        "type": "string"
      }
    },
    "required": []
  }
}
```

규칙:

```text
- query 또는 result_id 중 하나는 반드시 있어야 한다.
- 사용자가 보이스 채널에 없으면 실패한다.
- 봇이 보이스 채널에 없으면 join_voice를 먼저 수행하거나 내부적으로 입장한다.
- 큐 길이가 제한을 넘으면 실패한다.
```

---

### 8.7 skip_music

현재 재생 중인 곡을 스킵한다.

```json
{
  "name": "skip_music",
  "description": "현재 재생 중인 곡을 스킵하고 다음 곡을 재생한다.",
  "parameters": {
    "type": "object",
    "properties": {},
    "required": []
  }
}
```

---

### 8.8 show_queue

현재 음악 큐를 보여준다.

```json
{
  "name": "show_queue",
  "description": "현재 서버의 음악 재생 큐를 보여준다.",
  "parameters": {
    "type": "object",
    "properties": {},
    "required": []
  }
}
```

---

### 8.9 summarize_recent_chat

최근 채널 대화를 요약한다.

```json
{
  "name": "summarize_recent_chat",
  "description": "현재 채널의 최근 대화를 요약한다.",
  "parameters": {
    "type": "object",
    "properties": {
      "limit": {
        "type": "integer",
        "default": 30
      }
    },
    "required": []
  }
}
```

실행 전 검사:

```text
- 해당 채널이 요약 허용 채널인가?
- limit이 최대값을 넘지 않는가?
- 사용자가 해당 채널을 볼 권한이 있는가?
```

---

### 8.10 remember_user_preference

사용자가 명시적으로 기억해달라고 한 내용을 저장한다.

```json
{
  "name": "remember_user_preference",
  "description": "사용자가 명시적으로 기억해달라고 한 개인 선호나 서버 설정을 저장한다.",
  "parameters": {
    "type": "object",
    "properties": {
      "content": {
        "type": "string"
      },
      "scope": {
        "type": "string",
        "enum": ["user", "guild"]
      }
    },
    "required": ["content", "scope"]
  }
}
```

주의:

```text
- 민감 정보는 기본적으로 저장하지 않는다.
- 사용자가 명시적으로 기억을 요청한 경우에만 저장한다.
- 저장된 memory는 사용자가 삭제할 수 있어야 한다.
```

---

### 8.11 forget_user_memory

저장된 memory를 삭제한다.

```json
{
  "name": "forget_user_memory",
  "description": "사용자 또는 서버에 저장된 memory를 삭제한다.",
  "parameters": {
    "type": "object",
    "properties": {
      "memory_id": {
        "type": "string"
      },
      "scope": {
        "type": "string",
        "enum": ["user", "guild"]
      }
    },
    "required": ["memory_id", "scope"]
  }
}
```

---

## 9. Policy Layer

LLM이 function call을 제안해도, Policy Layer를 통과하지 못하면 실행하지 않는다.

Policy Layer의 기본 검사 항목:

```text
1. 사용자 권한
2. 서버 설정
3. 채널 설정
4. 현재 봇 상태
5. tool argument 유효성
6. rate limit
7. 위험도
```

위험도 등급:

```text
Safe
- respond_text
- show_queue
- get_current_track
- get_user_voice_channel

Moderate
- join_voice
- leave_voice
- play_music
- skip_music
- summarize_recent_chat
- remember_user_preference

Dangerous
- delete_message
- bulk_delete
- kick_user
- ban_user
- record_voice
- read_long_history
- change_server_config
```

초기 버전에서는 Dangerous tool을 구현하지 않는다.

---

## 10. 음악 재생 플로우

요청:

```text
@봇 나 있는 방 들어와서 요아소비 틀어줘
```

플로우:

```text
1. Mention Detector가 메시지 감지
2. Context Builder가 유저 보이스 상태 확인
3. LLM이 join_voice + play_music 판단
4. Policy Layer가 권한 확인
5. VoiceService가 보이스 채널 입장
6. MusicService가 검색어로 트랙 검색
7. MusicService가 큐에 추가
8. 재생 중인 곡이 없으면 ffmpeg 재생 시작
9. Tool result 반환
10. LLM이 최종 답변 생성
```

Guild별 음악 상태:

```python
@dataclass
class GuildMusicState:
    guild_id: int
    voice_channel_id: int | None
    text_channel_id: int | None
    current_track: Track | None
    queue: list[Track]
    is_playing: bool
    volume: float
    loop_mode: str
```

---

## 11. 빠른 명령 처리

모든 요청을 LLM에 보내면 비용과 지연이 커진다. 명확한 짧은 명령은 로컬에서 바로 처리할 수 있다.

예시:

```text
@봇 ping
@봇 큐
@봇 스킵
@봇 정지
@봇 나가
```

흐름:

```text
Mention Message
    ↓
Quick Command Parser
    ↓
Tool 직접 실행
    ↓
Discord Reply
```

단, quick command와 LLM agent는 동일한 Tool Layer를 사용해야 한다. 그래야 기능 정책이 중복되지 않는다.

---

## 12. 메모리 정책

메모리는 반드시 명시적이어야 한다.

저장 가능한 예:

```text
@봇 기억해. 나는 롤 할 때 정글을 주로 해.
@봇 이 서버에서는 답변을 짧게 해줘.
@봇 내가 노래 추천해달라 하면 J-pop 위주로 추천해줘.
```

저장하지 말아야 할 예:

```text
일반 대화 중 우연히 나온 개인정보
민감한 건강 정보
정치/종교 성향
사적인 대화 로그 전문
동의 없는 음성 대화 내용
```

Memory scope:

```text
user
- 특정 사용자에게만 적용되는 선호

guild
- 서버 전체에 적용되는 설정

channel
- 특정 채널에만 적용되는 설정
```

---

## 13. 에러 처리

Tool 실행 실패 시, 에러를 그대로 사용자에게 던지지 않는다. Tool result를 LLM에게 전달하고 자연어로 설명하게 한다.

예시 tool result:

```json
{
  "ok": false,
  "error_code": "USER_NOT_IN_VOICE_CHANNEL",
  "message": "사용자가 보이스 채널에 접속해 있지 않습니다."
}
```

최종 답변 예시:

```text
너가 먼저 보이스 채널에 들어가 있어야 내가 따라 들어갈 수 있어.
```

반복 실패 방지:

```text
- 같은 tool이 2회 연속 실패하면 중단한다.
- 검색 결과가 없으면 다른 검색어로 최대 1회만 재시도한다.
- 권한 실패는 재시도하지 않는다.
```

---

## 14. 보안 원칙

다음 원칙을 지킨다.

```text
- LLM에게 shell 실행 권한을 주지 않는다.
- LLM에게 임의 파일 읽기/쓰기 권한을 주지 않는다.
- LLM에게 raw SQL 실행 권한을 주지 않는다.
- LLM에게 Discord raw API 권한을 주지 않는다.
- 모든 tool argument는 schema validation을 거친다.
- 모든 write action은 permission check를 거친다.
- token, API key, .env 값은 절대 LLM context에 넣지 않는다.
```

금지 데이터:

```text
DISCORD_TOKEN
OPENAI_API_KEY
DATABASE_URL with password
.env contents
user private tokens
server credentials
```

---

## 15. 권장 디렉터리 구조

```text
src/
 ├─ main.py
 ├─ config.py
 │
 ├─ discord_adapter/
 │   ├─ bot.py
 │   ├─ events.py
 │   └─ message_parser.py
 │
 ├─ core/
 │   ├─ bot_core.py
 │   ├─ context_builder.py
 │   ├─ agent.py
 │   ├─ policy.py
 │   └─ tool_executor.py
 │
 ├─ tools/
 │   ├─ base.py
 │   ├─ chat_tools.py
 │   ├─ voice_tools.py
 │   ├─ music_tools.py
 │   ├─ memory_tools.py
 │   └─ summary_tools.py
 │
 ├─ services/
 │   ├─ llm_service.py
 │   ├─ music_service.py
 │   ├─ voice_service.py
 │   ├─ memory_service.py
 │   └─ permission_service.py
 │
 ├─ storage/
 │   ├─ db.py
 │   ├─ models.py
 │   └─ repositories.py
 │
 └─ utils/
     ├─ logger.py
     ├─ rate_limit.py
     └─ validators.py
```

---

## 16. MVP 범위

초기 버전에서는 다음 기능만 구현한다.

```text
v0.1
- 봇 멘션 감지
- LLM 일반 답변
- respond_text tool

v0.2
- agent loop
- get_user_voice_channel
- join_voice
- leave_voice

v0.3
- search_music
- play_music
- skip_music
- show_queue

v0.4
- summarize_recent_chat
- 서버별 persona

v0.5
- remember_user_preference
- forget_user_memory
```

초기에는 구현하지 않을 기능:

```text
- 음성 녹음
- STT 기반 실시간 대화
- TTS 응답
- 메시지 삭제
- 유저 kick/ban
- 임의 코드 실행
- 웹 대시보드
```

---

## 17. 최종 설계 원칙

이 봇은 명령어 봇이 아니라 Discord 안에서 동작하는 AI agent이다.

하지만 AI agent라고 해서 LLM에게 모든 권한을 주면 안 된다.

최종 원칙:

```text
1. Discord는 입출력 어댑터다.
2. Bot Core가 전체 흐름을 제어한다.
3. LLM은 tool call을 제안한다.
4. Policy Layer가 실행 가능 여부를 판단한다.
5. Tool Executor가 실제 기능을 수행한다.
6. 상태는 코드와 DB가 가진다.
7. LLM은 상태를 읽기만 한다.
8. 위험 기능은 기본적으로 비활성화한다.
9. 모든 loop에는 최대 단계 수를 둔다.
10. 사용자가 이해할 수 있는 자연어 답변으로 마무리한다.
```
