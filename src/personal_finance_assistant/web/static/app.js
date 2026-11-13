"use strict";

const $ = (id) => document.getElementById(id);
const pad = (value) => String(value).padStart(2, "0");
const escapeHtml = (value) => String(value === null || value === undefined ? "" : value).replace(/[&<>"']/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
}[character]));

const state = {
  start: "",
  end: "",
  search: "",
  category: "",
  merchant: "",
  review: "",
  sort: "date",
  direction: "desc",
  offset: 0,
  limit: 50,
  ids: "",
  section: "overview",
  categories: {},
  importPreview: null,
  reviewCount: 0,
};

const money = (value) => {
  if (!value || typeof value.minor !== "number") return "—";
  const minor = value.minor;
  const negative = minor < 0;
  const absolute = Math.abs(minor);
  const whole = String(Math.floor(absolute / 100)).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return `${negative ? "-" : ""}${whole},${pad(absolute % 100)} €`;
};

const compactMoney = (minor) => {
  const absolute = Math.abs(minor);
  if (absolute >= 100000) return `${Math.round(absolute / 100000)}k €`;
  if (absolute >= 1000) return `${Math.round(absolute / 1000)} €`;
  return `${Math.round(absolute / 100)} €`;
};

const parseMinor = (text) => {
  let raw = String(text === null || text === undefined ? "" : text).trim().replace(/\s/g, "").replace("€", "");
  if (!raw) throw new Error("An amount is required.");
  let negative = false;
  if (raw.startsWith("-")) { negative = true; raw = raw.slice(1); }
  if (raw.includes(",") && raw.includes(".")) {
    raw = raw.replace(/\./g, "").replace(",", ".");
  } else if (raw.includes(",")) {
    raw = raw.replace(",", ".");
  } else if ((raw.match(/\./g) || []).length > 1) {
    raw = raw.replace(/\./g, "");
  }
  const match = raw.match(/^(\d+)(?:\.(\d{1,2}))?$/);
  if (!match) throw new Error("Use a valid amount such as 150,00.");
  const whole = Number.parseInt(match[1], 10);
  const fraction = Number.parseInt((match[2] || "").padEnd(2, "0"), 10);
  const minor = whole * 100 + fraction;
  return negative ? -minor : minor;
};

const localDate = (date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
const monthStart = (date) => new Date(date.getFullYear(), date.getMonth(), 1);
const nextMonth = (date) => new Date(date.getFullYear(), date.getMonth() + 1, 1);
const previousMonth = (date) => new Date(date.getFullYear(), date.getMonth() - 1, 1);

const monthFromDate = (dateText) => dateText.slice(0, 7);

const formatApiDetail = (detail) => {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => item && item.msg ? item.msg : String(item)).join("; ");
  }
  return "The request could not be completed.";
};

const api = async (path, options = {}) => {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (body && body.detail) message = formatApiDetail(body.detail);
    } catch (error) {
      const text = await response.text();
      if (text) message = text.replace(/^\{.*"detail":"?/, "").replace(/"?\}?$/, "");
    }
    throw new Error(message);
  }
  return response.json();
};

const setError = (message) => {
  const banner = $("error");
  banner.textContent = message || "";
  banner.hidden = !message;
};

const clearOverview = () => {
  ["income", "expenses", "net", "savings", "refunds", "transfers", "fees", "count",
    "categorized", "uncategorized"].forEach((id) => { const element = $(id); if (element) element.textContent = "—"; });
  $("quality").textContent = "—";
  $("quality").className = "badge";
  $("period-label").textContent = "";
  $("categories").innerHTML = '<p class="muted">No data to display.</p>';
  $("trends").innerHTML = '<p class="muted">No data to display.</p>';
  $("merchants").innerHTML = '<p class="muted">No data to display.</p>';
  $("weekly-trends").innerHTML = '<p class="muted">No data to display.</p>';
  $("overview-transactions").innerHTML = '<p class="muted">No data to display.</p>';
  $("insights").innerHTML = '<p class="muted">No data to display.</p>';
};

const loadHealth = async () => {
  const element = $("health");
  try {
    const health = await api("/api/health");
    element.classList.remove("error");
    element.classList.add("ok");
    if (health.transactions === 0) {
      element.textContent = `Local database · schema v${health.schema_version} · no transactions yet`;
    } else {
      element.textContent = `Local database · ${health.transactions} transactions · schema v${health.schema_version}`;
    }
  } catch (error) {
    element.classList.remove("ok");
    element.classList.add("error");
    element.textContent = "Local database unavailable";
  }
};

const fetchCategories = async () => {
  try { state.categories = await api("/api/categories"); } catch (error) { state.categories = {}; }
  const options = Object.entries(state.categories)
    .map(([key, label]) => `<option value="${escapeHtml(key)}">${escapeHtml(label)}</option>`)
    .join("");
  [$("tx-category"), $("budget-category"), $("alias-category"), $("rule-category")].forEach((select) => {
    if (!select) return;
    const first = select.firstElementChild ? select.firstElementChild.outerHTML : "";
    select.innerHTML = first + options;
  });
};

const setDefaultDates = async () => {
  let start = monthStart(new Date());
  let end = nextMonth(start);
  try {
    const coverage = await api("/api/coverage");
    if (coverage.last_date) {
      const last = new Date(`${coverage.last_date}T12:00:00`);
      start = monthStart(last);
      end = nextMonth(start);
    }
  } catch (error) { /* use current month */ }
  $("start").value = localDate(start);
  $("end").value = localDate(end);
  state.start = $("start").value;
  state.end = $("end").value;
};

const queryString = (extra = {}) => {
  const parameters = new URLSearchParams();
  parameters.set("start", state.start);
  parameters.set("end", state.end);
  Object.entries(extra).forEach(([key, value]) => {
    if (value !== "" && value !== null && value !== undefined) parameters.set(key, value);
  });
  return parameters.toString();
};

const persistState = () => {
  const parameters = new URLSearchParams();
  parameters.set("start", state.start);
  parameters.set("end", state.end);
  if (state.search) parameters.set("search", state.search);
  if (state.category) parameters.set("category", state.category);
  if (state.merchant) parameters.set("merchant", state.merchant);
  if (state.review) parameters.set("review", state.review);
  if (state.sort !== "date") parameters.set("sort", state.sort);
  if (state.direction !== "desc") parameters.set("direction", state.direction);
  if (state.offset) parameters.set("offset", String(state.offset));
  if (state.ids) parameters.set("ids", state.ids);
  const hash = `#/${state.section}?${parameters.toString()}`;
  if (location.hash !== hash) history.replaceState(null, "", hash);
};

const applyHash = () => {
  const raw = location.hash.replace(/^#\/?/, "");
  if (!raw) return false;
  const [section, query] = raw.split("?");
  const parameters = new URLSearchParams(query || "");
  state.section = ["overview", "analytics", "budgets", "transactions", "import", "review",
    "merchants", "insights", "ask", "settings"].includes(section) ? section : "overview";
  if (parameters.get("start")) state.start = parameters.get("start");
  if (parameters.get("end")) state.end = parameters.get("end");
  state.search = parameters.get("search") || "";
  state.category = parameters.get("category") || "";
  state.merchant = parameters.get("merchant") || "";
  state.review = parameters.get("review") || "";
  state.sort = parameters.get("sort") || "date";
  state.direction = parameters.get("direction") || "desc";
  state.offset = Number.parseInt(parameters.get("offset") || "0", 10) || 0;
  state.ids = parameters.get("ids") || "";
  if (state.start) $("start").value = state.start;
  if (state.end) $("end").value = state.end;
  return true;
};

const showSection = (name, { load = true } = {}) => {
  state.section = name;
  document.querySelectorAll(".navlink").forEach((button) => {
    const active = button.dataset.section === name;
    button.classList.toggle("active", active);
    button.setAttribute("aria-current", active ? "page" : "false");
  });
  document.querySelectorAll(".section").forEach((section) => {
    section.classList.toggle("active", section.id === `section-${name}`);
  });
  syncTabState(name);
  persistState();
  if (load) loadForSection(name);
};

const barChart = (container, items, { onClick, colour = "category", empty = "No data for this period." } = {}) => {
  if (!items || !items.length) {
    container.innerHTML = `<p class="muted">${escapeHtml(empty)}</p>`;
    return;
  }
  const width = 620;
  const rowHeight = 32;
  const left = 150;
  const right = 100;
  const height = items.length * rowHeight + 12;
  const maximum = Math.max(...items.map((item) => item.minor), 1);
  const rows = items.map((item, index) => {
    const y = index * rowHeight + 6;
    const barWidth = Math.max(2, Math.round((item.minor / maximum) * (width - left - right)));
    const label = item.label.length > 22 ? `${item.label.slice(0, 21)}…` : item.label;
    const tooltip = `${item.label}: ${money({ minor: item.minor, currency: "EUR" })}`;
    return `
      <g>
        <text x="0" y="${y + 15}">${escapeHtml(label)}</text>
        <rect class="bar ${colour}" x="${left}" y="${y}" width="${barWidth}" height="20" rx="4"
              tabindex="0" role="button" data-minor="${item.minor}" aria-label="${escapeHtml(tooltip)}">
          <title>${escapeHtml(tooltip)}</title>
        </rect>
        <text class="value-label" x="${width - right + 8}" y="${y + 15}">${escapeHtml(money({ minor: item.minor, currency: "EUR" }))}</text>
      </g>`;
  }).join("");
  container.innerHTML = `
    <div class="chart-wrap">
      <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Horizontal bar chart">
        <line class="axis" x1="${left}" y1="0" x2="${left}" y2="${height - 2}"></line>
        ${rows}
      </svg>
    </div>
    <div class="legend"><span class="${colour}">${escapeHtml(colour === "merchant" ? "Spending by merchant" : "Spending by category")}</span></div>`;
  container.querySelectorAll("rect.bar").forEach((rect, index) => {
    const activate = () => onClick && onClick(items[index]);
    rect.addEventListener("click", activate);
    rect.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); activate(); }
    });
  });
};

