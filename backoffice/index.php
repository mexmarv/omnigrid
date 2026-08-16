<?php
require_once __DIR__ . '/lib.php';
$pdo = omnigrid_db();
$s = dashboard_snapshot($pdo);

function e(string $s): string { return htmlspecialchars($s, ENT_QUOTES); }

function friendly_task_type(string $taskType): string {
    if (str_starts_with($taskType, 'llm_infer:')) {
        return 'Text generation (' . substr($taskType, strlen('llm_infer:')) . ')';
    }
    if (str_starts_with($taskType, 'vlm_infer:')) {
        return 'Vision-language (' . substr($taskType, strlen('vlm_infer:')) . ')';
    }
    return match ($taskType) {
        'tensor_op' => 'Tensor operation',
        'onnx_infer' => 'ONNX inference',
        default => $taskType,
    };
}
?>
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Omnigrid -- community compute for AI agents</title>
<style>
  :root {
    --bg: #0a0d13; --panel: #121722; --panel-2: #171d2b; --border: #232b3d;
    --text: #e7ecf5; --muted: #9a94b3; --accent: #c084fc; --accent-2: #e879f9;
    --gold: #f5c453; --silver: #c9d2e0; --bronze: #d18b5c;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background-image: radial-gradient(circle at 12% -10%, rgba(232,121,249,0.14), transparent 42%),
                       radial-gradient(circle at 90% 10%, rgba(192,132,252,0.11), transparent 40%);
    background-attachment: fixed;
  }
  a { color: inherit; }

  nav {
    display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap;
    gap: 10px 16px; padding: 16px 28px; border-bottom: 1px solid var(--border);
    position: sticky; top: 0; background: rgba(10,13,19,0.85); backdrop-filter: blur(10px);
    z-index: 10;
  }
  nav .brand { display: flex; align-items: center; gap: 10px; text-decoration: none; }
  nav .brand span { font-weight: 700; font-size: 15px; letter-spacing: -0.01em; color: #ffffff; }
  nav .links { display: flex; align-items: center; gap: 18px; font-size: 13.5px; flex-wrap: wrap; }
  nav .links a { color: var(--muted); text-decoration: none; white-space: nowrap; }
  nav .links a:hover { color: var(--text); }
  nav .links a.cta {
    color: #06110d; background: linear-gradient(135deg, var(--accent), var(--accent-2));
    padding: 7px 14px; border-radius: 8px; font-weight: 600;
  }
  @media (max-width: 560px) {
    nav .links a:not(.cta) { display: none; }
    nav .links { gap: 10px; }
  }

  .wrap { max-width: 920px; margin: 0 auto; padding: 48px 24px 80px; }

  .hero { margin-bottom: 40px; display: flex; align-items: center; gap: 28px; }
  .hero img.logo { width: 110px; height: auto; flex-shrink: 0; }
  @media (max-width: 560px) { .hero { flex-direction: column; align-items: flex-start; gap: 16px; } .hero img.logo { width: 80px; height: auto; } }
  .live {
    display: inline-flex; align-items: center; gap: 7px; font-size: 12.5px; color: var(--accent);
    background: rgba(192,132,252,0.08); border: 1px solid rgba(192,132,252,0.25);
    padding: 5px 12px; border-radius: 999px; margin-bottom: 16px;
  }
  .live .dot {
    width: 7px; height: 7px; border-radius: 50%; background: var(--accent);
    animation: pulse 2s ease-in-out infinite;
  }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.35; } }
  h1 { font-size: 30px; margin: 0 0 8px; letter-spacing: -0.02em; }
  .tagline { color: var(--muted); margin: 0; font-size: 15.5px; max-width: 60ch; line-height: 1.55; }

  .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 36px; }
  .card {
    background: var(--panel); border: 1px solid var(--border); border-radius: 14px;
    padding: 20px 22px; transition: border-color .15s, transform .15s;
  }
  .card:hover { border-color: #2c3752; }
  .stat-card { display: flex; flex-direction: column; gap: 10px; }
  .stat-card svg { width: 18px; height: 18px; color: var(--muted); }
  .stat-card .value {
    font-size: 30px; font-weight: 650; font-variant-numeric: tabular-nums;
    background: linear-gradient(135deg, var(--accent), var(--accent-2));
    -webkit-background-clip: text; background-clip: text; color: transparent;
  }
  .stat-card .label { color: var(--muted); font-size: 13px; }
  .stat-card .caption { color: var(--muted); font-size: 11.5px; opacity: 0.75; line-height: 1.4; margin-top: -4px; }

  h2 {
    font-size: 13px; color: var(--muted); font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.08em; margin: 0 0 14px;
  }
  .section { margin-bottom: 36px; }
  .subnote { color: var(--muted); font-size: 12.5px; margin: -8px 0 14px; }

  .tags { display: flex; flex-wrap: wrap; gap: 8px; }
  .tag {
    display: inline-block; padding: 6px 12px; border-radius: 999px; font-size: 13px;
    font-family: ui-monospace, SFMono-Regular, monospace;
    background: var(--panel-2); border: 1px solid var(--border); color: var(--accent);
  }

  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  @media (max-width: 860px) { .stats { grid-template-columns: repeat(2, 1fr); } }
  @media (max-width: 720px) { .grid-2 { grid-template-columns: 1fr; } .stats { grid-template-columns: 1fr; } }

  .rank-row {
    display: flex; align-items: center; gap: 12px; padding: 11px 16px;
    border-bottom: 1px solid var(--border); font-size: 14px;
  }
  .rank-row:last-child { border-bottom: none; }
  .rank-badge {
    width: 24px; height: 24px; border-radius: 50%; display: flex; align-items: center;
    justify-content: center; font-size: 11.5px; font-weight: 700; flex-shrink: 0;
    background: var(--panel-2); color: var(--muted);
  }
  .rank-badge.gold { background: linear-gradient(135deg, var(--gold), #c9922b); color: #2a1c00; }
  .rank-badge.silver { background: linear-gradient(135deg, var(--silver), #8b97ab); color: #10131a; }
  .rank-badge.bronze { background: linear-gradient(135deg, var(--bronze), #9c5a30); color: #200f00; }
  .rank-row .name { flex: 1; }
  .rank-row .credits { color: var(--muted); font-variant-numeric: tabular-nums; font-size: 13px; }

  .activity-row { padding: 11px 16px; border-bottom: 1px solid var(--border); font-size: 13.5px; }
  .activity-row:last-child { border-bottom: none; }
  .activity-row .when { color: var(--muted); font-size: 12px; }

  .empty { color: var(--muted); padding: 20px 16px; font-size: 14px; }
  .cta-panel {
    padding: 26px; border-radius: 14px; background: var(--panel-2); border: 1px solid var(--border);
  }
  .cta-panel p { margin: 0 0 14px; color: var(--muted); font-size: 14.5px; line-height: 1.55; }
  .cta-panel a.btn {
    display: inline-block; padding: 10px 18px; border-radius: 10px; font-weight: 600;
    text-decoration: none; background: linear-gradient(135deg, var(--accent), var(--accent-2));
    color: #06110d; font-size: 14px;
  }

  footer {
    margin-top: 48px; padding-top: 24px; border-top: 1px solid var(--border);
    color: var(--muted); font-size: 13px; display: flex; justify-content: space-between;
    flex-wrap: wrap; gap: 10px;
  }
  footer a { color: var(--accent-2); text-decoration: none; }
</style>
</head>
<body>

<nav>
  <a class="brand" href="index.php"><span>Omnigrid</span></a>
  <div class="links">
    <a href="register.php">Get an API key</a>
    <a href="reset.php">Reset access</a>
    <a href="https://github.com/mexmarv/omnigrid">GitHub</a>
    <a class="cta" href="register.php">Share compute &rarr;</a>
  </div>
</nav>

<div class="wrap">
  <div class="hero">
    <img class="logo" src="assets/logo.png" alt="Omnigrid">
    <div>
      <div class="live"><span class="dot"></span> live network</div>
      <h1>Community compute for AI agents</h1>
      <p class="tagline">Spare CPU/RAM/GPU and open-model LLM inference, shared not sold.
         Every number on this page is real and updates automatically -- nothing here is a mockup.</p>
    </div>
  </div>

  <div class="stats">
    <div class="card stat-card">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/></svg>
      <div class="value" id="stat-online"><?= $s['providers_online'] ?></div>
      <div class="label">providers online</div>
    </div>
    <div class="card stat-card">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/></svg>
      <div class="value" id="stat-hours"><?= $s['compute_hours_donated'] ?></div>
      <div class="label">compute-hours donated</div>
    </div>
    <div class="card stat-card">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M20 6L9 17l-5-5"/></svg>
      <div class="value" id="stat-jobs"><?= $s['jobs_done'] ?> / <?= $s['jobs_total'] ?></div>
      <div class="label">jobs completed</div>
    </div>
    <div class="card stat-card" title="Received as a file upload or a base64 field, decoded/re-encoded in that one request's own PHP memory, queued, and released when the request ends -- nothing is written to disk beyond the job's own record.">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="3" y="4" width="18" height="14" rx="2"/><circle cx="8.5" cy="9.5" r="1.5"/><path d="M21 15l-5-5-9 9"/></svg>
      <div class="value" id="stat-multimodal"><?= $s['multimodal_jobs_done'] ?> / <?= $s['multimodal_jobs_total'] ?></div>
      <div class="label">multimodal (image) jobs processed</div>
      <div class="caption">upload &rarr; base64 in RAM &rarr; sent to model &rarr; discarded</div>
    </div>
  </div>

  <div class="section">
    <h2>Being shared for free, right now</h2>
    <div id="sharing-block">
      <?php if ($s['providers_online'] === 0 && empty($s['hosted_models'])): ?>
        <div class="card empty">Nobody's online right now -- <a href="register.php" style="color:var(--accent-2)">be the first to share something</a>.</div>
      <?php else: ?>
        <div class="card">
          <?php if ($s['providers_online'] > 0): ?>
            <p style="margin:0 0 12px; color:var(--muted); font-size:14px;" id="sharing-summary">
              <?= $s['total_cores'] ?> CPU cores and <?= number_format($s['total_ram_mb'] / 1024, 1) ?> GB RAM
              donated across <?= $s['providers_online'] ?> machine<?= $s['providers_online'] === 1 ? '' : 's' ?><?= $s['gpu_providers'] > 0 ? " ({$s['gpu_providers']} with a GPU)" : '' ?>.
            </p>
          <?php endif; ?>
          <?php if (!empty($s['hosted_models'])): ?>
            <p style="margin:0 0 10px; color:var(--muted); font-size:13px;">LLM models available for text generation:</p>
            <div class="tags" id="hosted-models-tags">
              <?php foreach ($s['hosted_models'] as $model): ?>
                <span class="tag"><?= e($model) ?></span>
              <?php endforeach; ?>
            </div>
          <?php elseif ($s['providers_online'] > 0): ?>
            <p style="margin:0; color:var(--muted); font-size:13px;" id="hosted-models-empty">No one's hosting an LLM for generation right now -- only raw compute (tensor ops, ONNX inference).</p>
          <?php endif; ?>
        </div>
      <?php endif; ?>
    </div>
  </div>

  <div class="grid-2 section">
    <div>
      <h2>Leaderboard</h2>
      <p class="subnote">Bragging rights only -- credits aren't spendable, just recognition for what you've contributed.</p>
      <div class="card" style="padding: 6px 0;" id="leaderboard-block">
        <?php if (empty($s['leaderboard'])): ?>
          <div class="empty">Nobody's shared or used compute here yet -- be the first.</div>
        <?php else: ?>
          <?php foreach ($s['leaderboard'] as $i => $row): ?>
            <?php $rankClass = $i === 0 ? 'gold' : ($i === 1 ? 'silver' : ($i === 2 ? 'bronze' : '')); ?>
            <div class="rank-row">
              <div class="rank-badge <?= $rankClass ?>"><?= $i + 1 ?></div>
              <div class="name"><?= e($row['name']) ?></div>
              <div class="credits"><?= number_format($row['credits'], 1) ?></div>
            </div>
          <?php endforeach; ?>
        <?php endif; ?>
      </div>
    </div>

    <div>
      <h2>Recent activity</h2>
      <p class="subnote">The last few jobs completed on the network.</p>
      <div class="card" style="padding: 6px 0;" id="activity-block">
        <?php if (empty($s['recent_activity'])): ?>
          <div class="empty">Nothing's run yet.</div>
        <?php else: ?>
          <?php foreach ($s['recent_activity'] as $job): ?>
            <div class="activity-row" data-finished-at="<?= $job['finished_at'] ?>">
              <div><?= e(friendly_task_type($job['task_type'])) ?></div>
              <div class="when"><?= number_format($job['compute_seconds'], 2) ?>s compute &middot; <span class="rel-time"></span></div>
            </div>
          <?php endforeach; ?>
        <?php endif; ?>
      </div>
    </div>
  </div>

  <div class="cta-panel">
    <p>Donate spare CPU/RAM/GPU, or point your Omnigent/Claude Code/Cursor agent at
       community-hosted open models -- both start with an account and an API key.</p>
    <a class="btn" href="register.php">Get your API key &rarr;</a>
  </div>

  <footer>
    <span>Nothing here executes remote code -- providers only ever run their own
      fixed, audited handlers on data-only payloads.</span>
    <span><a href="https://github.com/mexmarv/omnigrid">README &amp; source</a></span>
  </footer>
</div>

<script>
function relativeTime(unixSeconds) {
  const diff = Math.max(0, (Date.now() / 1000) - unixSeconds);
  if (diff < 60) return 'just now';
  if (diff < 3600) return Math.floor(diff / 60) + ' min ago';
  if (diff < 86400) return Math.floor(diff / 3600) + ' hr ago';
  return Math.floor(diff / 86400) + ' d ago';
}
function renderRelativeTimes() {
  document.querySelectorAll('.activity-row').forEach(function (row) {
    const el = row.querySelector('.rel-time');
    if (el) el.textContent = relativeTime(parseFloat(row.dataset.finishedAt));
  });
}
renderRelativeTimes();
setInterval(renderRelativeTimes, 30000);

async function refreshStats() {
  try {
    const res = await fetch('api/stats.php');
    const s = await res.json();
    document.getElementById('stat-online').textContent = s.providers_online;
    document.getElementById('stat-hours').textContent = s.compute_hours_donated;
    document.getElementById('stat-jobs').textContent = s.jobs_done + ' / ' + s.jobs_total;
    document.getElementById('stat-multimodal').textContent = s.multimodal_jobs_done + ' / ' + s.multimodal_jobs_total;
    // Leaderboard, sharing block, and activity feed refresh on next full page
    // load -- keeping this lightweight avoids rebuilding DOM structures (and
    // their event state) on every poll for data that rarely changes second to second.
  } catch (e) { /* offline or mid-deploy -- just skip this tick */ }
}
setInterval(refreshStats, 15000);
</script>

</body>
</html>
