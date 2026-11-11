import { http } from './api';

export function createFileImport(file) {
  const form = new FormData();
  form.append('file', file);
  return http.upload('/imports', form);
}
export const createEmailImport = (text) => http.post('/imports/email', { text });
export const getImport = (id) => http.get(`/imports/${id}`);
export const getItems = (id) => http.get(`/imports/${id}/items`);
export const confirmImport = (id, decisions) => http.post(`/imports/${id}/confirm`, { decisions });
export const undoImport = (id) => http.post(`/imports/${id}/undo`, {});