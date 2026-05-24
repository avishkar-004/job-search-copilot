"""
Real-time Flask + Socket.IO dashboard for monitoring job applications.
Runs on localhost:7000 by default.

Endpoints:
  GET  /                       → HTML dashboard
  GET  /api/stats              → summary stats JSON
  GET  /api/applications       → recent applications JSON
  POST /api/log_application    → bot pushes a new application; broadcast via WS
  POST /api/status             → bot pushes its current status; broadcast via WS
  POST /api/stop               → request a graceful stop
  GET  /api/stop_requested     → bot polls this to know if it should stop
  GET  /health                 → liveness
"""

import json
import os
import sys
import threading
from pathlib import Path

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask, jsonify, render_template_string, request

# Optional Socket.IO. We degrade gracefully if not installed.
try:
    from flask_socketio import SocketIO
    _HAS_SOCKETIO = True
except ImportError:  # pragma: no cover
    SocketIO = None
    _HAS_SOCKETIO = False

from src.output.tracker import get_stats, get_recent, log_application as _persist_app

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("DASHBOARD_SECRET", "job-apply-bot-secret")

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading") if _HAS_SOCKETIO else None

# Shared in-memory state — the bot can read/write through HTTP.
_STATE_LOCK = threading.Lock()
_STATE = {
    "current": "",         # human-readable: "Applying to X at Y"
    "stop_requested": False,
    "last_event_ts": 0,
}


def _emit(event: str, payload):
    """Helper: emit through Socket.IO if available, otherwise no-op."""
    if socketio is not None:
        try:
            socketio.emit(event, payload)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# HTML template — dark theme with Chart.js + live Socket.IO updates
# ---------------------------------------------------------------------------

_DASHBOARD_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Job Apply Bot — Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.2/dist/chart.umd.min.js"></script>
  <script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
  <style>
    :root {
      --bg: #0f1117;
      --surface: #1a1d27;
      --border: #2a2d3e;
      --text: #e2e8f0;
      --muted: #8892a4;
      --accent: #6366f1;
      --green: #22c55e;
      --yellow: #eab308;
      --red: #ef4444;
      --blue: #3b82f6;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', system-ui, sans-serif; min-height: 100vh; }

    header {
      padding: 1.5rem 2rem;
      border-bottom: 1px solid var(--border);
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    header h1 { font-size: 1.4rem; font-weight: 700; color: var(--accent); letter-spacing: -0.02em; }
    header .status { font-size: 0.8rem; color: var(--muted); display: flex; align-items: center; gap: 0.5rem; }
    .live-dot { display: inline-block; width: 8px; height: 8px; background: var(--green);
      border-radius: 50%; margin-right: 6px; animation: pulse 2s infinite; }
    .live-dot.off { background: var(--muted); animation: none; }
    @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
    .stop-btn { background: var(--red); color: white; border: none; padding: 0.4rem 0.9rem;
      border-radius: 6px; cursor: pointer; font-size: 0.8rem; font-weight: 600; }
    .stop-btn:hover { opacity: 0.9; }
    .stop-btn:disabled { opacity: 0.4; cursor: not-allowed; }

    .container { max-width: 1200px; margin: 0 auto; padding: 2rem; }

    .now-bar { background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
      padding: 1rem 1.25rem; margin-bottom: 1.5rem; display: flex; align-items: center; gap: 0.7rem; }
    .now-bar .label { font-size: 0.75rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; }
    .now-bar .what { color: var(--text); font-size: 0.95rem; }

    .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; margin-bottom: 2rem; }
    .stat-card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 1.25rem;
      transition: transform 0.2s; }
    .stat-card.bump { animation: bump 0.4s; }
    @keyframes bump { 0%{transform:scale(1)} 50%{transform:scale(1.04)} 100%{transform:scale(1)} }
    .stat-card .label { font-size: 0.75rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 0.5rem; }
    .stat-card .value { font-size: 2rem; font-weight: 700; }
    .stat-card.green .value { color: var(--green); }
    .stat-card.yellow .value { color: var(--yellow); }
    .stat-card.blue .value { color: var(--blue); }
    .stat-card.accent .value { color: var(--accent); }

    .charts-row { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-bottom: 2rem; }
    @media (max-width: 700px) { .charts-row { grid-template-columns: 1fr; } }
    .chart-card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 1.5rem; }
    .chart-card h2 { font-size: 0.95rem; color: var(--muted); margin-bottom: 1rem; font-weight: 600; }
    .chart-wrapper { position: relative; height: 200px; }

    .table-card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 1.5rem; }
    .table-card h2 { font-size: 0.95rem; color: var(--muted); margin-bottom: 1rem; font-weight: 600; }
    table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
    thead th { text-align: left; color: var(--muted); font-size: 0.75rem; text-transform: uppercase;
      letter-spacing: 0.06em; padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--border); }
    tbody tr:hover { background: rgba(255,255,255,0.03); }
    tbody tr.fresh { animation: slideIn 0.5s ease; background: rgba(99,102,241,0.06); }
    @keyframes slideIn {
      from { opacity: 0; transform: translateX(-12px); background: rgba(99,102,241,0.18); }
      to   { opacity: 1; transform: translateX(0);    background: rgba(99,102,241,0.06); }
    }
    tbody td { padding: 0.6rem 0.75rem; border-bottom: 1px solid var(--border); color: var(--text); }
    tbody tr:last-child td { border-bottom: none; }

    .badge { display: inline-block; padding: 0.2rem 0.6rem; border-radius: 9999px; font-size: 0.75rem; font-weight: 600; }
    .badge-applied { background: rgba(34,197,94,0.15); color: var(--green); }
    .badge-failed, .badge-error { background: rgba(239,68,68,0.15); color: var(--red); }
    .badge-skipped, .badge-skipped_score { background: rgba(234,179,8,0.15); color: var(--yellow); }
    .badge-default { background: rgba(100,100,120,0.2); color: var(--muted); }

    .score-bar { display: inline-flex; align-items: center; gap: 0.4rem; }
    .score-pip { width: 6px; height: 6px; border-radius: 50%; background: var(--muted); }
    .score-pip.high { background: var(--green); }
    .score-pip.mid { background: var(--yellow); }
    .score-pip.low { background: var(--red); }

    footer { text-align: center; color: var(--muted); font-size: 0.75rem; padding: 2rem; }
  </style>
