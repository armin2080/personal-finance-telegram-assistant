const state = { start: "", end: "", search: "" };

const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
}[character]));
const money = (value) => {
  const amount = value.minor / 100;
  return new Intl.NumberFormat("de-DE", { style: "currency", currency: value.currency }).format(amount);
};
const request = async (path) => {
  const response = await fetch(path);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
};
const setError = (message) => {
  $("error").textContent = message;
  $("error").hidden = !message;
};
const load = async () => {
  setError("");
  try {
    const query = `start=${state.start}&end=${state.end}`;
    const overview = await request(`/api/overview?${query}`);
    $("income").textContent = money(overview.income);
    $("expenses").textContent = money(overview.expenses);
    $("net").textContent = money(overview.net_cash_flow);
    $("savings").textContent = overview.savings_rate_percent === null ? "—" : `${overview.savings_rate_percent}%`;
    $("refunds").textContent = money(overview.refunds);
    $("transfers").textContent = money(overview.transfers);
    $("fees").textContent = money(overview.fees);
    $("count").textContent = overview.transaction_count;
    $("quality").textContent = overview.data_quality === "complete" ? "Reviewed data" : "Review needed";
    $("quality").classList.toggle("warning", overview.data_quality !== "complete");
    const [transactions, insights, trends, budgets, recurring] = await Promise.all([
      request(`/api/transactions?${query}&search=${encodeURIComponent(state.search)}`),
      request(`/api/insights?${query}`),
      request(`/api/trends?end_month=${state.end.slice(0, 7)}&months=6`),
      request(`/api/budgets?month=${state.start.slice(0, 7)}`),
      request("/api/recurring"),
    ]);
    $("transactions").innerHTML = transactions.transactions.length
      ? transactions.transactions.map((row) => `<tr><td>${escapeHtml(row.date)}</td><td>${escapeHtml(row.merchant)}</td><td>${escapeHtml(row.category)}</td><td>${escapeHtml(row.classification)}</td><td class="${row.review_status === "confirmed" ? "confirmed" : "review"}">${escapeHtml(row.review_status)}</td><td class="amount">${money(row.amount)}</td></tr>`).join("")
      : '<tr><td colspan="6" class="empty">No transactions match this period.</td></tr>';
    $("insights").innerHTML = insights.insights.length
      ? insights.insights.map((item) => `<div class="insight"><strong>${escapeHtml(item.title)}</strong><p>${escapeHtml(item.explanation)}</p><p>${escapeHtml(item.next_action || "")}</p></div>`).join("")
      : '<p class="muted">No evidence-backed insight for this period.</p>';
    const categories = overview.categories || [];
    const maximum = Math.max(...categories.map((item) => item.amount.minor), 1);
    $("categories").innerHTML = categories.length
      ? categories.slice(0, 8).map((item) => `<div class="bar-row"><div class="bar-label"><span>${escapeHtml(item.key)}</span><strong>${money(item.amount)}</strong></div><div class="bar-track"><div class="bar-fill" style="width:${Math.round(item.amount.minor * 100 / maximum)}%"></div></div></div>`).join("")
      : '<p class="muted">No classified categories in this period.</p>';
    const trendMaximum = Math.max(...trends.months.flatMap((item) => [item.expenses.minor, item.income.minor]), 1);
    $("trends").innerHTML = trends.months.map((item) => `<div class="trend-row"><span class="trend-label">${escapeHtml(item.month)}</span><div class="trend-line" title="Expenses: ${money(item.expenses)}" style="width:${Math.max(3, Math.round(item.expenses.minor * 100 / trendMaximum))}%"></div><div class="trend-line income" title="Income: ${money(item.income)}" style="width:${Math.max(3, Math.round(item.income.minor * 100 / trendMaximum))}%"></div></div>`).join("");
    $("budgets").innerHTML = budgets.budgets.length
      ? budgets.budgets.map((item) => `<div class="budget-row"><div class="budget-label"><span>${escapeHtml(item.category)}</span><strong>${money(item.remaining)}</strong></div><div class="budget-meta">${money(item.used)} used of ${money(item.limit)}${item.exceeded ? " · over budget" : ""}</div></div>`).join("")
      : '<p class="muted">No budgets configured for this month.</p>';
    $("recurring").innerHTML = recurring.candidates.length
      ? recurring.candidates.slice(0, 6).map((item) => `<div class="recurring-row"><div class="recurring-label"><span>${escapeHtml(item.merchant)}</span><strong>${money(item.average_amount)}</strong></div><div class="recurring-meta">${item.observations} observations · every ${item.average_interval_days} days · ${escapeHtml(item.confidence)} confidence</div></div>`).join("")
      : '<p class="muted">No repeated payment candidate has enough evidence.</p>';
  } catch (error) {
    setError(`The local dashboard could not load this view: ${error.message}`);
  }
};
const setDefaultDates = () => {
  const now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth(), 1);
  const end = new Date(now.getFullYear(), now.getMonth() + 1, 1);
  $("start").value = start.toISOString().slice(0, 10);
  $("end").value = end.toISOString().slice(0, 10);
  state.start = $("start").value;
  state.end = $("end").value;
};
const refresh = () => {
  state.start = $("start").value;
  state.end = $("end").value;
  load();
};
setDefaultDates();
load();
$("refresh").addEventListener("click", refresh);
$("search-button").addEventListener("click", () => { state.search = $("search").value; load(); });
$("search").addEventListener("keydown", (event) => { if (event.key === "Enter") { state.search = $("search").value; load(); } });
