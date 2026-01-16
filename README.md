# youtube-storage

YouTube 영상 자막 작업 및 아카이빙을 위한 자동화 저장소.

## 워크플로우 개요

```
YouTube URL
    ↓
[yt-subs-whisper-translate] → 자막 생성/번역 (en.srt, ko.srt, ko.vtt)
    ↓
[yt-burnin-upload] → 자막 번인 영상 생성 + YouTube 업로드
    ↓
[transcript-to-markdown] → 노트 마크다운 생성
    ↓
[web 통합] → 웹사이트 콘텐츠 추가 (TODO)
```

## 디렉토리 구조

```
youtube-storage/
├── README.md
├── scripts/
│   └── process_video.py      # 전체 파이프라인 자동화 스크립트
├── config/
│   └── oauth/                 # YouTube API OAuth 인증 파일
│       ├── client_secret.json
│       └── token.json
└── videos/
    └── {VIDEO_ID}/            # 영상별 폴더
        ├── meta.json          # yt-dlp 메타데이터
        ├── metadata_ko.json   # 한글 번역된 제목/설명
        ├── en.srt             # 영어 자막
        ├── en.vtt
        ├── ko.srt             # 한국어 자막
        ├── ko.vtt
        ├── burnin.mp4         # 자막 번인된 영상 (필수 보관)
        ├── notes.md           # 자막 기반 마크다운 노트
        ├── upload_info.json   # YouTube 업로드 정보
        └── logs/              # 처리 로그
            └── process_*.log
```

## 환경 설정

### Python 가상환경 (virtualenv)

```bash
# 가상환경 생성 (최초 1회)
python3 -m venv .venv

# 가상환경 활성화
source .venv/bin/activate

# 의존성 설치
pip install -r requirements.txt
```

### 필수 외부 도구

- `yt-dlp` - YouTube 다운로드
- `ffmpeg` - 영상/자막 처리
- `whisper` - 음성 인식 (자막 없을 때)
- `codex` - 번역/요약 (Codex CLI)

## 빠른 시작

### 1. 전체 파이프라인 실행

```bash
# 가상환경 활성화 후 실행
source .venv/bin/activate
python3 scripts/process_video.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

**기본 동작**: 자막 생성 → burn-in → 마크다운 노트 → **YouTube 업로드 (unlisted)**

### 옵션

| 플래그 | 설명 |
|--------|------|
| `--no-upload` | YouTube 업로드 건너뛰기 |
| `--skip-burnin` | burn-in 단계 건너뛰기 |
| `--skip-markdown` | 마크다운 생성 건너뛰기 |
| `--keep-source` | source 영상 보관 |
| `--dry-run` | 테스트 모드 (외부 API 호출 안함) |

### 2. 개별 단계 실행

```bash
# 1단계: 자막 생성/번역
python3 ../my-skills/yt-subs-whisper-translate/scripts/yt_subs_whisper_translate.py "<URL>"

# 2단계: 자막 번인 + 업로드
python3 ../my-skills/yt-burnin-upload/scripts/yt_burnin_upload.py "<URL>" --ko-srt path/to/ko.srt

# 3단계: 마크다운 노트 생성
python3 ../my-skills/transcript-to-markdown/scripts/transcript_to_markdown.py \
  --input ko.srt --output notes.md --title "영상 제목"
```

## OAuth 설정 (YouTube 업로드용)

YouTube Data API를 통해 영상을 업로드하려면 OAuth 2.0 인증이 필요합니다.

### 설정 단계

1. **Google Cloud Console에서 프로젝트 생성**
   - https://console.cloud.google.com/ 접속
   - 새 프로젝트 생성 또는 기존 프로젝트 선택

2. **YouTube Data API v3 활성화**
   - API 및 서비스 > 라이브러리
   - "YouTube Data API v3" 검색 후 활성화

3. **OAuth 2.0 클라이언트 ID 생성**
   - API 및 서비스 > 사용자 인증 정보
   - "사용자 인증 정보 만들기" > "OAuth 클라이언트 ID"
   - 애플리케이션 유형: "데스크톱 앱"
   - JSON 다운로드 후 `config/oauth/client_secret.json`으로 저장

4. **최초 인증 실행**
   ```bash
   source .venv/bin/activate
   python3 scripts/auth_youtube.py
   ```
   - 브라우저가 열리면 Google 계정 로그인
   - 권한 승인 후 `config/oauth/token.json` 자동 생성

### 재인증이 필요한 경우

토큰이 만료되거나 권한 변경이 필요하면:

```bash
source .venv/bin/activate
rm config/oauth/token.json
python3 scripts/auth_youtube.py
```

## 파일 보관 정책

| 파일 | 보관 여부 | 비고 |
|------|----------|------|
| source 영상 | 삭제 | 언제든 재다운로드 가능 |
| metadata.json | 보관 | 영상 정보 |
| *.srt, *.vtt | 보관 | 자막 파일 |
| burnin.mp4 | **필수 보관** | 최종 결과물 |
| notes.md | 보관 | 마크다운 노트 |
| logs/ | 보관 | 디버깅용 |

## 업로드 설정

기본값:
- **제목**: 원본 제목을 한글로 번역
- **설명**: 원본 YouTube 링크 + 한글 번역된 설명
- **공개상태**: unlisted (일부 공개)
- **태그/재생목록**: 없음

업로드 후 `upload_info.json`에 업로드 정보가 저장됩니다.

## TODO

- [x] YouTube OAuth 설정
- [x] 자동 업로드 기능
- [ ] web 통합 (새 카테고리/페이지 생성)

## 관련 스킬

- [yt-subs-whisper-translate](../my-skills/yt-subs-whisper-translate/) - 자막 생성/번역
- [yt-burnin-upload](../my-skills/yt-burnin-upload/) - 자막 번인 + 업로드
- [transcript-to-markdown](../my-skills/transcript-to-markdown/) - 마크다운 노트 생성