</head>
<body>
  <header>
    <h1>Job Apply Bot</h1>
    <div class="status">
      <span><span id="live-dot" class="live-dot off"></span><span id="conn-text">Connecting…</span></span>
      <button id="stop-btn" class="stop-btn" onclick="requestStop()">Stop Bot</button>
    </div>
  </header>

  <div class="container">
    <div class="now-bar">
      <span class="label">Now</span>
      <span class="what" id="now-what">Idle</span>
    </div>

    <div class="stats-grid" id="stats-grid">
      <div class="stat-card accent" id="card-total">
        <div class="label">Total Applied</div>
        <div class="value" id="stat-total">—</div>
      </div>
      <div class="stat-card green" id="card-today">
        <div class="label">Applied Today</div>
        <div class="value" id="stat-today">—</div>
      </div>
      <div class="stat-card blue">
        <div class="label">Success Rate</div>
        <div class="value" id="stat-rate">—</div>
      </div>
      <div class="stat-card yellow">
        <div class="label">Platforms Active</div>
        <div class="value" id="stat-platforms">—</div>
      </div>
    </div>

    <div class="charts-row">
      <div class="chart-card">
        <h2>By Platform</h2>
        <div class="chart-wrapper"><canvas id="platformChart"></canvas></div>
      </div>
      <div class="chart-card">
        <h2>By Status</h2>
        <div class="chart-wrapper"><canvas id="statusChart"></canvas></div>
      </div>
    </div>

    <div class="table-card">
      <h2>Recent Applications</h2>
      <table>
        <thead>
          <tr>
            <th>Date</th><th>Platform</th><th>Company</th><th>Title</th><th>Score</th><th>Status</th>
          </tr>
        </thead>
        <tbody id="recent-tbody">
          <tr><td colspan="6" style="color:var(--muted);text-align:center;padding:2rem">Loading…</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <footer>Job Apply Bot — All data is local to your machine</footer>

  <script>
    let platformChart = null;
    let statusChart = null;

    const PLATFORM_COLORS = ['#6366f1','#3b82f6','#22c55e','#eab308','#f97316','#ec4899','#14b8a6'];
    const STATUS_COLORS = { applied: '#22c55e', failed: '#ef4444', error: '#ef4444',
                             skipped_score: '#eab308', skipped: '#eab308' };

    function badgeClass(status) {
      const s = (status || '').toLowerCase();
      if (s === 'applied') return 'badge-applied';
      if (s === 'failed' || s === 'error') return 'badge-failed';
      if (s.startsWith('skip')) return 'badge-skipped';
      return 'badge-default';
    }

    function scorePip(score) {
      const n = parseInt(score);
      if (isNaN(n)) return '<span class="score-bar">?</span>';
      const cls = n >= 75 ? 'high' : n >= 65 ? 'mid' : 'low';
      return `<span class="score-bar"><span class="score-pip ${cls}"></span>${n}</span>`;
    }

    function rowHtml(row, fresh) {
      const cls = fresh ? 'fresh' : '';
      return `<tr class="${cls}">
        <td>${row.date || ''}</td>
        <td>${row.platform || ''}</td>
        <td>${(row.company || '').substring(0, 22)}</td>
        <td>${(row.job_title || '').substring(0, 35)}</td>
        <td>${scorePip(row.fit_score)}</td>
        <td><span class="badge ${badgeClass(row.status)}">${row.status || ''}</span></td>
      </tr>`;
    }

    async function loadData() {
      try {
        const [statsRes, appsRes] = await Promise.all([
          fetch('/api/stats'), fetch('/api/applications')
        ]);
        const stats = await statsRes.json();
        const apps = await appsRes.json();
        renderStats(stats);

        const tbody = document.getElementById('recent-tbody');
        if (!apps.length) {
          tbody.innerHTML = '<tr><td colspan="6" style="color:var(--muted);text-align:center;padding:2rem">No applications yet. Run python main.py to start.</td></tr>';
          return;
        }
        tbody.innerHTML = apps.slice(0, 20).map(r => rowHtml(r, false)).join('');
      } catch (err) { console.error('Dashboard load error:', err); }
    }

    function renderStats(stats) {
      document.getElementById('stat-total').textContent = stats.total;
      document.getElementById('stat-today').textContent = stats.today;
      document.getElementById('stat-rate').textContent = (stats.success_rate * 100).toFixed(1) + '%';
      document.getElementById('stat-platforms').textContent = Object.keys(stats.by_platform || {}).length;

      const pLabels = Object.keys(stats.by_platform || {});
      const pData = Object.values(stats.by_platform || {});
      if (!platformChart) {
        platformChart = new Chart(document.getElementById('platformChart'), {
          type: 'doughnut',
          data: { labels: pLabels, datasets: [{ data: pData, backgroundColor: PLATFORM_COLORS, borderWidth: 0 }] },
          options: { plugins: { legend: { position: 'bottom', labels: { color: '#8892a4', boxWidth: 12 } } }, cutout: '62%' }
        });
      } else {
        platformChart.data.labels = pLabels;
        platformChart.data.datasets[0].data = pData;
        platformChart.update();
      }
      const sLabels = Object.keys(stats.by_status || {});
      const sData = Object.values(stats.by_status || {});
      const sColors = sLabels.map(l => STATUS_COLORS[l] || '#6366f1');
      if (!statusChart) {
        statusChart = new Chart(document.getElementById('statusChart'), {
          type: 'doughnut',
          data: { labels: sLabels, datasets: [{ data: sData, backgroundColor: sColors, borderWidth: 0 }] },
          options: { plugins: { legend: { position: 'bottom', labels: { color: '#8892a4', boxWidth: 12 } } }, cutout: '62%' }
        });
      } else {
        statusChart.data.labels = sLabels;
        statusChart.data.datasets[0].data = sData;
        statusChart.data.datasets[0].backgroundColor = sColors;
        statusChart.update();
      }
    }

    function bump(id) {
      const el = document.getElementById(id);
      if (!el) return;
      el.classList.remove('bump'); void el.offsetWidth; el.classList.add('bump');
    }

    async function requestStop() {
      const btn = document.getElementById('stop-btn');
      btn.disabled = true;
      btn.textContent = 'Stopping…';
      try { await fetch('/api/stop', { method: 'POST' }); } catch {}
      setTimeout(() => { btn.disabled = false; btn.textContent = 'Stop Bot'; }, 5000);
    }

    // Socket.IO live updates
    let socket = null;
    try {
      socket = io();
      socket.on('connect', () => {
        document.getElementById('live-dot').classList.remove('off');
        document.getElementById('conn-text').textContent = 'Live';
      });
      socket.on('disconnect', () => {
        document.getElementById('live-dot').classList.add('off');
        document.getElementById('conn-text').textContent = 'Disconnected — auto-refresh fallback';
      });
      socket.on('new_application', (row) => {
        // Prepend row with animation
        const tbody = document.getElementById('recent-tbody');
        const fresh = document.createElement('tbody');
        fresh.innerHTML = rowHtml(row, true);
        tbody.insertBefore(fresh.firstElementChild, tbody.firstChild);
        // Bump counters and reload stats
        bump('card-total');
        bump('card-today');
        loadData();
      });
      socket.on('status', (s) => {
        document.getElementById('now-what').textContent = s.current || 'Idle';
      });
    } catch (e) { console.warn('Socket.IO unavailable, falling back to polling.'); }

    loadData();
    // Poll regardless — works whether or not the websocket is alive.
    setInterval(loadData, 30000);
  </script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template_string(_DASHBOARD_HTML)


