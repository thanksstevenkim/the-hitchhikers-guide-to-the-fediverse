# 연합우주를 여행하는 히치하이커를 위한 안내서

# The Hitchhiker's Guide to the Fediverse

[English README](./README.en.md)

정적 HTML, CSS, JS로 구성된 페디버스 인스턴스 디렉터리입니다.
`data/instances.json`의 기본 정보와 `data/stats.ok.json`의 통계를 병합해 한 화면에서 확인할 수 있습니다.  
GitHub Pages로 그대로 호스팅할 수 있으며, 한국어·영어 UI와 검색·필터·정렬 기능을 기본 제공합니다.

모든 데이터는 공개 API를 통해 자동 수집되며, 개인정보는 포함되지 않습니다.

---

## 📁 데이터와 Git 추적 정책

사이트와 자동화가 사용하는 주요 데이터 파일은 다음과 같습니다.

| 파일 | Git | Pages | 역할 |
| --- | --- | --- | --- |
| `data/instances.json` | 유지 | 포함 | 피어 탐색 시작점과 생태계 직접 관측을 위한 수동 seed 목록. 전체 운영 목록이 아님 |
| `data/monitored_instances.json` | 유지 | 제외 | 상태와 무관하게 계속 health check할 전체 canonical host registry |
| `data/stats.ok.json` | 유지 | 포함 | 검증을 통과한 공개 통계. 사이트의 유일한 통계 입력 |
| `data/software_taxonomy.json` | 유지 | 포함 | 소프트웨어 계열·용도별 분류와 사이드바 표시 순서 |
| `data/software_registry.json` | 유지 | 포함 | taxonomy와 정상 관측치를 결합한 공개 소프트웨어 레지스트리 |
| `data/manual_overrides.json` | 유지 | 제외 | 특정 호스트의 수집 결과를 보정하는 수동 규칙 |
| `data/host_aliases.json` | 유지 | 제외 | 원본 호스트와 canonical host의 검증된 매핑 |
| `data/spam_domain_blocklist.json` | 유지 | 제외 | 확인된 악성 exact host·domain suffix 규칙 |

다음 파일은 조사·진단 과정의 재생성 가능한 중간 산출물이므로 `.gitignore`에 포함하며 Pages에도 올리지 않습니다.

| 파일 | 생성 시점 |
| --- | --- |
| `data/stats.bad.json` | 통계 수집 중 검증 실패·네트워크 오류·이상치 기록 |
| `data/peer_suggestions.json` | `--discover-peers` 실행 시 발견 후보 기록 |
| `data/filtered_peers.json` | `filter_spam.py` 실행 시 필터 통과 후보 기록 |
| `data/spam_filtered.log.json` | `filter_spam.py` 실행 시 제외 사유 기록 |
| `data/software_review_queue.json` | 미분류 소프트웨어를 검토 우선순위별로 집계 |
| `data/language_review_queue.json` | 선언값·추론값 충돌과 모호한 한자 설명을 검토 대상으로 집계 |

이 파일들은 로컬 실행 중 필요에 따라 다시 생성됩니다. 과거 파일이 필요하면 Git 이력에서 확인할 수 있습니다.

---

## ⚙️ 설치와 수동 갱신

Python 3.12 환경에서 의존성을 설치합니다.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

seed와 monitored registry 전체의 통계를 갱신하고 결과를 검사합니다.

```bash
python scripts/fetch_stats.py
python scripts/build_software_registry.py
python scripts/validate_data.py
python scripts/build_software_review_queue.py
python scripts/build_language_review_queue.py
```

수집기는 기본 실행에서 `instances.json`의 seed와 `monitored_instances.json`의 전체 대상을 canonical host 기준으로 합쳐 매번 다시 처리합니다. 검증기는 registry 구조와 `stats.ok ⊆ monitored` 불변식까지 포함해 필수 필드와 중복 호스트를 검사합니다. Git에 반영하기 전에는 반드시 검증을 통과해야 합니다.

### 언어 판정과 검토 큐

