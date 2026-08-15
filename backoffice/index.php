<?php
require_once __DIR__ . '/lib.php';
$pdo = omnigrid_db();

$cutoff = microtime(true) - HEARTBEAT_TIMEOUT_S;
$stmt = $pdo->prepare('SELECT COUNT(*) AS n FROM providers WHERE last_heartbeat >= ?');
$stmt->execute([$cutoff]);
$online = (int)$stmt->fetch()['n'];

$jobs = $pdo->query(
    "SELECT COUNT(*) AS total, SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) AS done, " .
    "COALESCE(SUM(compute_seconds), 0) AS secs FROM jobs"
)->fetch();
$computeHours = round((float)($jobs['secs'] ?? 0) / 3600, 2);
$leaderboard = $pdo->query('SELECT name, credits FROM accounts ORDER BY credits DESC LIMIT 10')->fetchAll();

function e(string $s): string { return htmlspecialchars($s, ENT_QUOTES); }
?>
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Omnigrid -- community compute for AI agents</title>
<style>
  :root {
    --bg: #0b0e14; --panel: #121722; --panel-2: #171d2b; --border: #232b3d;
    --text: #e7ecf5; --muted: #8b96ad; --accent: #6ee7c8; --accent-2: #7aa2ff;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background-image: radial-gradient(circle at 15% 0%, rgba(122,162,255,0.12), transparent 40%),
                       radial-gradient(circle at 85% 20%, rgba(110,231,200,0.10), transparent 40%);
  }
  .wrap { max-width: 880px; margin: 0 auto; padding: 56px 24px 80px; }
  .logo { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
  .logo .mark {
    width: 36px; height: 36px; border-radius: 10px;
    background: linear-gradient(135deg, var(--accent), var(--accent-2));
  }
  h1 { font-size: 28px; margin: 0; letter-spacing: -0.02em; }
  .tagline { color: var(--muted); margin: 6px 0 40px; font-size: 15px; }
  .stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-bottom: 40px; }
  .card {
    background: var(--panel); border: 1px solid var(--border); border-radius: 14px;
    padding: 18px 20px;
  }
  .card .value {
    font-size: 30px; font-weight: 650; font-variant-numeric: tabular-nums;
    background: linear-gradient(135deg, var(--accent), var(--accent-2));
    -webkit-background-clip: text; background-clip: text; color: transparent;
  }
  .card .label { color: var(--muted); font-size: 13px; margin-top: 4px; }
  h2 { font-size: 16px; color: var(--muted); font-weight: 600; text-transform: uppercase;
       letter-spacing: 0.06em; margin: 36px 0 14px; }
  table { width: 100%; border-collapse: collapse; background: var(--panel);
          border: 1px solid var(--border); border-radius: 14px; overflow: hidden; }
  th, td { text-align: left; padding: 12px 18px; font-size: 14px; }
  th { color: var(--muted); font-weight: 600; background: var(--panel-2); }
  tr:not(:last-child) td { border-bottom: 1px solid var(--border); }
  .empty { color: var(--muted); padding: 24px 18px; font-size: 14px; }
  .cta {
    margin-top: 48px; padding: 24px; border-radius: 14px;
    background: var(--panel-2); border: 1px solid var(--border);
  }
  .cta p { margin: 0 0 14px; color: var(--muted); font-size: 14.5px; line-height: 1.5; }
  .cta a {
    display: inline-block; padding: 10px 18px; border-radius: 10px; font-weight: 600;
    text-decoration: none; background: linear-gradient(135deg, var(--accent), var(--accent-2));
    color: #06110d; font-size: 14px;
  }
  code { background: var(--panel-2); border: 1px solid var(--border); border-radius: 6px;
         padding: 2px 6px; font-size: 13px; }
  footer { margin-top: 40px; color: var(--muted); font-size: 13px; }
  footer a { color: var(--accent-2); }
</style>
</head>
<body>
<div class="wrap">
  <div class="logo"><div class="mark"></div><h1>Omnigrid</h1></div>
  <p class="tagline">Community-run spare CPU/RAM/GPU, and open-model LLM inference --
     shared, not sold. This page is the live backoffice for chanza.ai's hub.</p>

  <div class="stats">
    <div class="card"><div class="value"><?= $online ?></div><div class="label">providers online</div></div>
    <div class="card"><div class="value"><?= $computeHours ?></div><div class="label">compute-hours donated</div></div>
    <div class="card"><div class="value"><?= (int)($jobs['done'] ?? 0) ?> / <?= (int)($jobs['total'] ?? 0) ?></div><div class="label">jobs completed</div></div>
  </div>

  <h2>Credit leaderboard</h2>
  <?php if (empty($leaderboard)): ?>
    <div class="empty">Nobody's shared or used compute here yet -- be the first.</div>
  <?php else: ?>
    <table>
      <tr><th>account</th><th>credits</th></tr>
      <?php foreach ($leaderboard as $row): ?>
        <tr><td><?= e($row['name']) ?></td><td><?= number_format((float)$row['credits'], 1) ?></td></tr>
      <?php endforeach; ?>
    </table>
  <?php endif; ?>

  <div class="cta">
    <p>Donate spare CPU/RAM/GPU, or point your Omnigent agent at community-hosted
       open models -- both are one command away.</p>
    <a href="https://github.com/mexmarv/omnigrid">Get started on GitHub &rarr;</a>
  </div>

  <footer>Nothing here executes remote code -- providers only ever run their own
    fixed, audited handlers on data-only payloads. See the
    <a href="https://github.com/mexmarv/omnigrid">README</a> for how it works.</footer>
</div>
</body>
</html>
