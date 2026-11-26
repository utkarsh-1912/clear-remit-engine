import React, { useEffect, useRef, useState } from 'react';
import { Badge, Button, Card, CardBody, CardHeader, EmptyState, Field, Input, Stat, Table } from '@utkristi/ui';
import { Upload, Zap } from 'lucide-react';
import { apiFetch, fmtInt } from './utils';

export default function BulkStreamer({ core, onRefresh }) {
  const [activeJob, setActiveJob] = useState(null);
  const [customCount, setCustomCount] = useState('25000');
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
      } catch (_) {}
    }, 250);
  }

  async function handleFileUpload(file) {
    if (!file) return;
    setError('');
    try {
      const res = await fetch(`/api/bulk/upload-stream?filename=${encodeURIComponent(file.name)}`, {
        method: 'POST',
        body: file,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Upload failed');
      startPolling(data.job_id);
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleStress(count) {
    setError('');
    try {
      const data = await apiFetch('/api/bulk/stress-test', {
        method: 'POST',
        body: JSON.stringify({ num_vouchers: Number(count) }),
      });
      startPolling(data.job_id);
    } catch (err) {
      setError(err.message);
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
          <div className="eyebrow">High-Throughput Ingestion</div>
          <h1>GB-Scale Constant-Memory Data Streamer</h1>
          <p>Stream multi-gigabyte ISO 20022 XML and Bank CSV files directly to SQLite WAL in O(1) RAM.</p>
        </div>
      </header>

      {error && <div className="error">{error}</div>}

      <div className="form-grid">
        <Card className="panel">
          <CardHeader className="panel-heading"><div><h2>Stream Multi-GB Statement File</h2></div></CardHeader>
          <CardBody className="stack" style={{ gap: 14 }}>
            <input
              ref={fileRef}
              type="file"
              accept=".xml,.csv,.txt"
              className="file"
              onChange={e => handleFileUpload(e.target.files?.[0])}
            />
            <div className="actions">
              <Button onClick={() => fileRef.current?.click()} iconLeft={<Upload size={15} />}>
                Select XML / CSV File to Stream
              </Button>
            </div>
            <div style={{ paddingTop: 12, borderTop: '1px solid var(--cr-line)' }} className="stack">
              <Field label="Synthetic Stress Benchmark (Voucher Count)">
                <div className="actions">
                  <Input type="number" min={1000} max={500000} value={customCount} onChange={e => setCustomCount(e.target.value)} style={{ width: 140 }} />
                  <Button variant="ghost" onClick={() => handleStress(customCount)} iconLeft={<Zap size={15} />}>
                    Run Streaming Benchmark
                  </Button>
                </div>
              </Field>
            </div>
          </CardBody>
        </Card>

        <Card className="panel">
          <CardHeader className="panel-heading">
            <div><h2>Live Stream Telemetry</h2></div>
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
        <CardHeader className="panel-heading"><div><h2>Streaming Job History</h2></div></CardHeader>
        {core.bulk_jobs?.length > 0 ? (
          <Table columns={jobCols} rows={core.bulk_jobs} getRowKey={r => r.job_id} />
        ) : (
          <CardBody><EmptyState title="No streaming ingestion jobs run yet" /></CardBody>
        )}
      </Card>
    </div>
  );
}