`languages_detected`는 기존 UI와 소비자를 위한 최종 언어 목록입니다. 추가 필드는 판정 근거를 분리합니다.

| 필드 | 의미 |
| --- | --- |
| `languages_declared` | NodeInfo 또는 플랫폼 API가 명시한 언어 |
| `languages_inferred` | 정제된 서버 설명에서 높은 신뢰도로 추론한 언어 |
| `languages_document` | 사이트 HTML의 `lang` 등 문서 단서. 다른 근거가 없을 때만 최종값에 사용 |
| `languages_overridden` | `manual_overrides.json`에서 확정한 언어 |
| `language_detection_version` | 저장된 추론값을 만든 감지 규칙 버전 |
| `language_detection_status` | `current`, `reclassified`, `legacy_fallback`, `manual_override` 중 하나 |

감지 규칙이 바뀌면 수집기는 저장된 `nodeinfo_description`을 이용해 기존 레코드를 네트워크 재접속 없이 한 번 재분류합니다. 새 규칙으로도 판정할 수 없는 기존 값은 `legacy_fallback`으로 보존합니다.

감지기는 일본어·한국어와 함께 쓰인 중국어를 별도 근거로 확인하며, 아르메니아·그리스·조지아·태국 문자처럼 언어를 강하게 식별하는 문자 체계를 우선 사용합니다. 짧은 문구를 소수 라틴계 언어로 과신하지 않도록 길이와 기능어 근거도 함께 검사합니다. 같은 문자를 공유하는 다국어 문장의 완전한 판별은 여전히 제한적입니다.

기본 언어 검토 큐에는 선언값과 추론값이 충돌하거나, 사람의 확인이 필요한 모호한 한자 설명만 포함됩니다. 모든 `legacy_fallback` 항목까지 진단하려면 다음 옵션을 사용합니다.

```bash
python scripts/build_language_review_queue.py --include-legacy
```

### 대규모 수집 성능과 checkpoint

기본 수집은 최대 16개의 network worker만 사용하는 bounded concurrency 방식입니다. worker는 네트워크 observation만 반환하며, GOOD/BAD 전환과 파일·registry 변경은 main thread가 한 번씩 적용합니다. 같은 host는 한 실행에서 중복 제출되지 않습니다.

```bash
python scripts/fetch_stats.py --workers 16 --checkpoint-every 100
```

- `--workers` 기본값은 `16`, 허용 범위는 `1~32`입니다. 서버 부하와 Runner 자원을 고려해 상한을 제한합니다.
- `--checkpoint-every` 기본값은 `100`입니다. 100개 완료마다 alias, monitored registry, OK/BAD 상태를 같은 filesystem의 임시 파일에서 atomic rename으로 저장합니다.
- 마지막 partial batch도 정상 종료 전에 저장됩니다.
- `Ctrl+C`가 들어오면 새 작업 제출과 대기 중 작업을 취소하고, 이미 완료된 결과를 최대 10초간 회수한 뒤 final checkpoint를 시도하고 exit code `130`으로 종료합니다.
- 진행 로그는 checkpoint마다 처리량, GOOD/transient/BAD 수, 경과 시간, 평균 처리율과 대략적인 ETA를 표시합니다.
- connect timeout은 요청당 `3.05초`, read timeout은 요청당 `5초`입니다. 한 인스턴스가 여러 endpoint를 호출할 수 있으므로 인스턴스 전체 시간은 이보다 길 수 있지만, 제한된 worker 중 하나만 점유하며 전체 수집을 순차적으로 막지는 않습니다.

특정 구간의 네트워크 문제나 로컬 보안 도구의 차단을 재현할 때는 정렬·중복 제거가 끝난 대상 목록을 zero-based index로 잘라 실행할 수 있습니다. `--trace-hosts`는 각 대상의 수집 직전과 직후에 `TRACE START`/`TRACE END` 로그를 남깁니다. 정확한 마지막 요청을 확인하려면 worker 하나로 실행합니다.

