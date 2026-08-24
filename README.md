# 연합우주를 여행하는 히치하이커를 위한 안내서

# The Hitchhiker's Guide to the Fediverse

정적 HTML, CSS, JS로 구성된 한국어 페디버스 인스턴스 목록입니다.  
`data/instances.json`의 기본 정보와 `data/stats.ok.json`의 통계를 병합해 한 화면에서 확인할 수 있습니다.  
GitHub Pages로 그대로 호스팅할 수 있으며, 검색·필터·정렬 기능을 기본 제공합니다.

모든 데이터는 공개 API를 통해 자동 수집되며, 개인정보는 포함되지 않습니다.

---

## 📁 데이터와 Git 추적 정책

웹 UI가 런타임에 읽는 파일은 정확히 두 개입니다.

| 파일 | Git | Pages | 역할 |
| --- | --- | --- | --- |
| `data/instances.json` | 유지 | 포함 | 수동으로 선별한 인스턴스 목록 |
| `data/stats.ok.json` | 유지 | 포함 | 검증을 통과한 공개 통계. 사이트의 유일한 통계 입력 |
| `data/manual_overrides.json` | 유지 | 제외 | 특정 호스트의 수집 결과를 보정하는 수동 규칙 |
| `data/host_aliases.json` | 유지 | 제외 | 원본 호스트와 canonical host의 검증된 매핑 |

다음 파일은 조사·진단 과정의 재생성 가능한 중간 산출물이므로 `.gitignore`에 포함하며 Pages에도 올리지 않습니다.

| 파일 | 생성 시점 |
| --- | --- |
| `data/stats.bad.json` | 통계 수집 중 검증 실패·네트워크 오류·이상치 기록 |
| `data/peer_suggestions.json` | `--discover-peers` 실행 시 발견 후보 기록 |
| `data/filtered_peers.json` | `filter_spam.py` 실행 시 필터 통과 후보 기록 |
| `data/spam_filtered.log.json` | `filter_spam.py` 실행 시 제외 사유 기록 |

이 파일들은 로컬 실행 중 필요에 따라 다시 생성됩니다. 과거 파일이 필요하면 Git 이력에서 확인할 수 있습니다.

---

## ⚙️ 설치와 수동 갱신

Python 3.12 환경에서 의존성을 설치합니다.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

선별된 `instances.json`의 통계를 갱신하고 결과를 검사합니다.

```bash
python scripts/fetch_stats.py
python scripts/validate_data.py
```

수집기는 `instances.json`의 선별 인스턴스를 이전 통계 존재 여부와 관계없이 매번 다시 처리합니다. 인스턴스별로 `stats.ok.json`과 로컬 진단용 `stats.bad.json`을 원자적으로 갱신합니다. 검증기는 `instances.json`, `stats.ok.json`, `manual_overrides.json`, `host_aliases.json`의 JSON 구조와 필수 필드, 중복 호스트를 검사합니다. Git에 반영하기 전에는 반드시 검증을 통과해야 합니다.

### 상태 전환과 일시 장애 처리

`stats.ok.json`과 `stats.bad.json`은 host 및 alias를 canonical host로 해석했을 때 서로 배타적입니다.

- 정상 응답은 해당 인스턴스를 `stats.ok.json`에만 저장하고 기존 BAD 기록을 제거합니다.
- 이전에 정상 상태였던 인스턴스의 첫 번째와 두 번째 연속 실패는 일시 장애로 간주합니다. 마지막 정상 통계를 OK에 유지하면서 `consecutive_failures`, `last_failure_at`, `last_failure_reason`을 갱신합니다.
- 기본 임계값 `FAILURE_THRESHOLD = 3`에 도달하면 마지막 정상 통계를 OK에서 제거하고 현재 실패 기록을 BAD로 이동합니다.
- 이전 정상 기록이 없는 신규 실패 인스턴스는 즉시 BAD에 기록합니다.
- 이후 정상 응답을 받으면 BAD 기록과 실패 정보를 제거하고 `consecutive_failures`를 `0`으로 초기화해 OK로 복귀합니다.
- alias 원본과 canonical host의 이전 기록은 한 인스턴스로 합쳐져 양쪽 파일에 중복으로 남지 않습니다.

웹 UI는 `stats.ok.json`만 현재 정상 목록으로 사용합니다. 따라서 지속적으로 실패한 인스턴스는 임계값 도달 후 화면에서 제외되고, 복구되면 자동으로 다시 표시됩니다.

다른 디렉터리에서 안전하게 시험하려면 추적 파일 네 개를 복사한 뒤 `--data-dir`을 사용합니다.

```bash
python scripts/fetch_stats.py --data-dir /tmp/fediverse-data
python scripts/validate_data.py --data-dir /tmp/fediverse-data
```