const columnChart = (container, items, { onClick, title = "Monthly cash flow" } = {}) => {
  if (!items || !items.length) {
    container.innerHTML = '<p class="muted">No data for this period.</p>';
    return;
  }
  const width = 620;
  const height = 280;
  const left = 56;
  const right = 12;
  const top = 18;
  const bottom = 42;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const maximum = Math.max(...items.flatMap((item) => [item.expenses.minor, item.income.minor]), 1);
  const groupWidth = plotWidth / items.length;
  const barWidth = Math.max(4, Math.min(16, groupWidth * 0.32));
  const y = (value) => top + plotHeight - (value / maximum) * plotHeight;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((fraction) => {
    const value = Math.round(maximum * fraction);
    return `<line class="axis" x1="${left}" y1="${y(value)}" x2="${width - right}" y2="${y(value)}"></line>
            <text x="0" y="${y(value) + 4}">${escapeHtml(compactMoney(value))}</text>`;
  }).join("");
  const bars = items.map((item, index) => {
    const centre = left + groupWidth * index + groupWidth / 2;
    const expenseHeight = Math.max(1, (item.expenses.minor / maximum) * plotHeight);
    const incomeHeight = Math.max(1, (item.income.minor / maximum) * plotHeight);
    const expenseX = centre - barWidth - 2;
    const incomeX = centre + 2;
    const label = item.label || item.month;
    return `
      <g>
        <rect class="bar expense" x="${expenseX}" y="${top + plotHeight - expenseHeight}"
              width="${barWidth}" height="${expenseHeight}" rx="3" tabindex="0" role="button"
              aria-label="${escapeHtml(`${label} expenses ${money(item.expenses)}`)}">
          <title>${escapeHtml(`${label} expenses: ${money(item.expenses)}`)}</title>
        </rect>
        <rect class="bar income" x="${incomeX}" y="${top + plotHeight - incomeHeight}"
              width="${barWidth}" height="${incomeHeight}" rx="3" tabindex="0" role="button"
              aria-label="${escapeHtml(`${label} income ${money(item.income)}`)}">
          <title>${escapeHtml(`${label} income: ${money(item.income)}`)}</title>
        </rect>
        <text x="${centre}" y="${height - 22}" text-anchor="middle">${escapeHtml(label)}</text>
      </g>`;
  }).join("");
  container.innerHTML = `
    <div class="chart-wrap">
      <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(title)}">
        ${ticks}
        <line class="axis" x1="${left}" y1="${top + plotHeight}" x2="${width - right}" y2="${top + plotHeight}"></line>
        ${bars}
      </svg>
    </div>
    <div class="legend"><span class="expense">Expenses</span><span class="income">Income</span></div>`;
  container.querySelectorAll("rect.bar").forEach((rect) => {
    const group = rect.closest("g");
    const label = group ? group.querySelector("text").textContent : "";
    const item = items.find((entry) => (entry.label || entry.month) === label);
    const activate = () => onClick && onClick(item);
    rect.addEventListener("click", activate);
    rect.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); activate(); }
    });
  });
};

const renderInsights = (container, insights, { empty = "No evidence-backed insight for this period." } = {}) => {
  if (!insights || !insights.length) {
    container.innerHTML = `<p class="muted">${escapeHtml(empty)}</p>`;
    return;
  }
  container.innerHTML = insights.map((item) => {
    const ids = (item.supporting_transaction_ids || []).join(",");
    const clickable = Boolean(ids) || Boolean(item.period);
    return `<div class="insight ${clickable ? "clickable" : ""}" ${clickable ? 'tabindex="0" role="button"' : ""}
      data-action="open-insight" data-ids="${escapeHtml(ids)}"
      data-start="${escapeHtml(item.period ? item.period.start : state.start)}"
      data-end="${escapeHtml(item.period ? item.period.end : state.end)}">
      <strong>${escapeHtml(item.title)}</strong>
      <p>${escapeHtml(item.explanation)}</p>
      ${item.next_action ? `<p>${escapeHtml(item.next_action)}</p>` : ""}
      <p>Confidence: ${escapeHtml(item.confidence)}</p>
    </div>`;
  }).join("");
};

const transactionRow = (row) => {
  const statusClass = row.review_status === "confirmed" ? "confirmed" : row.review_status === "dismissed" ? "dismissed" : "review";
  return `<tr class="clickable" data-action="open-tx" data-id="${escapeHtml(row.id)}">
    <td>${escapeHtml(row.date)}</td>
    <td>${escapeHtml(row.merchant)}</td>
    <td>${escapeHtml(row.category_label)}${row.has_split ? " · split" : ""}</td>
    <td>${escapeHtml(row.classification.replace("_candidate", ""))}</td>
    <td><span class="status-pill ${statusClass}">${escapeHtml(row.review_status.replace("_", " "))}</span>
      <span class="muted">${Math.round((row.category_confidence || 0) * 100)}%</span></td>
    <td class="amount">${money(row.amount)}</td>
    <td class="row-action"><button class="button button-small" data-action="edit-tx" data-id="${escapeHtml(row.id)}">Edit</button></td>
  </tr>`;
};

const transactionCard = (row) => {
  const statusClass = row.review_status === "confirmed" ? "confirmed" : row.review_status === "dismissed" ? "dismissed" : "review";
  return `<article class="tx-card" data-action="open-tx" data-id="${escapeHtml(row.id)}" tabindex="0" role="button">
    <div class="tx-card-head">
      <strong>${escapeHtml(row.merchant)}</strong>
      <span class="tx-card-amount">${money(row.amount)}</span>
    </div>
    <div class="tx-card-meta">
      <span>${escapeHtml(row.date)}</span>
      <span>${escapeHtml(row.category_label)}${row.has_split ? " · split" : ""}</span>
      <span class="status-pill ${statusClass}">${escapeHtml(row.review_status.replace("_", " "))}</span>
      <span>${escapeHtml(row.classification.replace("_candidate", ""))}</span>
      <span>${Math.round((row.category_confidence || 0) * 100)}% confidence</span>
    </div>
    <button class="button button-small tx-card-edit" data-action="edit-tx" data-id="${escapeHtml(row.id)}">Edit category</button>
  </article>`;
};

const renderTransactions = (container, rows) => {
  if (!rows || !rows.length) {
    container.innerHTML = '<p class="empty">No transactions match this period and filters.</p>';
    return;
  }
  container.innerHTML = `
    <div class="table-wrap">
      <table>
        <thead><tr><th>Date</th><th>Merchant</th><th>Category</th><th>Type</th><th>Review</th><th class="amount">Amount</th><th></th></tr></thead>
        <tbody>${rows.map(transactionRow).join("")}</tbody>
      </table>
    </div>
    <div class="tx-cards">${rows.map(transactionCard).join("")}</div>`;
};

const loadOverviewTransactions = async () => {
  const payload = await api(`/api/transactions?${queryString({ search: state.search, limit: 12 })}`);
  renderTransactions($("overview-transactions"), payload.transactions);
};

