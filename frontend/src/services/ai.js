import { http } from './api';

export const askAI = (question) => http.post('/ai/ask', { question });