```bash
python -u scripts/fetch_stats.py \
  --discover-peers \
  --start-index 1000 \
  --limit 50 \
  --workers 1 \
  --trace-hosts \
  2>&1 | tee fetch-trace.log
```

`--start-index`와 `--limit`은 `--input`을 사용한 경우에도 이미 알려진 호스트를 제외하고 canonical host 기준으로 정렬·중복 제거한 뒤 적용됩니다. 추적 실행도 일반 수집과 마찬가지로 결과와 checkpoint를 지정된 `--data-dir`에 기록하므로, 원본 데이터를 보존하려면 별도의 시험 디렉터리를 사용해야 합니다.

약 27,000개 registry는 환경과 원격 서버 상태에 따라 여전히 오래 걸릴 수 있습니다. 현재는 매일 full scan을 유지합니다. 향후 실행 시간이 계속 길다면 healthy host는 2~3일 간격, 최근 실패/BAD host는 매일 검사하는 staggered scheduling을 별도 변경으로 검토합니다.

### 데이터 수명주기

각 파일의 책임은 분리되어 있습니다.

```text
instances.json             = discovery를 시작하는 수동 seed
monitored_instances.json   = 계속 health check할 전체 인스턴스
stats.ok.json              = 현재 사이트에 표시할 healthy 인스턴스
stats.bad.json             = 현재 실패 상태와 진단 기록
```

운영 흐름은 다음과 같습니다.

```text
seed → discovery → candidate review → monitored → health check → OK/BAD
                                                    ↑              |
                                                    └── recovery ──┘
```

- seed는 자동으로 monitored registry에 포함됩니다.
- peer suggestion은 검토만으로 registry에 들어가지 않습니다. `--input`으로 처리해 정상 수집에 성공한 후보만 `source: "peer"`로 편입됩니다.
- GOOD/BAD 전환은 표시 상태만 바꾸며 monitored membership은 삭제하지 않습니다.
- registry가 없거나 비어 있는 기존 checkout은 첫 수집 때 `instances.json ∪ stats.ok.json`으로 비파괴 bootstrap됩니다.
- alias는 저장 전에 canonical host로 정규화되므로 같은 인스턴스가 registry에 중복되지 않습니다.

### 수집 범위와 seed 다양성

이 프로젝트의 데이터는 Fediverse 전체에 대한 완전한 인구조사가 아닙니다. 수동 seed에서 시작해 공개된 피어 관계와 공개 API로 발견하고, 실제 응답을 검증할 수 있었던 서버의 표본입니다. 피어 목록을 공개하지 않거나 기존 seed와 연결되지 않은 서버, 일시적으로 응답하지 않은 서버, 접근이 제한된 서버는 포함되지 않을 수 있습니다. 따라서 관측된 소프트웨어 비율이나 서버 규모 분포를 Fediverse 전체의 점유율 또는 개인 서버 비율로 해석해서는 안 됩니다.

사이트의 포괄 총계는 **검증된 ActivityPub 호스트**로 표시합니다. WordPress·Ghost처럼 `activitypub_enabled_site`로 분류된 퍼블리싱 사이트는 별도 수치로 함께 보여줍니다. `users_total = 1`인 기록도 **사용자 1명을 보고한 호스트**라고만 표현합니다. 사용자 수는 각 소프트웨어의 자기 보고값이고 구현마다 제공 여부와 의미가 다르므로, 이를 개인 서버 판정이나 전체 Fediverse의 개인 서버 비율로 사용하지 않습니다. `monitored_instances.json`의 크기는 계속 검사할 수집 대상 수이며 현재 정상 호스트 수가 아닙니다.

seed는 두 역할을 가집니다. `discovery` seed는 수집기가 지원하는 피어 경로를 통해 새로운 후보를 찾는 출발점이고, `coverage` seed는 피어 목록 제공 여부와 관계없이 특정 소프트웨어·용도권을 매번 직접 확인하는 기준점입니다. 아래 표는 우선 관리할 대표 범위이며 전체 taxonomy를 열거한 것은 아닙니다. 특정 서버를 seed로 선택하는 것은 해당 운영 정책에 대한 보증이나 추천을 의미하지 않습니다.