const loadOverview = async () => {
  if (!state.start || !state.end) return;
  if (state.start >= state.end) {
    setError("Start date must be before end date.");
    clearOverview();
    return;
  }
  setError("");
  try {
    const query = queryString();
    const [overview, insights, trends, budgets, recurring, merchants, weekly, review] = await Promise.all([
      api(`/api/overview?${query}`),
      api(`/api/insights?${query}`),
      api(`/api/trends?end_month=${monthFromDate(state.end)}&months=6`),
      api(`/api/budgets?month=${monthFromDate(state.start)}`),
      api("/api/recurring"),
      api(`/api/merchants?${query}&limit=8`),
      api(`/api/weekly-trends?${query}`),
      api("/api/review?limit=500"),
    ]);
    state.reviewCount = review.review.length;
    updateReviewBadges();
    $("income").textContent = money(overview.income);
    $("expenses").textContent = money(overview.expenses);
    $("net").textContent = money(overview.net_cash_flow);
    $("savings").textContent = overview.savings_rate_percent === null ? "—" : `${overview.savings_rate_percent}%`;
    $("refunds").textContent = money(overview.refunds);
    $("transfers").textContent = money(overview.transfers);
    $("fees").textContent = money(overview.fees);
    $("count").textContent = overview.transaction_count;
    $("categorized").textContent = money(overview.categorized_expenses);
    $("uncategorized").textContent = money(overview.uncategorized_expenses);
    $("period-label").textContent = `${overview.period.start} to ${overview.period.end}`;
    const quality = $("quality");
    if (overview.data_quality === "no_data") {
      quality.textContent = "No data";
      quality.className = "badge muted";
    } else if (overview.data_quality === "complete") {
      quality.textContent = "Reviewed data";
      quality.className = "badge";
    } else {
      quality.textContent = "Review needed";
      quality.className = "badge warning";
    }
    if (overview.uncategorized_expenses.minor > 0) {
      $("uncategorized").parentElement.classList.add("notice-warning");
    } else {
      $("uncategorized").parentElement.classList.remove("notice-warning");
    }

    barChart($("categories"), overview.categories.map((item) => ({
      label: item.label, minor: item.amount.minor, key: item.key,
    })), {
      onClick: (item) => openFilteredTransactions({ category: item.key }),
      colour: "category",
      empty: "No classified spending in this period.",
    });
    columnChart($("trends"), trends.months.map((item) => ({
      label: item.month, month: item.month, expenses: item.expenses, income: item.income,
    })), { onClick: (item) => selectMonth(item.month) });
    barChart($("merchants"), merchants.merchants.map((item) => ({
      label: item.merchant, minor: item.amount.minor, merchant: item.merchant,
    })), {
      onClick: (item) => openFilteredTransactions({ merchant: item.merchant }),
      colour: "merchant",
      empty: "No classified merchant expenses in this period.",
    });
    columnChart($("weekly-trends"), weekly.weeks.map((item) => ({
      label: item.start.slice(5), start: item.start, expenses: item.expenses, income: item.income,
    })), { onClick: (item) => selectWeek(item.start) });

    renderInsights($("insights"), insights.insights.slice(0, 4));
    renderBudgets($("budgets"), budgets, false);
    renderRecurring($("recurring"), recurring, false);
    await loadOverviewTransactions();
  } catch (error) {
    setError(error.message);
    clearOverview();
  }
};

const renderBudgets = (container, payload, withActions = true) => {
  const budgets = payload.budgets || [];
  if (!budgets.length) {
    container.innerHTML = '<p class="muted">No budgets configured for this month.</p>';
    if (payload.disclosure && container.id === "budget-list") {
      const notice = $("budget-disclosure");
      notice.textContent = payload.disclosure;
      notice.hidden = payload.complete;
      notice.className = payload.complete ? "notice" : "notice notice-warning";
    }
    return;
  }
  container.innerHTML = budgets.map((item) => {
    const over = item.exceeded ? "over" : item.percentage_used >= (item.alert_threshold_percent || 90) ? "warn" : "";
    return `<div class="budget-row">
      <div class="budget-line"><strong>${escapeHtml(item.category_label)}</strong><span>${money(item.remaining)} remaining</span></div>
      <div class="budget-meta">${money(item.used)} used of ${money(item.limit)} · ${item.percentage_used}% · ${item.elapsed_days}/${item.total_days} days${item.projected ? ` · projected ${money(item.projected)}` : ""}${item.exceeded ? " · over budget" : ""}</div>
      <div class="progress"><span class="${over}" style="width:${Math.min(100, item.percentage_used)}%"></span></div>
      ${item.complete ? "" : '<div class="budget-meta">Category status incomplete: some spending is not yet categorised.</div>'}
      ${withActions ? `<div class="review-actions"><button class="button button-small button-danger" data-action="delete-budget" data-month="${escapeHtml(payload.month)}" data-category="${escapeHtml(item.category)}">Delete</button></div>` : ""}
    </div>`;
  }).join("");
  if (payload.disclosure && container.id === "budget-list") {
    const notice = $("budget-disclosure");
    notice.textContent = payload.disclosure;
    notice.hidden = payload.complete;
    notice.className = payload.complete ? "notice" : "notice notice-warning";
  }
};

const renderRecurring = (container, payload, withActions = true) => {
  const candidates = payload.candidates || [];
  const changes = payload.price_changes || [];
  if (!candidates.length && !changes.length) {
    container.innerHTML = '<p class="muted">No repeated payment candidate has enough evidence.</p>';
    return;
  }
  container.innerHTML = `
    ${changes.length ? `<div class="notice notice-warning">${changes.map((item) =>
      `${escapeHtml(item.merchant)} changed from ${money(item.old_amount)} to ${money(item.new_amount)} on ${escapeHtml(item.changed_on)}`
    ).join("<br>")}</div>` : ""}
    ${candidates.map((item) => `<div class="recurring-row">
      <div class="recurring-line"><strong>${escapeHtml(item.merchant)}</strong><span>${money(item.average_amount)}</span></div>
      <div class="recurring-meta">${item.observations} observations · about every ${item.average_interval_days} days · ${escapeHtml(item.status)} · ${escapeHtml(item.regularity)}</div>
      ${withActions ? `<div class="review-actions">
        <button class="button button-small" data-action="recurring" data-merchant="${escapeHtml(item.merchant)}" data-decision="confirmed">Confirm</button>
        <button class="button button-small" data-action="recurring" data-merchant="${escapeHtml(item.merchant)}" data-decision="dismissed">Dismiss</button>
      </div>` : ""}
    </div>`).join("")}`;
};

const loadAnalytics = async () => {
  try {
    const query = queryString();
    const [overview, trends, weekly, merchants, insights, recurring] = await Promise.all([
      api(`/api/overview?${query}`),
      api(`/api/trends?end_month=${monthFromDate(state.end)}&months=12`),
      api(`/api/weekly-trends?${query}`),
      api(`/api/merchants?${query}&limit=12`),
      api(`/api/insights?${query}`),
      api("/api/recurring"),
    ]);
    columnChart($("analytics-trends"), trends.months.map((item) => ({
      label: item.month.slice(2), month: item.month, expenses: item.expenses, income: item.income,
    })), { onClick: (item) => selectMonth(item.month) });
    barChart($("analytics-categories"), overview.categories.map((item) => ({
      label: item.label, minor: item.amount.minor, key: item.key,
    })), { onClick: (item) => openFilteredTransactions({ category: item.key }), colour: "category" });
    barChart($("analytics-merchants"), merchants.merchants.map((item) => ({
      label: item.merchant, minor: item.amount.minor, merchant: item.merchant,
    })), { onClick: (item) => openFilteredTransactions({ merchant: item.merchant }), colour: "merchant" });
    columnChart($("analytics-weekly"), weekly.weeks.map((item) => ({
      label: item.start.slice(5), start: item.start, expenses: item.expenses, income: item.income,
    })), { onClick: (item) => selectWeek(item.start) });
    renderInsights($("analytics-insights"), insights.insights);
    renderRecurring($("recurring-full"), recurring, true);
  } catch (error) { setError(error.message); }
};

const loadBudgets = async () => {
  try {
    const month = monthFromDate(state.start);
    const payload = await api(`/api/budgets?month=${month}`);
    renderBudgets($("budget-list"), payload, true);
  } catch (error) { setError(error.message); }
};

const loadTransactions = async () => {
  try {
    const parameters = {
      search: state.search,
      category: state.category,
      merchant: state.merchant,
      review_status: state.review,
      ids: state.ids,
      sort: state.sort,
      direction: state.direction,
      limit: state.limit,
      offset: state.offset,
    };
    const payload = await api(`/api/transactions?${queryString(parameters)}`);
    $("tx-search").value = state.search;
    $("tx-category").value = state.category;
    $("tx-review").value = state.review;
    $("tx-sort").value = state.sort;
    $("tx-summary").textContent = `${payload.total} transaction(s) · showing ${payload.transactions.length}`;
    renderTransactions($("tx-output"), payload.transactions);
    const page = Math.floor(state.offset / state.limit) + 1;
    const pages = Math.max(1, Math.ceil(payload.total / state.limit));
    $("tx-page").textContent = `Page ${page} of ${pages}`;
    $("tx-prev").disabled = state.offset === 0;
    $("tx-next").disabled = state.offset + state.limit >= payload.total;
    persistState();
  } catch (error) { setError(error.message); }
};

