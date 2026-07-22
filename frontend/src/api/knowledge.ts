import { requestJson } from '../api';
import type { KnowledgeChunk, KnowledgeDocument } from '../types';

export function fetchKnowledgeDocuments(): Promise<KnowledgeDocument[]> {
  return requestJson<KnowledgeDocument[]>('/knowledge/documents');
}

export function fetchKnowledgeChunks(documentId: number): Promise<KnowledgeChunk[]> {
  return requestJson<KnowledgeChunk[]>(`/knowledge/documents/${documentId}/chunks`);
}

export function uploadKnowledgeDocument(file: File): Promise<KnowledgeDocument> {
  const formData = new FormData();
  formData.append('file', file);
  return requestJson<KnowledgeDocument>('/knowledge/documents', {
    method: 'POST',
    body: formData,
  });
}

export async function deleteKnowledgeDocument(documentId: number): Promise<void> {
  await requestJson<unknown>(`/knowledge/documents/${documentId}`, {
    method: 'DELETE',
  });
}
