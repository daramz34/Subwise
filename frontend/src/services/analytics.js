import { http } from './api';

export const getOverview = (days = 30) => http.get(`/analytics/overview?days=${days}`);
export const getPriceChanges = () => http.get('/analytics/price-changes');