const loadReview = async () => {
  try {
    const payload = await api("/api/review?limit=200");
    const count = payload.review.length;
    $("review-total").textContent = `${count} pending`;
    $("review-count").textContent = String(count);
    $("review-count").hidden = count === 0;
    if (!count) {
      $("review-list").innerHTML = '<p class="muted">No transactions need review. High-confidence deterministic categories are confirmed automatically.</p>';
      return;
    }
    const options = Object.entries(state.categories)
      .map(([key, label]) => `<option value="${escapeHtml(key)}">${escapeHtml(label)}</option>`).join("");
    $("review-list").innerHTML = payload.review.map((item) => `
      <article class="review-card">
        <div class="budget-line">
          <strong>${escapeHtml(item.merchant)}</strong>
          <span>${money(item.amount)}</span>
        </div>
        <div class="budget-meta">${escapeHtml(item.date)} · ${escapeHtml(item.classification)} · ${escapeHtml(item.category)}
          · ${item.needs_merchant_review ? "merchant review" : ""} ${item.needs_classification_review ? "classification review" : ""}</div>
        <div class="grid">
          <label>Category<select data-field="category">${options}</select></label>
          <label>Classification<select data-field="classification">
            <option value="expense_candidate">Expense</option>
            <option value="income_candidate">Income</option>
            <option value="transfer_candidate">Transfer</option>
            <option value="refund_candidate">Refund</option>
            <option value="reversal_candidate">Reversal</option>
            <option value="fee_candidate">Fee</option>
            <option value="cash_withdrawal_candidate">Cash withdrawal</option>
            <option value="savings_candidate">Savings</option>
          </select></label>
          <label>Merchant<input data-field="merchant" value="${escapeHtml(item.merchant)}"></label>
        </div>
        <label class="check"><input type="checkbox" data-field="future"> Apply to future transactions from this merchant</label>
        <div class="review-actions">
          <button class="button button-small button-primary" data-action="save-review" data-id="${escapeHtml(item.id)}">Save correction</button>
          <button class="button button-small" data-action="open-tx" data-id="${escapeHtml(item.id)}">Open &amp; split</button>
          <button class="button button-small" data-action="confirm-tx" data-id="${escapeHtml(item.id)}">Confirm</button>
        </div>
      </article>`).join("");
    payload.review.forEach((item) => {
      const button = document.querySelector(`[data-action="save-review"][data-id="${CSS.escape(item.id)}"]`);
      const card = button ? button.closest(".review-card") : null;
      if (card) {
        card.querySelector('[data-field="category"]').value = item.category;
        card.querySelector('[data-field="classification"]').value = item.classification;
      }
    });
  } catch (error) { setError(error.message); }
};

const loadMerchants = async () => {
  try {
    const payload = await api("/api/merchant-entities");
    const options = Object.entries(state.categories)
      .map(([key, label]) => `<option value="${escapeHtml(key)}">${escapeHtml(label)}</option>`).join("");
    $("merchant-entities").innerHTML = payload.merchants.length ? payload.merchants.map((item) => `
      <div class="merchant-row">
        <div class="merchant-line"><strong>${escapeHtml(item.canonical_name)}</strong><span>${money(item.total)}</span></div>
        <div class="merchant-meta">${item.transaction_count} transaction(s) · default: ${escapeHtml(item.default_category_label || "none")}</div>
        <div class="merchant-meta">Aliases: ${item.aliases.length ? item.aliases.map((alias) => `
          ${escapeHtml(alias)} <button class="button button-small button-danger" data-action="delete-alias" data-alias="${escapeHtml(alias)}">remove</button>
        `).join(" · ") : "none"}</div>
        <div class="review-actions">
          <select data-merchant-default="${escapeHtml(item.canonical_name)}"><option value="">No default</option>${options}</select>
          <button class="button button-small" data-action="save-merchant-default" data-name="${escapeHtml(item.canonical_name)}">Save default</button>
          <button class="button button-small" data-action="merchant-history" data-name="${escapeHtml(item.canonical_name)}">History</button>
        </div>
      </div>`).join("") : '<p class="muted">No merchant entities yet. Aliases create canonical identities.</p>';
    payload.merchants.forEach((item) => {
      const select = document.querySelector(`[data-merchant-default="${CSS.escape(item.canonical_name)}"]`);
      if (select && item.default_category) select.value = item.default_category;
    });
  } catch (error) { setError(error.message); }
};

const loadRules = async () => {
  try {
    const payload = await api("/api/rules");
    $("rules-list").innerHTML = payload.rules.length ? payload.rules.map((item) => `
      <div class="rule-row">
        <div class="merchant-line"><strong>${escapeHtml(item.merchant_pattern || item.descriptor_pattern || item.pattern)}</strong>
          <span>${escapeHtml(item.category_label)}</span></div>
        <div class="merchant-meta">priority ${item.priority} · ${escapeHtml(item.classification)} · confidence ${item.confidence} · ${item.enabled ? "enabled" : "disabled"}${item.label ? ` · ${escapeHtml(item.label)}` : ""}</div>
        <div class="review-actions"><button class="button button-small button-danger" data-action="delete-rule" data-id="${escapeHtml(item.id)}">Delete rule</button></div>
      </div>`).join("") : '<p class="muted">No explicit rules. Corrections can optionally create one.</p>';
  } catch (error) { setError(error.message); }
};

const loadImports = async () => {
  try {
    const payload = await api("/api/imports");
    $("imports-list").innerHTML = payload.imports.length ? payload.imports.map((item) => `
      <div class="import-row">
        <div class="import-line"><strong>${escapeHtml(item.source_format)}</strong><span>${escapeHtml(item.status)}</span></div>
        <div class="import-meta">${item.inserted_count}/${item.transaction_count} inserted · ${item.exact_duplicate_count} exact duplicates · ${item.possible_duplicate_count} possible · ${escapeHtml(item.created_at)}</div>
        <div class="review-actions"><button class="button button-small button-danger" data-action="undo-import" data-id="${escapeHtml(item.id)}">Undo import</button></div>
      </div>`).join("") : '<p class="muted">No imports yet. Use the CLI to import a statement.</p>';
  } catch (error) { setError(error.message); }
};

const loadIntegrity = async () => {
  try {
    const payload = await api("/api/integrity");
    const clean = payload.integrity === "ok" && !payload.foreign_key_violations.length && !payload.split_violations.length;
    $("integrity").innerHTML = clean
      ? '<span class="badge">Integrity OK</span>'
      : `<span class="badge warning">Integrity issue</span><p class="muted">Foreign keys: ${payload.foreign_key_violations.length}; split violations: ${payload.split_violations.length}</p>`;
  } catch (error) { $("integrity").textContent = error.message; }
};

const loadInsightsFull = async () => {
  try {
    const query = queryString();
    const payload = await api(`/api/insights?${query}`);
    renderInsights($("insights-full"), payload.insights);
  } catch (error) { setError(error.message); }
};

const openFilteredTransactions = ({ ids = "", category = "", merchant = "" } = {}) => {
  state.ids = ids;
  state.category = category;
  state.merchant = merchant;
  state.offset = 0;
  showSection("transactions");
  $("tx-search").value = state.search;
};

const selectMonth = (month) => {
  const [year, monthNumber] = month.split("-").map(Number);
  const start = new Date(year, monthNumber - 1, 1);
  state.start = localDate(start);
  state.end = localDate(nextMonth(start));
  $("start").value = state.start;
  $("end").value = state.end;
  showSection("overview", { load: false });
  refreshAll();
};

const selectWeek = (startText) => {
  const start = new Date(`${startText}T12:00:00`);
  state.start = localDate(start);
  state.end = localDate(new Date(start.getFullYear(), start.getMonth(), start.getDate() + 7));
  $("start").value = state.start;
  $("end").value = state.end;
  persistState();
  loadOverview();
};

const loadForSection = (name) => {
  if (name === "overview") loadOverview();
  if (name === "analytics") loadAnalytics();
  if (name === "budgets") loadBudgets();
  if (name === "transactions") loadTransactions();
  if (name === "review") loadReview();
  if (name === "merchants") { loadMerchants(); loadRules(); }
  if (name === "insights") { loadInsightsFull(); api("/api/recurring").then((payload) => renderRecurring($("recurring-full"), payload, true)).catch(() => {}); }
  if (name === "settings") { loadImports(); loadIntegrity(); }
};

const refreshAll = async () => {
  state.start = $("start").value;
  state.end = $("end").value;
  if (!state.start || !state.end || state.start >= state.end) {
    setError("Start date must be before end date.");
    clearOverview();
    $("loading").hidden = true;
    return;
  }
  persistState();
  $("loading").hidden = false;
  try {
    await Promise.all([loadHealth(), loadOverview()]);
    if (state.section !== "overview") loadForSection(state.section);
  } finally {
    $("loading").hidden = true;
  }
};

const transactionDetail = async (id) => {
  const payload = await api(`/api/transactions?start=1900-01-01&end=2100-01-01&ids=${encodeURIComponent(id)}&limit=1`);
  return payload.transactions[0];
};

