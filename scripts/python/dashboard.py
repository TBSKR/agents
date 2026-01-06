#!/usr/bin/env python3
"""
Polymarket Trading Bot Dashboard

Simple, lightweight dashboard for the Gabagool strategy.
Optimized for MacBook Air M2.

Usage:
    python scripts/python/dashboard.py

Opens at: http://localhost:5050
"""

import sys
import json
import threading
import subprocess
from pathlib import Path
from flask import Flask, render_template_string, jsonify, request

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agents.application.trade_logger import TradeLogger
from agents.application.paper_portfolio import PaperPortfolio
from agents.application.gabagool_trader import GabagoolTrader
from agents.application.market_watcher import MarketWatcher

app = Flask(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.parent
VENV_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"
DATA_DIR = PROJECT_ROOT / "paper_trading_data"

# Global state
_opportunities = []
_watching = False

HTML = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Polymarket Bot</title>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: 'JetBrains Mono', monospace;
            background: #0a0a0a;
            color: #e0e0e0;
            min-height: 100vh;
            padding: 20px;
        }
        
        .container { max-width: 1000px; margin: 0 auto; }
        
        /* Header */
        header {
            text-align: center;
            padding: 30px 0;
            border-bottom: 1px solid #222;
            margin-bottom: 30px;
        }
        
        h1 {
            font-size: 24px;
            font-weight: 700;
            color: #00ff88;
            margin-bottom: 8px;
        }
        
        .subtitle { color: #666; font-size: 14px; }
        
        /* Big Action Button */
        .action-section {
            text-align: center;
            padding: 40px;
            background: #111;
            border: 1px solid #222;
            border-radius: 12px;
            margin-bottom: 30px;
        }
        
        .big-btn {
            display: inline-flex;
            align-items: center;
            gap: 12px;
            padding: 20px 50px;
            font-size: 18px;
            font-weight: 600;
            font-family: inherit;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.2s;
        }
        
        .big-btn.green {
            background: #00ff88;
            color: #000;
        }
        
        .big-btn.green:hover {
            background: #00cc6a;
            transform: scale(1.02);
        }
        
        .big-btn:disabled {
            opacity: 0.5;
            cursor: wait;
        }
        
        .quick-btns {
            display: flex;
            gap: 10px;
            justify-content: center;
            margin-top: 20px;
        }
        
        .quick-btn {
            padding: 10px 20px;
            background: #1a1a1a;
            border: 1px solid #333;
            color: #aaa;
            font-family: inherit;
            font-size: 13px;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.2s;
        }
        
        .quick-btn:hover {
            background: #222;
            color: #fff;
            border-color: #00ff88;
        }
        
        /* Stats */
        .stats {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 15px;
            margin-bottom: 30px;
        }
        
        .stat {
            background: #111;
            border: 1px solid #222;
            border-radius: 8px;
            padding: 20px;
            text-align: center;
        }
        
        .stat-value {
            font-size: 28px;
            font-weight: 700;
            color: #fff;
        }
        
        .stat-value.green { color: #00ff88; }
        .stat-value.red { color: #ff4444; }
        
        .stat-label {
            font-size: 11px;
            color: #666;
            text-transform: uppercase;
            margin-top: 8px;
        }
        
        /* Positions */
        .section {
            background: #111;
            border: 1px solid #222;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        
        .section-header {
            padding: 15px 20px;
            border-bottom: 1px solid #222;
            font-weight: 600;
            display: flex;
            justify-content: space-between;
        }
        
        .section-body {
            padding: 20px;
        }
        
        /* Position Cards */
        .position {
            background: #0a0a0a;
            border: 1px solid #222;
            border-radius: 6px;
            padding: 15px;
            margin-bottom: 10px;
        }
        
        .position:last-child { margin-bottom: 0; }
        
        .position-header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 10px;
        }
        
        .position-title {
            font-size: 13px;
            color: #aaa;
        }
        
        .position-status {
            font-size: 12px;
            padding: 3px 8px;
            border-radius: 4px;
        }
        
        .position-status.locked {
            background: rgba(0, 255, 136, 0.15);
            color: #00ff88;
        }
        
        .position-status.building {
            background: rgba(255, 200, 0, 0.15);
            color: #ffc800;
        }
        
        .position-details {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 10px;
            font-size: 12px;
        }
        
        .position-detail label {
            color: #666;
            display: block;
            margin-bottom: 3px;
        }
        
        .position-detail span {
            color: #fff;
            font-weight: 600;
        }
        
        /* Log */
        .log {
            background: #0a0a0a;
            border-radius: 6px;
            padding: 15px;
            max-height: 200px;
            overflow-y: auto;
            font-size: 12px;
        }
        
        .log-line {
            padding: 5px 0;
            border-bottom: 1px solid #1a1a1a;
        }
        
        .log-line:last-child { border-bottom: none; }
        
        .log-time { color: #444; margin-right: 10px; }
        .log-success { color: #00ff88; }
        .log-error { color: #ff4444; }
        
        /* Empty state */
        .empty {
            text-align: center;
            padding: 30px;
            color: #444;
        }
        
        /* Responsive */
        @media (max-width: 768px) {
            .stats { grid-template-columns: repeat(2, 1fr); }
            .position-details { grid-template-columns: repeat(2, 1fr); }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>POLYMARKET BOT</h1>
            <p class="subtitle">Gabagool Strategy • No AI • Pure Math</p>
        </header>
        
        <!-- Main Action -->
        <div class="action-section">
            <button class="big-btn green" id="main-btn" onclick="runGabagool()">
                ▶ START TRADING
            </button>
            <div class="quick-btns">
                <button class="quick-btn" onclick="runAction('scan')">Scan Markets</button>
                <button class="quick-btn" onclick="runAction('positions')">View Positions</button>
                <button class="quick-btn" onclick="runAction('watch')">Watch Mode</button>
            </div>
        </div>
        
        <!-- Stats -->
        <div class="stats">
            <div class="stat">
                <div class="stat-value" id="cash">$1,000</div>
                <div class="stat-label">Cash</div>
            </div>
            <div class="stat">
                <div class="stat-value" id="invested">$0</div>
                <div class="stat-label">Invested</div>
            </div>
            <div class="stat">
                <div class="stat-value green" id="profit">$0</div>
                <div class="stat-label">Guaranteed Profit</div>
            </div>
            <div class="stat">
                <div class="stat-value" id="locked">0/0</div>
                <div class="stat-label">Locked Positions</div>
            </div>
        </div>
        
        <!-- Positions -->
        <div class="section">
            <div class="section-header">
                <span>POSITIONS</span>
                <span id="pos-count">0</span>
            </div>
            <div class="section-body" id="positions">
                <div class="empty">No positions yet. Click START TRADING to begin.</div>
            </div>
        </div>
        
        <!-- Activity Log -->
        <div class="section">
            <div class="section-header">
                <span>ACTIVITY LOG</span>
            </div>
            <div class="section-body">
                <div class="log" id="log">
                    <div class="log-line">
                        <span class="log-time">--:--</span>
                        System ready. Click START TRADING.
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        function log(msg, type = '') {
            const logEl = document.getElementById('log');
            const time = new Date().toLocaleTimeString('en-US', { 
                hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' 
            });
            const line = document.createElement('div');
            line.className = 'log-line ' + (type === 'success' ? 'log-success' : type === 'error' ? 'log-error' : '');
            line.innerHTML = '<span class="log-time">' + time + '</span>' + msg;
            logEl.insertBefore(line, logEl.firstChild);
        }
        
        async function runGabagool() {
            const btn = document.getElementById('main-btn');
            btn.disabled = true;
            btn.textContent = '⏳ RUNNING...';
            log('Starting Gabagool strategy...');
            
            try {
                const res = await fetch('/api/run/gabagool', { method: 'POST' });
                const data = await res.json();
                
                if (data.success) {
                    log('Strategy completed', 'success');
                    if (data.output) {
                        data.output.split('\\n').slice(-10).forEach(line => {
                            if (line.trim() && !line.includes('===')) log(line.trim());
                        });
                    }
                } else {
                    log('Error: ' + (data.error || 'Unknown'), 'error');
                }
            } catch (e) {
                log('Network error', 'error');
            }
            
            btn.disabled = false;
            btn.textContent = '▶ START TRADING';
            loadData();
        }
        
        async function runAction(action) {
            log('Running ' + action + '...');
            
            try {
                const res = await fetch('/api/run/' + action, { method: 'POST' });
                const data = await res.json();
                
                if (data.success) {
                    log(action + ' completed', 'success');
                } else {
                    log(action + ' failed', 'error');
                }
            } catch (e) {
                log('Error: ' + e.message, 'error');
            }
            
            loadData();
        }
        
        async function loadData() {
            try {
                const res = await fetch('/api/data');
                const d = await res.json();
                
                // Update stats
                document.getElementById('cash').textContent = '$' + d.portfolio.cash_balance.toFixed(0);
                document.getElementById('invested').textContent = '$' + d.gabagool.total_invested.toFixed(0);
                
                const profitEl = document.getElementById('profit');
                profitEl.textContent = '$' + d.gabagool.total_guaranteed_profit.toFixed(2);
                profitEl.className = 'stat-value ' + (d.gabagool.total_guaranteed_profit > 0 ? 'green' : '');
                
                document.getElementById('locked').textContent = 
                    d.gabagool.locked_positions + '/' + d.gabagool.total_positions;
                
                // Update positions
                document.getElementById('pos-count').textContent = d.positions.length;
                renderPositions(d.positions);
                
            } catch (e) {
                console.error('Load error:', e);
            }
        }
        
        function renderPositions(positions) {
            const el = document.getElementById('positions');
            
            if (!positions.length) {
                el.innerHTML = '<div class="empty">No positions yet. Click START TRADING to begin.</div>';
                return;
            }
            
            let html = '';
            positions.forEach(p => {
                const status = p.is_profit_locked ? 'locked' : 'building';
                const statusText = p.is_profit_locked ? '✓ LOCKED' : '⏳ BUILDING';
                
                html += `
                <div class="position">
                    <div class="position-header">
                        <span class="position-title">${p.question.substring(0, 50)}...</span>
                        <span class="position-status ${status}">${statusText}</span>
                    </div>
                    <div class="position-details">
                        <div class="position-detail">
                            <label>YES</label>
                            <span>${p.qty_yes.toFixed(0)} @ $${p.avg_yes.toFixed(4)}</span>
                        </div>
                        <div class="position-detail">
                            <label>NO</label>
                            <span>${p.qty_no.toFixed(0)} @ $${p.avg_no.toFixed(4)}</span>
                        </div>
                        <div class="position-detail">
                            <label>Pair Cost</label>
                            <span>$${p.pair_cost.toFixed(4)}</span>
                        </div>
                        <div class="position-detail">
                            <label>Profit</label>
                            <span style="color: ${p.guaranteed_profit > 0 ? '#00ff88' : '#666'}">
                                $${p.guaranteed_profit.toFixed(2)}
                            </span>
                        </div>
                    </div>
                </div>`;
            });
            
            el.innerHTML = html;
        }
        
        // Initial load
        loadData();
        
        // Refresh every 15 seconds
        setInterval(loadData, 15000);
    </script>
</body>
</html>'''


def get_data():
    """Get all data for dashboard."""
    logger = TradeLogger()
    
    # Portfolio
    state_path = logger.data_dir / "portfolio_state.json"
    portfolio = PaperPortfolio.load_state(str(state_path)) if state_path.exists() else PaperPortfolio(1000.0)
    
    # Gabagool positions
    gabagool = GabagoolTrader(str(logger.data_dir))
    
    return {
        'portfolio': portfolio.get_portfolio_summary(),
        'gabagool': gabagool.get_summary(),
        'positions': gabagool.get_all_positions(),
    }


@app.route('/')
def index():
    return render_template_string(HTML)


@app.route('/api/data')
def api_data():
    return jsonify(get_data())


@app.route('/api/run/<cmd>', methods=['POST'])
def api_run(cmd):
    valid_cmds = ['gabagool', 'scan', 'positions', 'watch', 'status']
    if cmd not in valid_cmds:
        return jsonify({'success': False, 'error': 'Invalid command'})
    
    try:
        script = PROJECT_ROOT / "scripts" / "python" / "run_paper_trader.py"
        
        if cmd == 'gabagool':
            run_cmd = [str(VENV_PYTHON), str(script), 'auto', '--strategy', 'gabagool', '--count', '3']
        elif cmd == 'scan':
            run_cmd = [str(VENV_PYTHON), str(script), 'scan', '--min-edge', '0.1']
        elif cmd == 'positions':
            run_cmd = [str(VENV_PYTHON), str(script), 'positions']
        elif cmd == 'watch':
            run_cmd = [str(VENV_PYTHON), str(script), 'watch', '--duration', '30']
        else:
            run_cmd = [str(VENV_PYTHON), str(script), cmd]
        
        result = subprocess.run(
            run_cmd,
            capture_output=True, text=True, timeout=120, cwd=str(PROJECT_ROOT)
        )
        
        output = result.stdout + result.stderr
        lines = [l for l in output.split('\n') if l.strip() and 'Warning' not in l and 'pkg_resources' not in l]
        clean_output = '\n'.join(lines[-30:])
        
        return jsonify({
            'success': result.returncode == 0,
            'message': f'{cmd} completed',
            'output': clean_output
        })
        
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': 'Timeout'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


if __name__ == '__main__':
    import webbrowser
    
    print("\n" + "="*50)
    print("  POLYMARKET BOT")
    print("="*50)
    print("\n  Dashboard: http://localhost:5050")
    print("  Press Ctrl+C to stop\n")
    
    threading.Timer(1.5, lambda: webbrowser.open('http://localhost:5050')).start()
    app.run(host='0.0.0.0', port=5050, debug=False)
