/* Component 8: GB-Scale Constant-Memory Data Streamer & Throughput Telemetry */
import { store, apiJson, refreshCore, fmtInt, toast } from '../api.js';

let activePoll = null;

export function renderBulkStreamer(container) {
  if (!store.core) return;
  const jobs = store.core.bulk_jobs || [];

  container.innerHTML = `
    <div class="topbar">
      <div>
        <h2>⚡ GB-Scale Constant-Memory Data Streamer</h2>
        <div class="topbar-sub">O(1) RAM XML iterparse &amp; Chunked CSV Streaming • 5,000-Row Atomic SQLite WAL Batches • Zero HTTP Timeouts</div>
      </div>
    </div>

    <div class="grid-2">
      <div class="card">
        <div class="card-header"><span class="card-title">Stream Multi-GB File Directly to Core GL</span><span class="pill p-cyan">Zero-RAM HTTP Stream</span></div>
        <div class="dropzone" id="gbDropzone">
          <div style="font-size:28px; margin-bottom:8px;">📂</div>
          <div style="font-weight:700; font-size:14px;">Drop Multi-GB ISO 20022 XML or Bank CSV Here</div>
          <div style="font-size:12px; color:var(--muted); margin-top:4px;">Streams raw binary chunks straight to disk and parses with O(1) memory (~20 MB RAM).</div>
          <input type="file" id="gbFileInput" class="hidden" accept=".xml,.csv,.txt" />
        </div>

        <div style="margin-top:18px;">
          <div class="card-title" style="margin-bottom:8px;">Or Launch High-Throughput Stress Benchmark</div>
          <div class="actions">
            <button class="primary" data-stress="25000">⚡ 25,000 Vouchers (50k Lines)</button>
            <button class="emerald" data-stress="100000">🚀 100,000 Vouchers (200k Lines)</button>
            <button data-stress="250000">🔥 250,000 Vouchers (500k Lines)</button>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-header"><span class="card-title">Live Streaming Telemetry</span><span id="activeJobStatus" class="pill p-cyan">IDLE</span></div>
        <div id="liveJobDetails" style="font-size:12.5px; color:var(--muted);">Launch a file stream or stress benchmark to inspect real-time Rows/sec and MB/sec throughput.</div>
        <div class="progress-outer"><div class="progress-inner" id="jobProgressBar"></div></div>
        <div class="kpi-grid" style="margin-top:12px; margin-bottom:0;">
          <div class="kpi-card" style="padding:12px;">
            <div class="kpi-label">Throughput</div>
            <div class="kpi-val" id="telRowsSec" style="font-size:20px; color:var(--emerald)">0 /s</div>
            <div class="kpi-sub">Posting Lines / Sec</div>
          </div>
          <div class="kpi-card" style="padding:12px;">
            <div class="kpi-label">Data Velocity</div>
            <div class="kpi-val" id="telMbSec" style="font-size:20px; color:var(--cyan)">0 MB/s</div>
            <div class="kpi-sub">Constant O(1) RAM</div>
          </div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-header"><span class="card-title">Streaming Ingestion Job History</span></div>
      <table>
        <thead><tr><th>Job ID</th><th>Type</th><th>File / Stream</th><th>Status</th><th class="num">Vouchers</th><th class="num">GL Lines</th><th class="num">Elapsed</th><th class="num">Rows/Sec</th></tr></thead>
        <tbody>
          ${jobs.length ? jobs.map(j => `
            <tr>
              <td class="mono" style="color:var(--cyan)">${j.job_id}</td>
              <td><span class="pill p-violet">${j.job_type}</span></td>
              <td class="mono" style="font-size:11.5px;">${j.filename}</td>
              <td><span class="pill ${j.status === 'COMPLETED' ? 'p-green' : (j.status === 'FAILED' ? 'p-rose' : 'p-amber')}">${j.status}</span></td>
              <td class="num">${fmtInt(j.vouchers_ingested)}</td>
              <td class="num">${fmtInt(j.posting_lines_ingested)}</td>
              <td class="num">${j.elapsed_sec}s</td>
              <td class="num" style="color:var(--emerald); font-weight:700;">${fmtInt(j.rows_per_sec)}/s</td>
            </tr>
          `).join('') : '<tr><td colspan="8" style="color:var(--muted)">No streaming jobs run yet.</td></tr>'}
        </tbody>
      </table>
    </div>
  `;

  function pollJob(jobId) {
    if (activePoll) clearInterval(activePoll);
    activePoll = setInterval(async () => {
      try {
        const j = await apiJson('/api/bulk/jobs/' + jobId);
        container.querySelector('#activeJobStatus').textContent = j.status;
        container.querySelector('#jobProgressBar').style.width = j.progress_pct + '%';
        container.querySelector('#telRowsSec').textContent = fmtInt(j.rows_per_sec) + ' /s';
        container.querySelector('#telMbSec').textContent = j.mb_per_sec + ' MB/s';
        container.querySelector('#liveJobDetails').innerHTML =
          `<b>${j.job_id}</b> (${j.filename}) • <b>${fmtInt(j.vouchers_ingested)}</b> Vouchers / <b>${fmtInt(j.posting_lines_ingested)}</b> GL Lines in <b>${j.elapsed_sec}s</b> (${j.progress_pct}%)`;

        if (j.status === 'COMPLETED' || j.status === 'FAILED') {
          clearInterval(activePoll);
          toast(j.status === 'COMPLETED' ? `Streamed ${fmtInt(j.posting_lines_ingested)} GL lines at ${fmtInt(j.rows_per_sec)} rows/sec!` : 'Job Failed: ' + j.error_message);
          await refreshCore();
        }
      } catch (_) {}
    }, 220);
  }

  async function uploadFile(file) {
    if (!file) return;
    container.querySelector('#activeJobStatus').textContent = 'STREAMING...';
    container.querySelector('#liveJobDetails').textContent = `Streaming ${file.name} (${(file.size / (1024 * 1024)).toFixed(2)} MB)...`;
    const res = await fetch('/api/bulk/upload-stream?filename=' + encodeURIComponent(file.name), { method: 'POST', body: file });
    const d = await res.json();
    if (!res.ok) { alert(d.detail || 'Upload failed'); return; }
    pollJob(d.job_id);
  }

  const dz = container.querySelector('#gbDropzone');
  const fi = container.querySelector('#gbFileInput');
  dz.addEventListener('click', () => fi.click());
  fi.addEventListener('change', () => uploadFile(fi.files[0]));
  dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('dragover'); });
  dz.addEventListener('dragleave', () => dz.classList.remove('dragover'));
  dz.addEventListener('drop', e => { e.preventDefault(); dz.classList.remove('dragover'); uploadFile(e.dataTransfer.files[0]); });

  container.querySelectorAll('[data-stress]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const n = Number(btn.getAttribute('data-stress'));
      const d = await apiJson('/api/bulk/stress-test', { method: 'POST', body: JSON.stringify({ num_vouchers: n }) });
      pollJob(d.job_id);
    });
  });
}
