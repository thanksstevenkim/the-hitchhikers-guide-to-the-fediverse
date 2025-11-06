(async function renderDirectory() {
  const locale = document.documentElement.lang || "ko";
  const numberLocale = locale || "ko-KR";
  const FALLBACK_STRINGS = {
    ko: {
      title: "한국어 Fediverse 인스턴스 디렉토리",
      intro: "한국어로 운영되는 페디버스 인스턴스를 수동으로 정리한 목록입니다.",
      search_label: "검색어",
      search_placeholder: "이름 또는 설명 검색",
      platform_filter_label: "플랫폼",
      platform_all: "전체",
      platform_mastodon: "Mastodon",
      platform_misskey: "Misskey",
      table_heading: "인스턴스 목록",
      table_caption: "한국어 Fediverse 인스턴스 목록",
      table_aria: "한국어 Fediverse 인스턴스 목록",
      name: "이름",
      url: "주소",
      platform: "플랫폼",
      users_total: "총 사용자",
      users_active: "활성 사용자(월)",
      statuses: "게시물 수",
      description: "설명",
      loading: "데이터를 불러오는 중입니다…",
      no_data: "데이터 없음",
      no_instances: "표시할 인스턴스가 없습니다.",
      no_results: "조건에 맞는 인스턴스가 없습니다.",
      error_fetch:
        "데이터를 불러오는 중 오류가 발생했습니다. 로컬에서 테스트하는 경우 <code>python -m http.server</code>로 간단한 서버를 실행하세요.",
      sort_users_total: "총 사용자 수로 정렬",
      sort_users_active: "월간 활성 사용자 수로 정렬",
      footer_note: "데이터는 data/instances.json과 data/stats.json 파일을 수정해 갱신할 수 있습니다.",
    },
  };

  const elements = {
    table: document.getElementById("instances-table"),
    tableBody: document.getElementById("instances-body"),
    tableCaption: document.getElementById("tableCaption"),
    pageTitle: document.getElementById("page-title"),
    pageIntro: document.getElementById("page-intro"),
    directoryTitle: document.getElementById("directory-title"),
    footerNote: document.getElementById("footer-note"),
    searchInput: document.getElementById("q"),
    searchLabel: document.getElementById("searchLabel"),
    platformSelect: document.getElementById("platformFilter"),
    platformLabel: document.getElementById("platformLabel"),
    filterForm: document.getElementById("filterForm"),
    sortableHeaders: Array.from(document.querySelectorAll("th[data-sort-key]")),
  };

  const columnCount = elements.table.querySelectorAll("thead th").length || 7;

  const stringsData = await loadStrings();
  const strings = resolveStrings(stringsData, locale);

  applyStaticStrings(strings);
  setStatusMessage(strings.loading, { busy: true });

  const filters = { query: "", platform: "all" };
  const sortState = { key: null, direction: "desc" };
  let baseRows = [];

  bindFilters();
  bindSorting();

  try {
    const [instances, stats] = await Promise.all([loadInstances(), loadStats()]);
    const statsMap = createStatsMap(stats);

    baseRows = instances.map((instance, index) => ({
      order: index,
      instance,
      stats: statsMap.get(normalizeUrl(instance.url)) ?? null,
    }));

    if (baseRows.length === 0) {
      setStatusMessage(strings.no_instances);
      return;
    }

    updateDisplay();
  } catch (error) {
    console.error(error);
    setStatusMessage(strings.error_fetch, { allowHTML: true });
  }

  function bindFilters() {
    if (elements.filterForm) {
      elements.filterForm.addEventListener("submit", (event) => event.preventDefault());
    }

    if (elements.searchInput) {
      elements.searchInput.addEventListener("input", () => {
        filters.query = elements.searchInput.value.trim().toLowerCase();
        updateDisplay();
      });
    }

    if (elements.platformSelect) {
      elements.platformSelect.addEventListener("change", () => {
        const value = elements.platformSelect.value || "all";
        filters.platform = value;
        updateDisplay();
      });
    }
  }

  function bindSorting() {
    elements.sortableHeaders.forEach((header) => {
      const button = header.querySelector("button");
      if (!button) return;

      button.addEventListener("click", () => {
        const key = header.dataset.sortKey;
        if (!key) return;

        if (sortState.key === key) {
          sortState.direction = sortState.direction === "asc" ? "desc" : "asc";
        } else {
          sortState.key = key;
          sortState.direction = "desc";
        }

        updateDisplay();
      });
    });
  }

  function updateDisplay() {
    if (!baseRows.length) {
      setStatusMessage(strings.no_instances);
      return;
    }

    const filteredRows = filterRows(baseRows);
    const sortedRows = sortRows(filteredRows);

    renderRows(sortedRows);
    updateSortIndicators();
  }

  function filterRows(rows) {
    return rows.filter(({ instance }) => {
      const matchesPlatform =
        filters.platform === "all" ||
        (instance.platform ?? "").toString().trim().toLowerCase() === filters.platform;

      if (!matchesPlatform) {
        return false;
      }

      if (!filters.query) {
        return true;
      }

      const haystack = `${instance.name ?? ""} ${(instance.description ?? "")}`
        .toString()
        .toLowerCase();
      return haystack.includes(filters.query);
    });
  }

  function sortRows(rows) {
    if (!sortState.key) {
      return [...rows];
    }

    const directionMultiplier = sortState.direction === "asc" ? 1 : -1;
    const key = sortState.key;

    return [...rows].sort((a, b) => {
      const aValue = getNumericValue(a.stats?.[key]);
      const bValue = getNumericValue(b.stats?.[key]);

      if (aValue === null && bValue === null) {
        return a.order - b.order;
      }
      if (aValue === null) {
        return 1;
      }
      if (bValue === null) {
        return -1;
      }

      if (aValue === bValue) {
        return a.order - b.order;
      }

      const diff = aValue - bValue;
      return diff * directionMultiplier;
    });
  }

  function updateSortIndicators() {
    elements.sortableHeaders.forEach((header) => {
      const key = header.dataset.sortKey;
      const button = header.querySelector("button");
      if (!key || !button) return;

      if (sortState.key === key) {
        header.dataset.direction = sortState.direction;
        header.setAttribute(
          "aria-sort",
          sortState.direction === "asc" ? "ascending" : "descending"
        );
        button.setAttribute("aria-pressed", "true");
      } else {
        header.removeAttribute("data-direction");
        header.removeAttribute("aria-sort");
        button.setAttribute("aria-pressed", "false");
      }
    });
  }

  function renderRows(rows) {
    if (!rows.length) {
      const hasActiveFilters = filters.query.length > 0 || filters.platform !== "all";
      setStatusMessage(hasActiveFilters ? strings.no_results : strings.no_instances);
      return;
    }

    const fragment = document.createDocumentFragment();

    rows.forEach(({ instance, stats }) => {
      const row = document.createElement("tr");

      const nameCell = document.createElement("th");
      nameCell.scope = "row";
      nameCell.textContent = textOrFallback(instance.name);

      const urlCell = document.createElement("td");
      if (instance.url) {
        const link = document.createElement("a");
        link.href = instance.url;
        link.textContent = instance.url.replace(/^https?:\/\//, "");
        link.rel = "noopener";
        link.target = "_blank";
        urlCell.appendChild(link);
      } else {
        urlCell.textContent = strings.no_data;
      }

      const platformCell = document.createElement("td");
      platformCell.textContent = textOrFallback(instance.platform);

      const usersTotalCell = document.createElement("td");
      usersTotalCell.textContent = formatNumber(stats?.users_total);

      const usersActiveCell = document.createElement("td");
      usersActiveCell.textContent = formatNumber(stats?.users_active_month);

      const statusesCell = document.createElement("td");
      statusesCell.textContent = formatNumber(stats?.statuses);

      const descriptionCell = document.createElement("td");
      descriptionCell.textContent = textOrFallback(instance.description);

      row.append(
        nameCell,
        urlCell,
        platformCell,
        usersTotalCell,
        usersActiveCell,
        statusesCell,
        descriptionCell
      );
      fragment.appendChild(row);
    });

    elements.tableBody.innerHTML = "";
    elements.tableBody.appendChild(fragment);
    elements.table.setAttribute("aria-busy", "false");
  }

  async function loadInstances() {
    const response = await fetch("data/instances.json");
    if (!response.ok) {
      throw new Error(`인스턴스 데이터를 불러올 수 없습니다: ${response.status}`);
    }
    const data = await response.json();
    if (!Array.isArray(data)) {
      throw new Error("인스턴스 데이터 형식이 올바르지 않습니다.");
    }
    return data;
  }

  async function loadStats() {
    try {
      const response = await fetch("data/stats.json", { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`통계 데이터를 불러올 수 없습니다: ${response.status}`);
      }
      const data = await response.json();
      if (!Array.isArray(data)) {
        throw new Error("통계 데이터 형식이 올바르지 않습니다.");
      }
      return data;
    } catch (error) {
      console.info("통계 데이터를 불러오지 못했습니다. 기본 값으로 표시합니다.");
      return [];
    }
  }

  function createStatsMap(stats) {
    const map = new Map();
    stats.forEach((entry) => {
      if (!entry?.url) return;
      const key = normalizeUrl(entry.url);
      if (!key) return;
      map.set(key, {
        users_total: getNumericValue(entry.users_total),
        users_active_month: getNumericValue(entry.users_active_month),
        statuses: getNumericValue(entry.statuses),
        fetched_at: entry.fetched_at ?? null,
      });
    });
    return map;
  }

  function normalizeUrl(url) {
    if (!url || typeof url !== "string") return "";
    try {
      const parsed = new URL(url);
      parsed.hash = "";
      parsed.search = "";
      return parsed.toString().replace(/\/+$/, "").toLowerCase();
    } catch (error) {
      return url.replace(/\/+$/, "").toLowerCase();
    }
  }

  function getNumericValue(value) {
    if (value === null || value === undefined) return null;
    const numberValue = Number(value);
    return Number.isFinite(numberValue) ? numberValue : null;
  }

  function formatNumber(value) {
    if (value === null || value === undefined) {
      return strings.no_data;
    }
    const numberValue = Number(value);
    if (!Number.isFinite(numberValue)) {
      return strings.no_data;
    }
    return numberValue.toLocaleString(numberLocale);
  }

  function textOrFallback(value) {
    if (value === null || value === undefined) {
      return strings.no_data;
    }
    const text = String(value).trim();
    return text.length ? text : strings.no_data;
  }

  async function loadStrings() {
    try {
      const response = await fetch("i18n/strings.json", { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`문자열 파일을 불러올 수 없습니다: ${response.status}`);
      }
      const data = await response.json();
      if (typeof data !== "object" || data === null) {
        throw new Error("문자열 데이터 형식이 올바르지 않습니다.");
      }
      return data;
    } catch (error) {
      console.info("문자열 데이터를 불러오지 못했습니다. 내장 한국어 문자열을 사용합니다.");
      return FALLBACK_STRINGS;
    }
  }

  function resolveStrings(data, requestedLocale) {
    const fallback = FALLBACK_STRINGS.ko ?? {};
    if (!data || typeof data !== "object") {
      return { ...fallback };
    }
    const candidate = data[requestedLocale] || data.ko;
    if (candidate && typeof candidate === "object") {
      return { ...fallback, ...candidate };
    }
    return { ...fallback };
  }

  function applyStaticStrings(dict) {
    if (dict.title) {
      document.title = dict.title;
    }
    if (elements.pageTitle) {
      elements.pageTitle.textContent = dict.title;
    }
    if (elements.pageIntro) {
      elements.pageIntro.textContent = dict.intro;
    }
    if (elements.directoryTitle) {
      elements.directoryTitle.textContent = dict.table_heading;
    }
    if (elements.tableCaption) {
      elements.tableCaption.textContent = dict.table_caption;
    }
    if (elements.table) {
      elements.table.setAttribute("aria-label", dict.table_aria);
      if (elements.tableCaption?.id) {
        elements.table.setAttribute("aria-describedby", elements.tableCaption.id);
      }
    }
    if (elements.footerNote) {
      elements.footerNote.textContent = dict.footer_note;
    }
    if (elements.searchLabel) {
      elements.searchLabel.textContent = dict.search_label;
    }
    if (elements.searchInput) {
      elements.searchInput.placeholder = dict.search_placeholder;
      elements.searchInput.setAttribute("aria-label", dict.search_label);
    }
    if (elements.platformLabel) {
      elements.platformLabel.textContent = dict.platform_filter_label;
    }
    if (elements.platformSelect) {
      elements.platformSelect.setAttribute("aria-label", dict.platform_filter_label);
      elements.platformSelect.innerHTML = "";
      const options = [
        { value: "all", label: dict.platform_all },
        { value: "mastodon", label: dict.platform_mastodon },
        { value: "misskey", label: dict.platform_misskey },
      ];
      options.forEach((option) => {
        const opt = document.createElement("option");
        opt.value = option.value;
        opt.textContent = option.label;
        elements.platformSelect.appendChild(opt);
      });
      elements.platformSelect.value = "all";
    }

    setColumnText("name", dict.name);
    setColumnText("url", dict.url);
    setColumnText("platform", dict.platform);
    setColumnText("users_total", dict.users_total, dict.sort_users_total);
    setColumnText("users_active_month", dict.users_active, dict.sort_users_active);
    setColumnText("statuses", dict.statuses);
    setColumnText("description", dict.description);
  }

  function setColumnText(columnKey, text, sortLabel) {
    const header = document.querySelector(`th[data-column="${columnKey}"]`);
    if (!header) return;
    const button = header.querySelector("button");
    if (button) {
      button.textContent = text;
      if (sortLabel) {
        button.setAttribute("aria-label", sortLabel);
        button.setAttribute("title", sortLabel);
      }
      button.setAttribute("aria-pressed", "false");
    } else {
      header.textContent = text;
    }
  }

  function setStatusMessage(message, options = {}) {
    const { allowHTML = false, busy = false } = options;
    elements.tableBody.innerHTML = "";
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = columnCount;
    if (allowHTML) {
      cell.innerHTML = message;
    } else {
      cell.textContent = message;
    }
    row.appendChild(cell);
    elements.tableBody.appendChild(row);
    elements.table.setAttribute("aria-busy", busy ? "true" : "false");
  }
})();
