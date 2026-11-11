// Amounts from /subscriptions are strings ("15.49"); always format per its own currency.
export function money(amount, currency) {
  const n = Number(amount);
  try { return new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(n); }
  catch { return `${n.toFixed(2)} ${currency}`; }
}

export function shortDate(iso) {
  if (!iso) return 'Not set';
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}

export function cadence(interval, count) {
  const n = count || 1;
  if (n === 1) return { day: 'daily', week: 'weekly', month: 'monthly', year: 'yearly' }[interval] || interval;
  return `every ${n} ${interval}s`;
}