const openEditor = async (id) => {
  try {
    const row = await transactionDetail(id);
    if (!row) throw new Error("Transaction not found.");
    showSection("transactions", { load: false });
    const categoryOptions = Object.entries(state.categories)
      .map(([key, label]) => `<option value="${escapeHtml(key)}" ${key === row.category ? "selected" : ""}>${escapeHtml(label)}</option>`).join("");
    const classificationOptions = [
      ["expense_candidate", "Expense"], ["income_candidate", "Income"],
      ["transfer_candidate", "Transfer"], ["refund_candidate", "Refund"],
      ["reversal_candidate", "Reversal"], ["fee_candidate", "Fee"],
      ["cash_withdrawal_candidate", "Cash withdrawal"], ["savings_candidate", "Savings"],
    ].map(([value, label]) => `<option value="${value}" ${value === row.classification ? "selected" : ""}>${label}</option>`).join("");
    const splits = await api(`/api/transactions/${encodeURIComponent(id)}/splits`);
    $("tx-editor").hidden = false;
    $("tx-editor-body").innerHTML = `
      <div class="budget-line"><strong>${escapeHtml(row.merchant)}</strong><span>${money(row.amount)} · ${escapeHtml(row.date)}</span></div>
      <p class="muted">${escapeHtml(row.description)}</p>
      <form id="edit-form" class="form">
        <label>Merchant<input id="edit-merchant" value="${escapeHtml(row.merchant)}"></label>
        <label>Category<select id="edit-category">${categoryOptions}</select></label>
        <label>Classification<select id="edit-classification">${classificationOptions}</select></label>
        <label>Note<input id="edit-note" value="${escapeHtml(row.note || "")}"></label>
        <label>Evidence used<input value="${escapeHtml(row.evidence || "none")}" readonly></label>
        <label class="check"><input id="edit-future" type="checkbox"> Apply this classification to future transactions from this merchant</label>
        <div class="review-actions">
          <button class="button button-primary" type="submit">Save correction</button>
          <button class="button" type="button" data-action="confirm-tx" data-id="${escapeHtml(row.id)}">Confirm</button>
          <button class="button" type="button" data-action="undo-tx" data-id="${escapeHtml(row.id)}">Undo correction</button>
          <button class="button" type="button" data-action="close-editor">Close</button>
        </div>
      </form>
      <h3>Link a refund or reversal</h3>
      <div class="split-row">
        <input id="link-target" placeholder="Original transaction ID">
        <select id="link-type"><option value="refund">Refund</option><option value="reversal">Reversal</option></select>
        <button class="button" type="button" data-action="save-link" data-id="${escapeHtml(row.id)}">Link</button>
      </div>
      <h3>Split transaction</h3>
      ${splits.splits.length ? `<div class="review-list">${splits.splits.map((item) => `
        <div class="budget-row"><div class="budget-line"><strong>${escapeHtml(item.category_label)}</strong><span>${money(item.amount)}</span></div>
        <div class="budget-meta">${escapeHtml(item.note || "no note")}</div></div>`).join("")}</div>
        <button class="button button-danger" data-action="remove-split" data-id="${escapeHtml(row.id)}">Remove split</button>`
      : `<div id="split-rows">
          <div class="split-row"><input class="split-amount" inputmode="decimal" placeholder="Amount EUR"><select class="split-category">${categoryOptions}</select></div>
          <div class="split-row"><input class="split-amount" inputmode="decimal" placeholder="Amount EUR"><select class="split-category">${categoryOptions}</select></div>
         </div>
         <button class="button" type="button" data-action="add-split-row">Add allocation</button>
         <button class="button button-primary" type="button" data-action="save-split" data-id="${escapeHtml(row.id)}">Save split</button>`}
    `;
    $("edit-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        await api(`/api/transactions/${encodeURIComponent(row.id)}/correct`, {
          method: "POST",
          body: JSON.stringify({
            merchant: $("edit-merchant").value,
            category_key: $("edit-category").value,
            classification: $("edit-classification").value,
            note: $("edit-note").value,
            apply_to_future: $("edit-future").checked,
          }),
        });
        setError("");
        await Promise.all([loadTransactions(), loadReview(), loadOverview()]);
        await openEditor(row.id);
      } catch (error) { setError(error.message); }
    });
  } catch (error) { setError(error.message); }
};

const saveReview = async (id) => {
  const button = document.querySelector(`[data-action="save-review"][data-id="${CSS.escape(id)}"]`);
  const card = button ? button.closest(".review-card") : null;
  if (!card) return;
  try {
    await api(`/api/transactions/${encodeURIComponent(id)}/correct`, {
      method: "POST",
      body: JSON.stringify({
        merchant: card.querySelector('[data-field="merchant"]').value,
        category_key: card.querySelector('[data-field="category"]').value,
        classification: card.querySelector('[data-field="classification"]').value,
        apply_to_future: card.querySelector('[data-field="future"]').checked,
      }),
    });
    setError("");
    await Promise.all([loadReview(), loadOverview()]);
  } catch (error) { setError(error.message); }
};

const quickAction = async (id, action) => {
  try {
    await api(`/api/transactions/${encodeURIComponent(id)}/${action}`, { method: "POST" });
    setError("");
    await Promise.all([loadReview(), loadTransactions(), loadOverview()]);
  } catch (error) { setError(error.message); }
};

const askQuestion = async (question) => {
  if (!question.trim()) return;
  $("ask-answer").textContent = "Thinking locally…";
  try {
    const answer = await api("/api/ask", {
      method: "POST",
      body: JSON.stringify({ question, month: monthFromDate(state.start) }),
    });
    $("ask-answer").innerHTML = `${escapeHtml(answer.text)}<div class="meta">Intent: ${escapeHtml(answer.intent)} · Period: ${escapeHtml(answer.period.start)} to ${escapeHtml(answer.period.end)} · Confidence: ${escapeHtml(answer.confidence)}${answer.uncertainty ? ` · ${escapeHtml(answer.uncertainty)}` : ""}</div>`;
  } catch (error) {
    $("ask-answer").innerHTML = `<span class="notice-error">${escapeHtml(error.message)}</span>`;
  }
};

const TRANSFER_CATEGORIES = ["transfers", "transfers.blocked_account"];

const syncClassificationForCategory = (categorySelect, classificationSelect) => {
  if (!categorySelect || !classificationSelect) return;
  if (TRANSFER_CATEGORIES.includes(categorySelect.value)) {
    classificationSelect.value = "transfer_candidate";
  }
};

const IMPORT_CLASSIFICATIONS = [
  ["expense_candidate", "Expense"],
  ["income_candidate", "Income"],
  ["transfer_candidate", "Transfer"],
  ["refund_candidate", "Refund"],
  ["reversal_candidate", "Reversal"],
  ["fee_candidate", "Fee"],
  ["cash_withdrawal_candidate", "Cash withdrawal"],
  ["savings_candidate", "Savings"],
  ["unknown", "Unknown"],
];

const importCategoryOptions = (selected) => Object.entries(state.categories)
  .map(([key, label]) => `<option value="${escapeHtml(key)}" ${key === selected ? "selected" : ""}>${escapeHtml(label)}</option>`)
  .join("");

const importClassificationOptions = (selected) => IMPORT_CLASSIFICATIONS
  .map(([value, label]) => `<option value="${escapeHtml(value)}" ${value === selected ? "selected" : ""}>${escapeHtml(label)}</option>`)
  .join("");

const importClassificationLabel = (value) => {
  const match = IMPORT_CLASSIFICATIONS.find(([key]) => key === value);
  return match ? match[1] : value;
};

const importRowCard = (row) => `
  <article class="import-card" data-row="${row.row_number}"
    data-suggested-merchant="${escapeHtml(row.merchant)}"
    data-suggested-category="${escapeHtml(row.category)}"
    data-suggested-classification="${escapeHtml(row.classification)}"
    data-review-required="${row.review_required ? "1" : "0"}">
    <div class="import-card-head">
      <div>
        <strong>${escapeHtml(row.merchant || "Unknown merchant")}</strong>
        <span class="muted">${escapeHtml(row.date)} · ${escapeHtml(String(row.payment_channel || "unknown").replace(/_/g, " "))}</span>
      </div>
      <strong class="import-amount">${money(row.amount)}</strong>
    </div>
    <p class="import-description">${escapeHtml(row.description || row.booking_text || "No description")}</p>
    ${row.counterparty ? `<p class="import-counterparty">Counterparty: ${escapeHtml(row.counterparty)}</p>` : ""}
    <p class="import-suggestion"><span class="muted">Suggested</span> ${escapeHtml(importClassificationLabel(row.classification))} → ${escapeHtml(row.category_label)} <span class="muted">${Math.round((row.category_confidence || 0) * 100)}%</span></p>
    <div class="import-badges">
      ${row.review_required ? '<span class="badge warning">needs review</span>' : ""}
      ${row.duplicate_reason ? '<span class="badge warning">possible duplicate</span>' : ""}
    </div>
    <details class="import-edit">
      <summary>Edit this row</summary>
      <div class="form">
        <label>Merchant<input data-import-field="merchant" value="${escapeHtml(row.merchant)}"></label>
        <label>Category<select data-import-field="category">${importCategoryOptions(row.category)}</select></label>
        <label>Type<select data-import-field="classification">${importClassificationOptions(row.classification)}</select></label>
        <label>Note<input data-import-field="note" value=""></label>
        <label>Learn from this edit
          <select data-import-field="remember">
            <option value="">This transaction only</option>
            <option value="merchant" ${row.merchant_learnable ? "" : "disabled"}>Remember this merchant in future</option>
            <option value="descriptor" ${row.descriptor_pattern ? "" : "disabled"}>Remember this description in future${row.descriptor_pattern ? ` (“${escapeHtml(row.descriptor_pattern)}”)` : ""}</option>
          </select>
        </label>
        <button class="button button-small" type="button" data-action="reset-import-row">Reset to suggestion</button>
      </div>
      <p class="muted">Why: ${escapeHtml(row.evidence || "no strong evidence")}</p>
    </details>
  </article>`;

const filterImportRows = () => {
  const term = $("import-search").value.trim().toLowerCase();
  const onlyReview = $("import-only-review").checked;
  let visible = 0;
  document.querySelectorAll(".import-card").forEach((card) => {
    const matchesText = !term || card.textContent.toLowerCase().includes(term);
    const matchesReview = !onlyReview || card.dataset.reviewRequired === "1";
    card.hidden = !(matchesText && matchesReview);
    if (!card.hidden) visible += 1;
  });
  let empty = document.getElementById("import-filter-empty");
  if (!empty) {
    empty = document.createElement("p");
    empty.id = "import-filter-empty";
    empty.className = "empty";
    empty.textContent = "No rows match this filter.";
    $("import-rows").appendChild(empty);
  }
  empty.hidden = visible > 0;
};