### 선택 사항: 새 피어 조사

새 후보를 조사하는 과정은 정기 워크플로와 분리되어 있습니다.

```bash
python scripts/fetch_stats.py --discover-peers
python scripts/filter_spam.py
python scripts/fetch_stats.py --input data/filtered_peers.json
python scripts/validate_data.py
```

- `--peer-output -`을 사용하면 후보를 파일 대신 표준 출력으로 보낼 수 있습니다.
- `filter_spam.py --dry-run`은 필터 결과를 파일에 쓰지 않습니다.
- `--blocklist <파일>`로 로컬 추가 차단 목록을 지정할 수 있습니다.
- 새 후보를 `stats.ok.json`에 합치기 전에는 결과와 진단 로그를 사람이 검토해야 합니다.

`--input`으로 전달하는 피어 후보 목록에서는 `stats.ok.json`, `stats.bad.json`, legacy `stats.json`, aliases를 기준으로 이미 확인한 호스트를 제외합니다. 이 중복 제거는 선별 seed를 갱신하는 기본 실행과 `--discover-peers`의 seed 처리에는 적용되지 않습니다.

### 테스트

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

---

## 🧩 스크립트 요약

| 스크립트         | 역할                                                   |
| ---------------- | ------------------------------------------------------ |
| `fetch_stats.py` | ActivityPub 노드/플랫폼별 API를 통해 통계 수집 및 검증 |
| `filter_spam.py` | 도메인 이름 기반 스팸·광고·비정상 후보 자동 필터링     |
| `validate_data.py` | 배포 데이터의 JSON 형식과 필수 필드 검증 |
| `update.yml`     | 격리된 통계 갱신, 검증, 명시적 커밋 및 Pages 배포 |

---

## 🖥️ 웹 UI 기능

### ✔ 이름/URL 통합

- 인스턴스 이름이 바로 URL로 링크됨
- URL 열 제거 → 표가 더 간결해짐

### ✔ 가입 여부 토글 버튼

- 체크박스 제거
- "가입 닫힌 서버 표시" 버튼
- 클릭 시 초록색 활성 상태 (`badge--ok` 스타일)

### ✔ 검색 및 언어 필터 개선

- 검색창 폭 확장
- 언어 드롭다운은 자동 정규화된 언어명 표시 (예: `en` → "영어")

### ✔ 기타 기능

- 플랫폼 필터 자동 생성
- 설명·이름 실시간 검색
- 통계 열 정렬
- 가입 여부 배지 표시
- 비정상 인스턴스 자동 표시
- 이상한 메타데이터 및 Nodeinfo를 가진 웹사이트 필터링

---

## 🔄 자동 통계 및 Pages 배포

`.github/workflows/update.yml`은 매일 06:00 (Asia/Seoul) / 21:00 (UTC)에
다음 순서로 실행됩니다.

1. Python `3.12.10`과 `requirements.txt`의 고정 의존성을 설치합니다.
2. 추적 중인 데이터 네 개를 Runner 임시 디렉터리에 복사합니다.
3. 임시 디렉터리에서 통계를 수집하고 `validate_data.py`로 검사합니다.
4. 검증에 성공한 `stats.ok.json`과 `host_aliases.json`만 작업 트리에 승격합니다.
5. 두 파일 중 실제 변경이 있는 경우에만 Actions bot으로 커밋합니다.
6. 변경 여부와 관계없이 현재의 정상 데이터로 `_site` 아티팩트를 만들고 Pages에 배포합니다.

검증이나 수집이 실패하면 추적 중인 정상 데이터는 덮어쓰지 않으며 Pages 배포 단계도 실행되지 않습니다. Pages 아티팩트에는 `index.html`, `styles.css`, `js/`, `i18n/`, `instances.json`, `stats.ok.json`만 포함됩니다.

워크플로의 `GITHUB_TOKEN`에는 `contents: write`, `pages: write`, `id-token: write` 권한이 필요합니다. 저장소의 **Settings → Pages → Build and deployment → Source**는 **GitHub Actions**여야 합니다. 현재처럼 보호되지 않은 개인 저장소의 `main` 브랜치에서는 기본 `GITHUB_TOKEN`으로 충분하며 별도 PAT을 저장소에 넣지 않습니다. 조직 또는 저장소 정책이 Actions의 쓰기를 제한한다면 해당 정책을 먼저 확인해야 합니다.

---

## 💻 로컬 미리보기

```bash
python -m http.server 8000
```

`http://localhost:8000`에서 사이트를 확인합니다.
브라우저에서 `file://`로 직접 열면 JSON이 불러와지지 않을 수 있습니다.

---

## ⚖️ 라이선스

이 프로젝트는 [MIT License](./LICENSE)를 따릅니다.