@app.route("/api/stats")
def api_stats():
    try:
        return jsonify(get_stats())
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/applications")
def api_applications():
    try:
        return jsonify(get_recent(100))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/log_application", methods=["POST"])
def api_log_application():
    """Bot pushes a new application here; we persist + broadcast."""
    try:
        data = request.get_json(force=True, silent=True) or {}
        _persist_app(data)
        # Reload row from CSV-style dict for dashboard consumption
        row = {
            "date": data.get("date", ""),
            "platform": data.get("platform", ""),
            "company": data.get("company", ""),
            "job_title": data.get("job_title", ""),
            "fit_score": data.get("fit_score", ""),
            "status": data.get("status", "applied"),
        }
        _emit("new_application", row)
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/status", methods=["POST"])
def api_status():
    """Bot pushes its current status here ("Applying to X at Y…")."""
    try:
        data = request.get_json(force=True, silent=True) or {}
        with _STATE_LOCK:
            _STATE["current"] = str(data.get("current", ""))[:240]
        _emit("status", {"current": _STATE["current"]})
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/stop", methods=["POST"])
def api_stop():
    """Dashboard requests bot stop. Bot polls /api/stop_requested."""
    with _STATE_LOCK:
        _STATE["stop_requested"] = True
    _emit("status", {"current": "Stop requested — bot will stop after current job."})
    return jsonify({"ok": True})


@app.route("/api/stop_requested", methods=["GET"])
def api_stop_requested():
    with _STATE_LOCK:
        return jsonify({"stop_requested": _STATE["stop_requested"]})


@app.route("/api/reset_stop", methods=["POST"])
def api_reset_stop():
    with _STATE_LOCK:
        _STATE["stop_requested"] = False
    return jsonify({"ok": True})


@app.route("/health")
def health():
    return jsonify({"status": "ok", "websocket": _HAS_SOCKETIO})


# ---------------------------------------------------------------------------
# Startup helper
# ---------------------------------------------------------------------------

def start_dashboard(host: str = "127.0.0.1", port: int = 7000, debug: bool = False):
    print(f"\n  Dashboard starting at http://{host}:{port}")
    print(f"  WebSocket: {'enabled' if _HAS_SOCKETIO else 'disabled (install flask-socketio)'}")
    print("  Press Ctrl+C to stop.\n")
    if socketio is not None:
        socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)
    else:
        app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    start_dashboard()