const importCommitButtons = () => ["import-commit", "import-commit-bottom"]
  .map((id) => $(id))
  .filter(Boolean);

const setImportCommitState = ({ disabled, label, pending = false }) => {
  importCommitButtons().forEach((button) => {
    button.disabled = Boolean(disabled);
    if (label) button.textContent = label;
  });
  const status = $("import-edit-status");
  if (status) status.classList.toggle("pending", pending);
};

const importRowEdits = (card) => {
  const merchant = card.querySelector('[data-import-field="merchant"]').value.trim();
  const category = card.querySelector('[data-import-field="category"]').value;
  const classification = card.querySelector('[data-import-field="classification"]').value;
  const note = card.querySelector('[data-import-field="note"]').value.trim();
  const remember = card.querySelector('[data-import-field="remember"]').value;
  const edited = merchant !== card.dataset.suggestedMerchant
    || category !== card.dataset.suggestedCategory
    || classification !== card.dataset.suggestedClassification
    || Boolean(note)
    || Boolean(remember);
  return { merchant, category, classification, note, remember, edited };
};

const updateImportEditStatus = () => {
  const status = $("import-edit-status");
  if (!status) return;
  const cards = [...document.querySelectorAll(".import-card")];
  const edited = cards.filter((card) => importRowEdits(card).edited).length;
  if (!cards.length) {
    status.textContent = "No rows in this preview.";
    return;
  }
  status.textContent = edited
    ? `${edited} of ${cards.length} row(s) edited — tap Import to save these changes`
    : `${cards.length} row(s) ready — nothing edited yet`;
};

const markImportRowsSaved = () => {
  document.querySelectorAll(".import-card").forEach((card) => {
    const values = importRowEdits(card);
    card.dataset.suggestedMerchant = values.merchant;
    card.dataset.suggestedCategory = values.category;
    card.dataset.suggestedClassification = values.classification;
    card.querySelector('[data-import-field="note"]').value = "";
    card.querySelector('[data-import-field="remember"]').value = "";
  });
};

const renderImportPreview = (payload) => {
  state.importPreview = payload;
  $("import-preview").hidden = false;
  $("import-summary-title").textContent = payload.file_name;
  const possible = payload.possible_duplicate_count || (payload.existing_import ? payload.existing_import.possible_duplicate_count : 0);
  const fullyImported = Boolean(payload.existing_import && payload.existing_import.status === "completed" && payload.existing_import.possible_duplicate_count === 0);
  $("import-summary-badge").textContent = fullyImported ? "Already imported" : "Ready to review";
  $("import-summary-badge").className = fullyImported ? "badge warning" : "badge";
  $("import-summary").innerHTML = `
    <div><span>Rows</span><strong>${payload.transaction_count}</strong></div>
    <div><span>Period</span><strong>${escapeHtml(payload.first_date)} → ${escapeHtml(payload.last_date)}</strong></div>
    <div><span>Money in</span><strong>${money(payload.total_in)}</strong></div>
    <div><span>Money out</span><strong>${money(payload.total_out)}</strong></div>
    <div><span>Uncategorised</span><strong>${payload.uncategorized_count}</strong></div>
    <div><span>Needs review</span><strong>${payload.review_required_count}</strong></div>
    <div><span>Possible duplicates</span><strong>${possible}</strong></div>
    <div><span>Exact file match</span><strong>${payload.exact_file_match ? "Yes" : "No"}</strong></div>`;
  const notice = $("import-duplicate-notice");
  if (fullyImported) {
    notice.hidden = false;
    notice.textContent = "This exact file is already fully imported. No rows will be added.";
  } else if (payload.existing_import && payload.existing_import.possible_duplicate_count > 0) {
    notice.hidden = false;
    notice.textContent = `This file was partially imported. ${payload.existing_import.possible_duplicate_count} possible duplicate row(s) were skipped. Check “Include possible duplicates” and import again to add them.`;
  } else if (possible > 0) {
    notice.hidden = false;
    notice.textContent = `${possible} possible duplicate row(s) were found. They are skipped unless you check “Include possible duplicates”.`;
  } else if (payload.reference_matches > 0) {
    notice.hidden = false;
    notice.textContent = `${payload.reference_matches} row(s) match an existing bank reference and will be skipped.`;
  } else {
    notice.hidden = true;
    notice.textContent = "";
  }
  $("import-accept-duplicates-wrap").hidden = possible === 0;
  $("import-accept-duplicates").checked = Boolean(payload.existing_import && payload.existing_import.possible_duplicate_count > 0);
  setImportCommitState({
    disabled: fullyImported,
    label: fullyImported ? "Already imported" : "Import rows",
  });
  $("import-rows").innerHTML = payload.rows.map(importRowCard).join("");
  $("import-search").value = "";
  $("import-only-review").checked = false;
  filterImportRows();
  updateImportEditStatus();
};

const resetImportPreview = () => {
  state.importPreview = null;
  $("import-preview").hidden = true;
  $("import-form").reset();
  $("import-file-label").textContent = "Sparkasse CSV-CAMT V8 export";
  $("import-progress").hidden = true;
  $("import-error").hidden = true;
  setImportCommitState({ disabled: false, label: "Import rows" });
  $("import-edit-status").textContent = "Choose a file to preview it.";
};

const readApiError = async (response) => {
  try {
    const body = await response.json();
    if (body && body.detail) return formatApiDetail(body.detail);
  } catch (error) { /* fall through */ }
  return `Request failed (${response.status})`;
};

const previewImportFile = async () => {
  const file = $("import-file").files[0];
  if (!file) throw new Error("Choose a CSV file first.");
  $("import-error").hidden = true;
  $("import-progress").hidden = false;
  $("import-progress").textContent = "Parsing the statement locally…";
  const body = new FormData();
  body.append("file", file);
  const response = await fetch("/api/imports/preview", { method: "POST", body });
  if (!response.ok) throw new Error(await readApiError(response));
  const payload = await response.json();
  $("import-progress").hidden = true;
  renderImportPreview(payload);
};

const commitImportPreview = async () => {
  const preview = state.importPreview;
  if (!preview) return;
  const overrides = [];
  document.querySelectorAll(".import-card").forEach((card) => {
    const values = importRowEdits(card);
    const override = { row_number: Number(card.dataset.row) };
    if (values.merchant !== card.dataset.suggestedMerchant) override.merchant = values.merchant;
    if (values.category !== card.dataset.suggestedCategory) override.category_key = values.category;
    if (values.classification !== card.dataset.suggestedClassification) override.classification = values.classification;
    if (values.note) override.note = values.note;
    if (values.remember) override.remember = values.remember;
    if (Object.keys(override).length > 1) overrides.push(override);
  });
  $("import-error").hidden = true;
  $("import-progress").hidden = false;
  $("import-progress").textContent = "Importing into the local database…";
  importCommitButtons().forEach((button) => { button.disabled = true; });
  $("import-edit-status").textContent = "Saving changes to the local database…";
  try {
    const result = await api("/api/imports/commit", {
      method: "POST",
      body: JSON.stringify({
        preview_id: preview.preview_id,
        accept_possible_duplicates: $("import-accept-duplicates").checked,
        overrides,
      }),
    });
    let message = result.inserted
      ? `Imported ${result.inserted} row(s). You can change any category later under Transactions.`
      : "No rows were added.";
    if (result.exact_duplicates) message += ` ${result.exact_duplicates} exact duplicate(s) skipped.`;
    if (result.possible_duplicates) message += ` ${result.possible_duplicates} possible duplicate(s) skipped.`;
    if (result.learned && result.learned.length) message += ` Remembered ${result.learned.length} row(s) for future imports.`;
    if (result.learning_errors && result.learning_errors.length) message += ` Learning issues: ${result.learning_errors.join("; ")}`;
    if (result.already_imported_file && !result.inserted) message = "This exact file was already imported; no rows were added.";
    $("import-progress").textContent = message;
    $("import-progress").className = result.possible_duplicates || (result.learning_errors && result.learning_errors.length) ? "notice notice-warning" : "notice";
    if (result.possible_duplicates) {
      // Keep the edits so the follow-up commit applies them to the skipped rows.
      $("import-duplicate-notice").hidden = false;
      $("import-duplicate-notice").textContent = `${result.possible_duplicates} possible duplicate row(s) were skipped. Check “Include possible duplicates” and tap the button again to add them.`;
      $("import-accept-duplicates-wrap").hidden = false;
      $("import-accept-duplicates").checked = true;
      setImportCommitState({ disabled: false, label: "Add skipped duplicates", pending: true });
      $("import-edit-status").textContent = `${result.possible_duplicates} duplicate row(s) still waiting. Your edits are kept for the next tap.`;
    } else {
      markImportRowsSaved();
      setImportCommitState({ disabled: true, label: "Imported" });
      updateImportEditStatus();
      $("import-edit-status").textContent = result.inserted
        ? `Saved ${result.inserted} row(s). Rows marked “needs review” are in the Review queue.`
        : "This file was already imported. Nothing new was saved.";
    }
    await Promise.all([loadHealth(), loadImports(), loadOverview(), loadReview()]);
  } catch (error) {
    $("import-error").hidden = false;
    $("import-error").textContent = error.message;
    setImportCommitState({ disabled: false, label: "Import rows" });
    updateImportEditStatus();
  }
};

