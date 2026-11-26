import React, { useEffect, useRef, useState } from 'react';
import { Badge, Button, Card, CardBody, CardHeader, EmptyState, Stat, Table } from '@utkristi/ui';
import { Upload } from 'lucide-react';
import { apiFetch, fmtInt } from './utils';

export default function BulkStreamer({ core, onRefresh }) {
  const [activeJob, setActiveJob] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const pollRef = useRef(null);
  const fileRef = useRef(null);

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  function startPolling(jobId) {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const j = await apiFetch(`/api/bulk/jobs/${jobId}`);
        setActiveJob(j);
        if (j.status === 'COMPLETED' || j.status === 'FAILED') {
          clearInterval(pollRef.current);
          await onRefresh();
        }
      } catch (err) {
        clearInterval(pollRef.current);
        setActiveJob(null);
        setError(err.message);
      }
    }, 250);
  }

  async function handleFileUpload(file) {
    if (!file) return;
    setError('');
    setUploading(true);
    try {
      const res = await fetch(`/api/bulk/upload-stream?filename=${encodeURIComponent(file.name)}`, {
        method: 'POST',
        body: file,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Upload failed');
      setActiveJob({ ...data, progress_pct: 0 });
      startPolling(data.job_id);
    } catch (err) {
      setError(err.message);
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  }

  const jobCols = [
    { key: 'job_id', header: 'Job ID' },
    { key: 'job_type', header: 'Type', render: r => <Badge tone="info">{r.job_type}</Badge> },
    { key: 'filename', header: 'Source' },
    { key: 'status', header: 'Status', render: r => <Badge tone={r.status === 'COMPLETED' ? 'ok' : r.status === 'FAILED' ? 'bad' : 'warn'}>{r.status}</Badge> },
    { key: 'vouchers_ingested', header: 'Vouchers', align: 'right', render: r => fmtInt(r.vouchers_ingested) },
    { key: 'posting_lines_ingested', header: 'GL Lines', align: 'right', render: r => fmtInt(r.posting_lines_ingested) },
    { key: 'elapsed_sec', header: 'Elapsed', align: 'right', render: r => `${r.elapsed_sec}s` },
    { key: 'rows_per_sec', header: 'Lines/Sec', align: 'right', render: r => fmtInt(r.rows_per_sec) },
  ];

  return (
    <div className="stack">
      <header className="page-heading">
        <div>
          <h1>Bank imports</h1>
          <p>Upload large ISO 20022 XML or bank CSV files for direct receipt posting.</p>
        </div>
      </header>

      {error && <div className="error">{error}</div>}

      <div className="form-grid">
        <Card className="panel">
          <CardHeader className="panel-heading"><div><h2>Upload a bank statement</h2></div></CardHeader>
          <CardBody className="stack" style={{ gap: 14 }}>
            <p>Uploads post receipts directly to cash and receivables. Use Remittance &amp; tax first if you need to review allocations before posting.</p>
            <input
              ref={fileRef}
              type="file"
              accept=".xml,.csv"
              hidden
              onChange={e => handleFileUpload(e.target.files?.[0])}
            />
            <div className="actions">
              <Button disabled={uploading || activeJob?.status === 'RUNNING'} onClick={() => fileRef.current?.click()} iconLeft={<Upload size={15} />}>
                {uploading ? 'Uploading' : 'Select XML or CSV'}
              </Button>
            </div>
          </CardBody>
        </Card>

        <Card className="panel">
          <CardHeader className="panel-heading">
            <div><h2>Current import</h2></div>
            <Badge tone={activeJob?.status === 'COMPLETED' ? 'ok' : 'info'}>
              {activeJob ? `${activeJob.status} (${activeJob.progress_pct}%)` : 'IDLE'}
            </Badge>
          </CardHeader>
          <CardBody>
            <div className="detail-metrics">
              <Stat label="GL Lines / Sec" value={activeJob ? fmtInt(activeJob.rows_per_sec) : '0'} />
              <Stat label="Velocity" value={activeJob ? `${activeJob.mb_per_sec} MB/s` : '0 MB/s'} />
              <Stat label="Lines Committed" value={activeJob ? fmtInt(activeJob.posting_lines_ingested) : '0'} />
            </div>
          </CardBody>
        </Card>
      </div>

      <Card className="panel">
        <CardHeader className="panel-heading"><div><h2>Import history</h2></div></CardHeader>
        {core.bulk_jobs?.length > 0 ? (
          <Table columns={jobCols} rows={core.bulk_jobs} getRowKey={r => r.job_id} />
        ) : (
          <CardBody><EmptyState title="No bank statements imported yet" /></CardBody>
        )}
      </Card>
    </div>
  );
}