| 용도 | 소프트웨어·계열 | 대표 seed | 역할 | 상태 |
| --- | --- | --- | --- | --- |
| 마이크로블로그 | Mastodon 계열 | `mastodon.social` 외 7개 | discovery | 기존 |
| 마이크로블로그 | Misskey 계열 | `misskey.io`, `aoharu.place` | discovery | 기존 |
| 마이크로블로그 | Pleroma 계열(Akkoma) | `fe.disroot.org` | coverage | 이번 보강 |
| 경량 마이크로블로그 | GoToSocial | — | coverage | 미보강 |
| 포럼·토론 | Lemmy | `lemmy.ml` | coverage | 기존 |
| 사진 | Pixelfed | `pixelfed.social` | coverage | 이번 보강 |
| 동영상 | PeerTube | `framatube.org` | coverage | 이번 보강 |
| 독서·서평 | BookWyrm | `bookwyrm.it` | coverage | 이번 보강 |
| 행사·그룹 | Mobilizon | `mobilizon.fr` | coverage | 이번 보강 |
| 범용 소셜 네트워크 | Friendica | `friendica.world` | coverage | 이번 보강 |
| 허브·퍼블리싱 | Hubzilla | `hub.netzgemeinde.eu` | coverage | 이번 보강 |
| 장문 블로그 | WriteFreely | `write.as` | coverage | 이번 보강 |
| 오디오·음악 | Funkwhale | — | coverage | 미보강 |
| 소프트웨어 포지 | Forgejo | — | coverage | 미보강 |

### 소프트웨어 taxonomy

`data/software_taxonomy.json`은 웹 UI에 있던 소프트웨어 분류를 독립된 데이터로 관리합니다. 그룹은 다음 네 유형을 사용합니다.

- `family`: Mastodon·Misskey·Pleroma처럼 계보를 나타내는 그룹
- `software`: GoToSocial·Ghost·WordPress처럼 독립 소프트웨어를 직접 표시하는 그룹
- `category`: 블로그·포럼·동영상·오디오·행사·브릿지처럼 용도에 따른 그룹
- `fallback`: 아직 분류하지 못한 소프트웨어를 위한 `unknown` 그룹

각 소프트웨어 ID는 최대 한 그룹에만 속할 수 있습니다. 그룹 순서, ID 형식, 멤버 중복, 유일한 fallback 여부는 `validate_data.py`가 검사합니다. taxonomy에 아직 없는 새 소프트웨어도 수집에서 제외하지 않으며 웹 UI에서는 `미분류(Unclassified)` 그룹 아래에 동적으로 표시합니다. `software.name` 자체가 없는 경우는 별도의 `소프트웨어명 없음(Software name unavailable)`으로 표시합니다.

분류 계보·용도와 별도로 각 그룹에는 `deployment_kind`가 있습니다.

- `federated_service`: 연합 서비스를 주목적으로 배포하는 소프트웨어
- `activitypub_enabled_site`: ActivityPub으로 참여하는 범용 퍼블리싱 소프트웨어. 현재 WordPress와 Ghost
- `federation_infrastructure`: 브릿지·릴레이·지원 인프라
- `unknown`: 운영 성격을 아직 분류하지 못한 소프트웨어

이 구분은 어느 참여자가 더 “진짜 Fediverse”인지 서열화하지 않습니다. 모든 검증된 ActivityPub 호스트를 함께 보면서도 CMS·퍼블리싱 사이트를 별도 집계할 수 있게 합니다.

저장소가 Mastodon·Misskey·Pleroma 등의 포크임을 명시하면 용도 그룹보다 해당 `family`를 우선합니다. 단순 API 호환이나 다중 프로토콜 지원만으로는 계보로 보지 않고 실제 용도에 맞는 `category`로 분류합니다.

### 공개 소프트웨어 레지스트리

