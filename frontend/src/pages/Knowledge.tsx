import { DragEvent, useEffect, useState } from 'react';
import { deleteKnowledgeDocument, fetchKnowledgeChunks, fetchKnowledgeDocuments, uploadKnowledgeDocument } from '../api/knowledge';
import {
  EmptyState,
  ErrorState,
  LoadingState,
  MetricCard,
  PageShell,
  ProductHero,
  SectionCard,
  StatusBadge,
} from '../components/IndustrialUI';
import { formatDateTime, formatDocumentName } from '../utils/reportFormatter';
import type { CurrentUser, KnowledgeChunk, KnowledgeDocument } from '../types';

export default function KnowledgePage({ currentUser }: { currentUser: CurrentUser | null }) {
  const canUpload = currentUser?.permissions.includes('knowledge:upload') ?? false;
  const canDelete = currentUser?.permissions.includes('knowledge:delete') ?? false;
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [selectedDocumentId, setSelectedDocumentId] = useState<number | null>(null);
  const [chunks, setChunks] = useState<KnowledgeChunk[]>([]);
  const [loading, setLoading] = useState(true);
  const [chunkLoading, setChunkLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void loadDocuments();
  }, []);

  const totalSegments = documents.reduce((total, document) => total + document.chunk_count, 0);
  const indexedCount = documents.filter((document) => document.status === 'indexed').length;
  const selectedDocument = documents.find((document) => document.id === selectedDocumentId) ?? null;
  const faultKnowledgeCount = documents.filter((document) => /e\d{3}/i.test(document.filename)).length;
  const coveredDevices = buildCoverage(documents);

  async function loadDocuments() {
    setLoading(true);
    setError(null);
    try {
      setDocuments(await fetchKnowledgeDocuments());
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : '知识库文档加载失败。');
    } finally {
      setLoading(false);
    }
  }

  async function openSegments(documentId: number) {
    setSelectedDocumentId(documentId);
    setChunkLoading(true);
    setError(null);
    try {
      setChunks(await fetchKnowledgeChunks(documentId));
    } catch (chunkError) {
      setChunks([]);
      setError(chunkError instanceof Error ? chunkError.message : '文档摘要加载失败。');
    } finally {
      setChunkLoading(false);
    }
  }

  async function upload(file: File) {
    if (!canUpload || uploading) return;
    setUploading(true);
    setError(null);
    try {
      const document = await uploadKnowledgeDocument(file);
      await loadDocuments();
      await openSegments(document.id);
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : '知识库文档上传失败。');
    } finally {
      setUploading(false);
    }
  }

  async function remove(documentId: number) {
    if (!canDelete) return;
    setError(null);
    try {
      await deleteKnowledgeDocument(documentId);
      if (selectedDocumentId === documentId) {
        setSelectedDocumentId(null);
        setChunks([]);
      }
      await loadDocuments();
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : '知识库文档删除失败。');
    }
  }

  function handleDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files[0];
    if (file) void upload(file);
  }

  return (
    <PageShell>
      <ProductHero
        eyebrow="Knowledge Platform"
        title="企业维修知识资产中心"
        description="沉淀设备维修手册、故障处理规范、历史案例和专家经验。知识完成索引后，会作为智能诊断报告的可追溯依据。"
        side={
          <div className="grid gap-3 text-sm">
            <div className="flex items-center justify-between"><span className="text-slate-500">当前权限</span><span className="font-semibold text-slate-950">{canUpload ? '可维护知识库' : '只读查看'}</span></div>
            <div className="flex items-center justify-between"><span className="text-slate-500">知识状态</span><StatusBadge label={documents.length && indexedCount === documents.length ? '全部可引用' : '存在待处理资料'} healthy={documents.length === indexedCount} /></div>
            <div className="text-xs leading-5 text-slate-500">上传区域已降权，核心关注知识资产覆盖范围、索引状态和可引用内容。</div>
          </div>
        }
      />

      {error ? <ErrorState message={error} /> : null}
      {loading ? <LoadingState title="正在加载知识库资产" steps={['维修资料', '故障知识', '历史案例']} /> : null}

      <div className="grid gap-4 md:grid-cols-4">
        <MetricCard label="故障知识数量" value={`${faultKnowledgeCount} 类`} description="按故障代码识别的维修资料" />
        <MetricCard label="知识片段数量" value={`${totalSegments} 段`} description="可被诊断引用的内容片段" />
        <MetricCard label="关联设备类型" value={coveredDevices.length ? `${coveredDevices.length} 类` : '待完善'} description={coveredDevices.join('、') || '暂无覆盖信息'} />
        <MetricCard label="可引用文档" value={`${indexedCount}/${documents.length || 0} 份`} description="已完成索引的知识资产" tone={documents.length === indexedCount ? 'normal' : 'warning'} />
      </div>

      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
        <SectionCard eyebrow="Documents" title="知识资产列表" right={<button type="button" onClick={() => void loadDocuments()} className="control-button h-9">刷新</button>}>
          <div className="mt-4 overflow-hidden rounded-2xl border border-slate-200">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <thead className="bg-slate-50 text-xs text-slate-500">
                <tr>
                  <th className="px-4 py-3 text-left">业务资料</th>
                  <th className="px-4 py-3 text-left">类型</th>
                  <th className="px-4 py-3 text-left">状态</th>
                  <th className="px-4 py-3 text-left">知识片段</th>
                  <th className="px-4 py-3 text-left">更新时间</th>
                  {canDelete ? <th className="px-4 py-3 text-right">操作</th> : null}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200 bg-white">
                {loading ? (
                  <tr><td colSpan={canDelete ? 6 : 5} className="px-4 py-8 text-center text-slate-500">正在加载知识库文档...</td></tr>
                ) : documents.length ? documents.map((document) => (
                  <tr key={document.id} className="transition hover:bg-slate-50">
                    <td className="px-4 py-3">
                      <button type="button" onClick={() => void openSegments(document.id)} className="text-left">
                        <div className="font-semibold text-slate-950">{formatDocumentName(document.filename)}</div>
                        <div className="mt-1 max-w-[360px] truncate text-xs text-slate-500">{document.filename}</div>
                      </button>
                    </td>
                    <td className="px-4 py-3 text-slate-600">{document.file_type.toUpperCase()}</td>
                    <td className="px-4 py-3"><StatusPill status={document.status} /></td>
                    <td className="px-4 py-3 font-mono text-slate-700">{document.chunk_count}</td>
                    <td className="px-4 py-3 text-slate-600">{formatDateTime(document.updated_at)}</td>
                    {canDelete ? (
                      <td className="px-4 py-3 text-right">
                        <button type="button" onClick={() => void remove(document.id)} className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600 transition hover:border-red-200 hover:bg-red-50 hover:text-red-700">删除</button>
                      </td>
                    ) : null}
                  </tr>
                )) : (
                  <tr><td colSpan={canDelete ? 6 : 5} className="px-4 py-8 text-center text-slate-500">暂无知识库文档。</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </SectionCard>

        <div className="grid gap-5">
          {canUpload ? (
            <SectionCard eyebrow="Upload" title="上传维修资料">
              <label
                onDragOver={(event) => {
                  event.preventDefault();
                  setDragging(true);
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={handleDrop}
                className={`mt-4 grid cursor-pointer place-items-center rounded-2xl border-2 border-dashed p-5 text-center transition ${
                  dragging ? 'border-sky-400 bg-sky-50' : 'border-slate-200 bg-slate-50 hover:border-sky-300 hover:bg-sky-50'
                }`}
              >
                <input
                  type="file"
                  accept=".pdf,.md,.markdown,.txt"
                  disabled={uploading}
                  className="hidden"
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    event.target.value = '';
                    if (file) void upload(file);
                  }}
                />
                <div className="text-sm font-semibold text-slate-950">{uploading ? '正在上传并建立索引...' : '拖拽或点击上传'}</div>
                <div className="mt-2 text-xs leading-5 text-slate-500">支持 PDF / Markdown / TXT。上传后自动解析、切片并进入企业知识检索库。</div>
              </label>
            </SectionCard>
          ) : null}

          <SectionCard eyebrow="Preview" title={selectedDocument ? formatDocumentName(selectedDocument.filename) : '知识摘要预览'}>
            <div className="mt-4 grid max-h-[520px] gap-3 overflow-auto pr-1">
              {chunkLoading ? (
                <EmptyState title="正在加载知识摘要" description="请稍候。" />
              ) : chunks.length ? (
                chunks.slice(0, 8).map((chunk) => (
                  <article key={chunk.id} className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-sky-700">知识摘要 {chunk.chunk_index + 1}</span>
                      <span className="text-xs text-slate-500">{chunk.vector_id ? '可被诊断引用' : '待入库'}</span>
                    </div>
                    <p className="mt-2 line-clamp-5 text-xs leading-5 text-slate-600">{chunk.content}</p>
                  </article>
                ))
              ) : (
                <EmptyState title={selectedDocument ? '该文档暂无知识摘要' : '请选择左侧文档'} description={selectedDocument ? '请检查文档处理状态。' : '选择文档后可查看可引用内容摘要。'} />
              )}
            </div>
          </SectionCard>
        </div>
      </div>
    </PageShell>
  );
}

function StatusPill({ status }: { status: string }) {
  return <StatusBadge label={statusLabel(status)} healthy={status === 'indexed'} />;
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    uploaded: '已上传',
    processing: '处理中',
    indexed: '已索引',
    failed: '失败',
  };
  return labels[status] ?? status;
}

function buildCoverage(documents: KnowledgeDocument[]): string[] {
  const coverage = new Set<string>();
  for (const document of documents) {
    const name = document.filename.toLowerCase();
    if (name.includes('e101') || name.includes('temperature')) coverage.add('温度传感器');
    if (name.includes('e201') || name.includes('vibration')) coverage.add('振动电机');
    if (name.includes('e203') || name.includes('motor')) coverage.add('电机驱动');
    if (name.includes('e404') || name.includes('communication') || name.includes('sensor')) coverage.add('通信设备');
  }
  return Array.from(coverage);
}
