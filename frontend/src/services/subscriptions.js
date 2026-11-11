import { http } from './api';

export function listSubscriptions(params) {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== '' && v !== null && v !== undefined && v !== false) qs.set(k, v);
  });
  return http.get(`/subscriptions?${qs}`);
}
export const createSubscription = (body) => http.post('/subscriptions', body);
export const updateSubscription = (id, body) => http.put(`/subscriptions/${id}`, body);
export const setStatus = (id, status) => http.patch(`/subscriptions/${id}/status`, { status });
export const archiveSubscription = (id) => http.del(`/subscriptions/${id}`);
export const listCategories = () => http.get('/categories');