`scripts/build_software_registry.py`는 `stats.ok.json`과 `software_taxonomy.json`을 결합해 `data/software_registry.json`을 생성합니다. 각 항목에는 정규화된 소프트웨어 ID, 분류 그룹과 유형, `deployment_kind`, 분류 상태, 현재 정상 호스트 수, 관측 이름, 마지막 관측 시각이 포함됩니다.

이 파일은 매일 통계 갱신 뒤 자동 재생성되며 GitHub Pages에도 공개됩니다. 전체 영문 스키마와 공개 URL은 [English README](./README.en.md#public-data-urls)에 정리되어 있습니다. `ap-tombstone`은 운영 종료 표식이고 소프트웨어명이 없는 관측은 식별 가능한 소프트웨어가 아니므로 레지스트리에서 제외합니다.

### 미분류 소프트웨어 검토

현재 정상 인스턴스에서 아직 분류되지 않은 소프트웨어를 집계하려면 다음 명령을 실행합니다.

```bash
python scripts/build_software_review_queue.py
```

결과는 기본적으로 Git에서 제외되는 `data/software_review_queue.json`에 저장됩니다. 동일한 소프트웨어 이름을 사용하는 호스트를 하나로 묶고, 현재 정상 인스턴스 수가 많은 순서로 대표 호스트·관측 이름·마지막 관측 시각을 기록합니다.

- `explicit_unknown`: taxonomy의 `unknown`에 명시적으로 들어 있지만 아직 재분류하지 않은 항목
- `unclassified`: taxonomy에 아직 등장하지 않은 새 항목

파일을 만들지 않고 바로 확인하려면 `--output -`을 사용합니다.

```bash
python scripts/build_software_review_queue.py --output -
```

### 상태 전환과 일시 장애 처리

`stats.ok.json`과 `stats.bad.json`은 host 및 alias를 canonical host로 해석했을 때 서로 배타적입니다.

- 정상 응답은 해당 인스턴스를 `stats.ok.json`에만 저장하고 기존 BAD 기록을 제거합니다.
- 이전에 정상 상태였던 인스턴스의 첫 번째와 두 번째 연속 실패는 일시 장애로 간주합니다. 마지막 정상 통계를 OK에 유지하면서 `consecutive_failures`, `last_failure_at`, `last_failure_reason`을 갱신합니다.
- 기본 임계값 `FAILURE_THRESHOLD = 3`에 도달하면 마지막 정상 통계를 OK에서 제거하고 현재 실패 기록을 BAD로 이동합니다.
- 이전 정상 기록이 없는 신규 실패 인스턴스는 즉시 BAD에 기록합니다.
- `ap-tombstone`처럼 운영 종료를 명시하는 software marker는 일시 장애 유예 없이 즉시 BAD로 이동합니다.
- 이후 정상 응답을 받으면 BAD 기록과 실패 정보를 제거하고 `consecutive_failures`를 `0`으로 초기화해 OK로 복귀합니다.
- alias 원본과 canonical host의 이전 기록은 한 인스턴스로 합쳐져 양쪽 파일에 중복으로 남지 않습니다.

웹 UI는 `stats.ok.json`만 현재 정상 목록으로 사용합니다. 지속적으로 실패한 인스턴스는 임계값 도달 후 화면에서 제외되지만 monitored registry에는 남아 다음 실행에서도 검사되며, 복구되면 자동으로 다시 표시됩니다.

다른 디렉터리에서 안전하게 시험하려면 추적 데이터 여섯 개를 복사한 뒤 `--data-dir`을 사용합니다.

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
- 기본적으로 추적 파일 `data/spam_domain_blocklist.json`의 exact host와 확인된 악성 domain suffix 규칙을 적용합니다. `--blocklist <파일>`은 이 기본 파일 대신 지정한 목록을 사용합니다.
- TLD 자체는 스팸 판정 근거로 사용하지 않습니다. 개별 악성 서버는 `exact_hosts`에, 하위 호스트까지 같은 목적으로 대량 생성되는 것이 확인된 도메인 영역은 `domain_suffixes`에 기록합니다. suffix 비교는 DNS label 경계를 지키므로 `activitypub-troll.cf` 규칙이 `notactivitypub-troll.cf`까지 차단하지 않습니다.
- 새 후보를 `stats.ok.json`에 합치기 전에는 결과와 진단 로그를 사람이 검토해야 합니다.

`--input`으로 전달하는 피어 후보 목록에서는 monitored registry, `stats.ok.json`, `stats.bad.json`, legacy `stats.json`, aliases를 기준으로 이미 알려진 호스트를 제외합니다. 이 중복 제거는 seed/monitored health refresh에는 적용되지 않습니다. `--discover-peers`는 전체 monitored 대상을 검사하면서 peers를 모으되, 이미 알려진 호스트를 한 번 계산해 suggestion에서 제외합니다.

과거 TLD 규칙으로 제외된 후보를 현재 규칙으로 다시 나누려면 기존 로그 자체를 입력으로 사용할 수 있습니다. 입력 로그를 보존하도록 출력과 새 로그에는 반드시 다른 경로를 사용해야 하며, 스크립트도 동일 경로 덮어쓰기를 거부합니다.

```bash
python scripts/filter_spam.py \
  --input data/spam_filtered.log.json \
  --output /tmp/recheck_candidates.json \
  --log /tmp/recheck_filtered.log.json

# 두 결과를 검토한 뒤 통과 후보만 실제 수집
python scripts/fetch_stats.py --input /tmp/recheck_candidates.json
```

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
| `filter_spam.py` | exact host·domain suffix blocklist, 도메인 휴리스틱, 통계 이상 기반 후보 필터링 |
| `build_software_registry.py` | 정상 관측치와 taxonomy를 결합해 공개 소프트웨어 레지스트리 생성 |
| `build_software_review_queue.py` | 미분류 소프트웨어를 이름별로 집계해 검토 대기열 생성 |
| `validate_data.py` | 배포 데이터의 JSON 형식과 필수 필드 검증 |
| `update.yml`     | 격리된 통계 갱신, 검증, 명시적 커밋 및 Pages 배포 |

---

## 🖥️ 웹 UI 기능

### ✔ 한국어/영어 UI

- `?lang=ko`와 `?lang=en`으로 표시 언어를 명시적으로 선택
- 언어 매개변수가 없으면 브라우저의 선호 언어를 확인하고, 지원되는 언어가 없으면 영어로 표시
- 화면 상단의 `한국어` / `English` 링크로 언어별 URL을 바로 전환·공유

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
2. 추적 중인 입력·상태 데이터와 소프트웨어 taxonomy를 Runner 임시 디렉터리에 복사합니다.
3. 임시 디렉터리에서 16 workers, 100-host checkpoint로 통계를 수집합니다.
4. 정상 통계와 taxonomy로 `software_registry.json`을 생성하고 전체 데이터를 검사합니다.
5. 검증에 성공한 `monitored_instances.json`, `stats.ok.json`, `host_aliases.json`, `software_registry.json`을 작업 트리에 승격합니다.
6. 네 파일 중 실제 변경이 있는 경우에만 Actions bot으로 커밋합니다.
7. 변경 여부와 관계없이 현재의 정상 데이터로 `_site` 아티팩트를 만들고 Pages에 배포합니다.

검증이나 수집이 실패하면 추적 중인 정상 데이터는 덮어쓰지 않으며 Pages 배포 단계도 실행되지 않습니다. Pages 아티팩트에는 `index.html`, `styles.css`, `js/`, `i18n/`, `instances.json`, `stats.ok.json`, `software_taxonomy.json`, `software_registry.json`만 포함됩니다.

update job에는 `timeout-minutes: 300`을 설정합니다. 강제 timeout은 graceful shutdown 신호를 보장하지 않으므로 최대 손실 범위는 마지막 100개 미만의 미저장 observation이며, 그 이전 checkpoint는 staging 디렉터리에 보존됩니다. Workflow가 실패하면 staging 결과는 repository에 승격되지 않습니다.

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