const rememberEditedImportRows = () => {
  let applied = 0;
  document.querySelectorAll(".import-card").forEach((card) => {
    const values = importRowEdits(card);
    if (!values.edited) return;
    const select = card.querySelector('[data-import-field="remember"]');
    if (!select) return;
    const merchantOption = select.querySelector('option[value="merchant"]');
    const descriptorOption = select.querySelector('option[value="descriptor"]');
    if (!values.remember) {
      if (merchantOption && !merchantOption.disabled) select.value = "merchant";
      else if (descriptorOption && !descriptorOption.disabled) select.value = "descriptor";
    }
    if (select.value) applied += 1;
  });
  updateImportEditStatus();
  const status = $("import-edit-status");
  if (status) {
    status.textContent = applied
      ? `${applied} edited row(s) will be remembered. Tap Import to save.`
      : "Edit a row first, then remember it.";
  }
};

const TAB_PRIMARY = ["overview", "transactions", "import", "budgets"];

const TAB_LABELS = {
  overview: "Home",
  transactions: "Activity",
  import: "Import",
  budgets: "Budgets",
};

const TAB_ICONS = {
  overview: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/></svg>',
  transactions: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16"/><path d="M4 12h16"/><path d="M4 17h10"/></svg>',
  import: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 15V4"/><path d="m7 9 5-5 5 5"/><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/></svg>',
  budgets: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8"/><path d="M12 12V4"/><path d="M12 12l5.6 2.8"/></svg>',
  more: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="12" r="1.7"/><circle cx="12" cy="12" r="1.7"/><circle cx="19" cy="12" r="1.7"/></svg>',
};

const updateReviewBadges = () => {
  const count = state.reviewCount || 0;
  ["review-count", "sheet-review-count", "tab-more-dot"].forEach((id) => {
    const badge = $(id);
    if (!badge) return;
    badge.textContent = String(count);
    badge.hidden = count === 0;
  });
};

const setTabSheetOpen = (open) => {
  const sheet = $("tabsheet");
  const backdrop = $("tabsheet-backdrop");
  const more = $("tab-more");
  if (!sheet || !backdrop) return;
  sheet.hidden = !open;
  backdrop.hidden = !open;
  if (more) more.setAttribute("aria-expanded", open ? "true" : "false");
  if (open) {
    const first = sheet.querySelector("button");
    if (first) first.focus();
  }
};

const buildTabBar = () => {
  const bar = $("tabbar");
  const grid = $("tabsheet-grid");
  if (!bar || !grid) return;
  const links = [...document.querySelectorAll(".mainnav .navlink")];
  if (!links.length) return;
  const labelOf = (link) => {
    const clone = link.cloneNode(true);
    clone.querySelectorAll(".pill").forEach((badge) => badge.remove());
    return clone.textContent.trim();
  };
  const labels = new Map(links.map((link) => [link.dataset.section, labelOf(link)]));
  const secondary = [...labels.keys()].filter((section) => !TAB_PRIMARY.includes(section));
  bar.innerHTML = TAB_PRIMARY.filter((section) => labels.has(section)).map((section) => `
    <button class="tab" type="button" data-section="${section}">
      ${TAB_ICONS[section] || ""}
      <span>${escapeHtml(TAB_LABELS[section] || labels.get(section))}</span>
    </button>`).join("") + `
    <button class="tab" type="button" id="tab-more" aria-expanded="false" aria-controls="tabsheet">
      ${TAB_ICONS.more}
      <span>More</span>
      <span class="pill" id="tab-more-dot" hidden>0</span>
    </button>`;
  grid.innerHTML = secondary.map((section) => `
    <button type="button" data-section="${section}">${escapeHtml(labels.get(section))}${
      section === "review" ? ' <span class="pill" id="sheet-review-count" hidden>0</span>' : ""
    }</button>`).join("");
  updateReviewBadges();
};

const syncTabState = (section) => {
  document.querySelectorAll(".tab[data-section]").forEach((button) => {
    const active = button.dataset.section === section;
    button.classList.toggle("active", active);
    button.setAttribute("aria-current", active ? "page" : "false");
  });
  const more = $("tab-more");
  if (more) {
    const active = !TAB_PRIMARY.includes(section);
    more.classList.toggle("active", active);
    more.setAttribute("aria-current", active ? "page" : "false");
  }
  document.querySelectorAll("#tabsheet-grid button").forEach((button) => {
    const active = button.dataset.section === section;
    button.classList.toggle("active", active);
    button.setAttribute("aria-current", active ? "page" : "false");
  });
};

const registerServiceWorker = () => {
  if (!("serviceWorker" in navigator)) return;
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => undefined);
  });
};

let deferredInstallPrompt = null;

const bindInstallPrompt = () => {
  const button = $("install-app");
  if (!button) return;
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferredInstallPrompt = event;
    button.hidden = false;
  });
  window.addEventListener("appinstalled", () => {
    deferredInstallPrompt = null;
    button.hidden = true;
    const hint = $("install-hint");
    if (hint) hint.textContent = "Installed. Open Mint Growth Finance from your home screen.";
  });
  button.addEventListener("click", async () => {
    if (!deferredInstallPrompt) return;
    deferredInstallPrompt.prompt();
    await deferredInstallPrompt.userChoice.catch(() => undefined);
    deferredInstallPrompt = null;
    button.hidden = true;
  });
};

