import { http } from './api';

export const getPlans = () => http.get('/plans');
export const getEntitlement = () => http.get('/payments/entitlement');
export const getOrders = () => http.get('/payments/orders');
export const createOrder = () => http.post('/payments/create-order', { plan_code: 'plus' });
export const captureOrder = (orderId) => http.post('/payments/capture-order', { order_id: orderId });