const bindEvents = () => {
  buildTabBar();
  bindInstallPrompt();
  document.querySelectorAll(".navlink").forEach((button) => {
    button.addEventListener("click", () => showSection(button.dataset.section));
  });
  document.addEventListener("click", (event) => {
    const tab = event.target.closest("#tabbar [data-section], #tabsheet-grid [data-section]");
    if (tab) {
      event.preventDefault();
      setTabSheetOpen(false);
      showSection(tab.dataset.section);
      return;
    }
    if (event.target.closest("#tab-more")) {
      event.preventDefault();
      setTabSheetOpen($("tabsheet").hidden);
      return;
    }
    if (event.target.closest("#tabsheet-close") || event.target.id === "tabsheet-backdrop") {
      event.preventDefault();
      setTabSheetOpen(false);
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && $("tabsheet") && !$("tabsheet").hidden) setTabSheetOpen(false);
  });
  $("refresh").addEventListener("click", refreshAll);
  $("import-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await previewImportFile();
    } catch (error) {
      $("import-progress").hidden = true;
      $("import-error").hidden = false;
      $("import-error").textContent = error.message;
    }
  });
  $("import-file").addEventListener("change", () => {
    const file = $("import-file").files[0];
    $("import-file-label").textContent = file ? file.name : "Sparkasse CSV-CAMT V8 export";
  });
  importCommitButtons().forEach((button) => {
    button.addEventListener("click", commitImportPreview);
  });
  $("import-remember-edits").addEventListener("click", rememberEditedImportRows);
  $("import-reset").addEventListener("click", resetImportPreview);
  $("import-search").addEventListener("input", filterImportRows);
  $("import-only-review").addEventListener("change", filterImportRows);
  $("import-rows").addEventListener("input", updateImportEditStatus);
  document.addEventListener("change", (event) => {
    const target = event.target;
    if (!target || target.tagName !== "SELECT") return;
    if (target.id === "edit-category") {
      syncClassificationForCategory(target, $("edit-classification"));
      return;
    }
    if (target.dataset.importField === "category") {
      const card = target.closest(".import-card");
      syncClassificationForCategory(target, card ? card.querySelector('[data-import-field="classification"]') : null);
      return;
    }
    if (target.dataset.field === "category") {
      const card = target.closest(".review-card");
      syncClassificationForCategory(target, card ? card.querySelector('[data-field="classification"]') : null);
    }
  });
  $("import-rows").addEventListener("change", updateImportEditStatus);
  $("search-button").addEventListener("click", () => { state.search = $("search").value; loadOverviewTransactions(); });
  $("search").addEventListener("keydown", (event) => {
    if (event.key === "Enter") { state.search = $("search").value; loadOverviewTransactions(); }
  });
  $("tx-apply").addEventListener("click", () => {
    state.search = $("tx-search").value;
    state.category = $("tx-category").value;
    state.review = $("tx-review").value;
    state.sort = $("tx-sort").value;
    state.offset = 0;
    state.ids = "";
    loadTransactions();
  });
  $("tx-clear").addEventListener("click", () => {
    state.search = ""; state.category = ""; state.review = ""; state.merchant = "";
    state.ids = ""; state.offset = 0;
    $("tx-search").value = ""; $("tx-category").value = ""; $("tx-review").value = "";
    loadTransactions();
  });
  $("tx-prev").addEventListener("click", () => {
    state.offset = Math.max(0, state.offset - state.limit);
    loadTransactions();
  });
  $("tx-next").addEventListener("click", () => {
    state.offset += state.limit;
    loadTransactions();
  });
  $("budget-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const limit = parseMinor($("budget-limit").value);
      const category = $("budget-category").value;
      await api("/api/budgets", {
        method: "POST",
        body: JSON.stringify({ month: monthFromDate(state.start), category_key: category, limit_minor: limit }),
      });
      const threshold = $("budget-threshold").value;
      if (threshold) {
        await api("/api/budgets/alert", {
          method: "POST",
          body: JSON.stringify({ category_key: category, threshold_percent: Number.parseInt(threshold, 10), enabled: true }),
        });
      }
      setError("");
      await Promise.all([loadBudgets(), loadOverview()]);
    } catch (error) { setError(error.message); }
  });
  $("alias-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api("/api/merchant-entities/alias", {
        method: "POST",
        body: JSON.stringify({
          alias: $("alias-input").value,
          canonical_name: $("alias-canonical").value,
          default_category_key: $("alias-category").value || null,
        }),
      });
      $("alias-input").value = ""; $("alias-canonical").value = "";
      setError("");
      await loadMerchants();
    } catch (error) { setError(error.message); }
  });
  $("merge-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api("/api/merchant-entities/merge", {
        method: "POST",
        body: JSON.stringify({
          source_canonical: $("merge-source").value,
          target_canonical: $("merge-target").value,
          confirm: $("merge-confirm").checked,
        }),
      });
      setError("");
      await loadMerchants();
    } catch (error) { setError(error.message); }
  });
  $("rule-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api("/api/rules", {
        method: "POST",
        body: JSON.stringify({
          merchant_pattern: $("rule-merchant").value || null,
          descriptor_pattern: $("rule-descriptor").value || null,
          category_key: $("rule-category").value,
          classification: $("rule-classification").value,
          priority: Number.parseInt($("rule-priority").value || "150", 10),
        }),
      });
      setError("");
      await loadRules();
    } catch (error) { setError(error.message); }
  });
  $("merchant-history-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = $("merchant-history-name").value;
    try {
      const payload = await api(`/api/transactions?start=1900-01-01&end=2100-01-01&merchant=${encodeURIComponent(name)}&limit=100`);
      renderTransactions($("merchant-history"), payload.transactions);
    } catch (error) { setError(error.message); }
  });
  $("ask-form").addEventListener("submit", (event) => {
    event.preventDefault();
    askQuestion($("ask-input").value);
  });
  document.querySelectorAll("[data-question]").forEach((button) => {
    button.addEventListener("click", () => {
      $("ask-input").value = button.dataset.question;
      askQuestion(button.dataset.question);
    });
  });
  $("tx-editor-close").addEventListener("click", () => { $("tx-editor").hidden = true; });

  document.addEventListener("click", async (event) => {
    const target = event.target.closest("[data-action]");
    if (!target) return;
    const action = target.dataset.action;
    if (action === "open-tx" || action === "edit-tx") { event.preventDefault(); openEditor(target.dataset.id); }
    if (action === "reset-import-row") {
      event.preventDefault();
      const card = target.closest(".import-card");
      if (!card) return;
      card.querySelector('[data-import-field="merchant"]').value = card.dataset.suggestedMerchant;
      card.querySelector('[data-import-field="category"]').value = card.dataset.suggestedCategory;
      card.querySelector('[data-import-field="classification"]').value = card.dataset.suggestedClassification;
      card.querySelector('[data-import-field="note"]').value = "";
      card.querySelector('[data-import-field="remember"]').value = "";
      updateImportEditStatus();
    }
    if (action === "save-review") { event.preventDefault(); saveReview(target.dataset.id); }
    if (action === "confirm-tx") { event.preventDefault(); quickAction(target.dataset.id, "confirm"); }
    if (action === "undo-tx") { event.preventDefault(); quickAction(target.dataset.id, "undo"); }
    if (action === "delete-budget") {
      event.preventDefault();
      try {
        await api(`/api/budgets?month=${encodeURIComponent(target.dataset.month)}&category=${encodeURIComponent(target.dataset.category)}`, { method: "DELETE" });
        await Promise.all([loadBudgets(), loadOverview()]);
      } catch (error) { setError(error.message); }
    }
    if (action === "delete-alias") {
      event.preventDefault();
      try {
        await api(`/api/merchant-entities/alias?alias=${encodeURIComponent(target.dataset.alias)}`, { method: "DELETE" });
        await loadMerchants();
      } catch (error) { setError(error.message); }
    }
    if (action === "save-merchant-default") {
      event.preventDefault();
      const select = document.querySelector(`[data-merchant-default="${CSS.escape(target.dataset.name)}"]`);
      try {
        await api("/api/merchant-entities/default", {
          method: "POST",
          body: JSON.stringify({ canonical_name: target.dataset.name, category_key: select.value || null }),
        });
        await loadMerchants();
      } catch (error) { setError(error.message); }
    }
    if (action === "merchant-history") {
      event.preventDefault();
      $("merchant-history-name").value = target.dataset.name;
      try {
        const payload = await api(`/api/transactions?start=1900-01-01&end=2100-01-01&merchant=${encodeURIComponent(target.dataset.name)}&limit=100`);
        renderTransactions($("merchant-history"), payload.transactions);
      } catch (error) { setError(error.message); }
    }
    if (action === "reprocess") {
      event.preventDefault();
      try {
        const result = await api("/api/reprocess", { method: "POST" });
        await Promise.all([loadRules(), loadOverview()]);
        setError(`Reapplied rules to ${result.updated} transaction(s).`);
      } catch (error) { setError(error.message); }
    }
    if (action === "delete-rule") {
      event.preventDefault();
      try {
        await api(`/api/rules/${encodeURIComponent(target.dataset.id)}`, { method: "DELETE" });
        await loadRules();
      } catch (error) { setError(error.message); }
    }
    if (action === "undo-import") {
      event.preventDefault();
      if (!confirm("Undo this import? Only this batch is removed; corrections block undo.")) return;
      try {
        await api(`/api/imports/${encodeURIComponent(target.dataset.id)}/undo?confirm=true`, { method: "POST" });
        await Promise.all([loadImports(), loadOverview()]);
      } catch (error) { setError(error.message); }
    }
    if (action === "recurring") {
      event.preventDefault();
      try {
        await api("/api/recurring/decision", {
          method: "POST",
          body: JSON.stringify({ merchant: target.dataset.merchant, decision: target.dataset.decision }),
        });
        const payload = await api("/api/recurring");
        renderRecurring($("recurring-full"), payload, true);
        renderRecurring($("recurring"), payload, false);
      } catch (error) { setError(error.message); }
    }
    if (action === "open-insight") {
      event.preventDefault();
      state.start = target.dataset.start || state.start;
      state.end = target.dataset.end || state.end;
      $("start").value = state.start; $("end").value = state.end;
      openFilteredTransactions({ ids: target.dataset.ids || "" });
    }
    if (action === "close-editor") { $("tx-editor").hidden = true; }
    if (action === "remove-split") {
      event.preventDefault();
      try {
        await api(`/api/transactions/${encodeURIComponent(target.dataset.id)}/split`, { method: "DELETE" });
        await openEditor(target.dataset.id);
      } catch (error) { setError(error.message); }
    }
    if (action === "save-link") {
      event.preventDefault();
      try {
        const linked = document.getElementById("link-target").value.trim();
        if (!linked) throw new Error("Enter the original transaction ID.");
        await api(`/api/transactions/${encodeURIComponent(target.dataset.id)}/link`, {
          method: "POST",
          body: JSON.stringify({ linked_transaction_id: linked, link_type: document.getElementById("link-type").value }),
        });
        setError("");
        await openEditor(target.dataset.id);
      } catch (error) { setError(error.message); }
    }
    if (action === "add-split-row") {
      event.preventDefault();
      const row = document.createElement("div");
      row.className = "split-row";
      row.innerHTML = `<input class="split-amount" inputmode="decimal" placeholder="Amount EUR"><select class="split-category">${$("edit-category").innerHTML}</select>`;
      $("split-rows").appendChild(row);
    }
    if (action === "save-split") {
      event.preventDefault();
      try {
        const amounts = [...document.querySelectorAll(".split-amount")].map((input) => input.value).filter(Boolean);
        const categories = [...document.querySelectorAll(".split-category")].map((select) => select.value);
        if (amounts.length < 2) throw new Error("A split needs at least two allocations.");
        const allocations = amounts.map((amount, index) => ({
          amount_minor: parseMinor(amount),
          category_key: categories[index],
          note: "",
        }));
        await api(`/api/transactions/${encodeURIComponent(target.dataset.id)}/split`, {
          method: "POST",
          body: JSON.stringify({ allocations }),
        });
        setError("");
        await Promise.all([openEditor(target.dataset.id), loadTransactions(), loadOverview()]);
      } catch (error) { setError(error.message); }
    }
  });

  document.addEventListener("keydown", (event) => {
    if ((event.key === "Enter" || event.key === " ") && event.target.matches('.insight.clickable')) {
      event.preventDefault();
      event.target.click();
    }
  });

  window.addEventListener("hashchange", async () => {
    applyHash();
    showSection(state.section, { load: false });
    await refreshAll();
  });
};

const initialize = async () => {
  registerServiceWorker();
  await fetchCategories();
  if (!applyHash()) {
    await setDefaultDates();
  } else if (!state.start || !state.end) {
    await setDefaultDates();
  }
  bindEvents();
  showSection(state.section, { load: false });
  await refreshAll();
};

initialize();
