<?php
require_once __DIR__ . '/lib.php';
$pdo = omnigrid_db();

function e(string $s): string { return htmlspecialchars($s, ENT_QUOTES); }

function hub_base_url(): string {
    $scheme = 'http';
    if (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off') {
        $scheme = 'https';
    } elseif (($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '') === 'https') {
        $scheme = 'https';
    }
    $host = $_SERVER['HTTP_HOST'] ?? 'chanza.ai';
    return "$scheme://$host";
}

$error = null;
$result = null;

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $name = trim($_POST['name'] ?? '');
    if ($name === '') {
        $error = 'Enter a name.';
    } else {
        try {
            $result = register_account($pdo, $name);
            $result['name'] = $name;
        } catch (RuntimeException $ex) {
            $error = $ex->getMessage() . ' Pick a different name, or if it\'s yours, use the API key you already saved.';
        }
    }
}

$hub = hub_base_url();
?>
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Get an Omnigrid account</title>
<style>
  :root {
    --bg: #0b0e14; --panel: #121722; --panel-2: #171d2b; --border: #232b3d;
    --text: #e7ecf5; --muted: #8b96ad; --accent: #6ee7c8; --accent-2: #7aa2ff; --danger: #ff8080;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background-image: radial-gradient(circle at 15% 0%, rgba(122,162,255,0.12), transparent 40%),
                       radial-gradient(circle at 85% 20%, rgba(110,231,200,0.10), transparent 40%);
  }
  .wrap { max-width: 720px; margin: 0 auto; padding: 56px 24px 80px; }
  a.back { color: var(--muted); font-size: 13.5px; text-decoration: none; }
  h1 { font-size: 26px; margin: 18px 0 6px; letter-spacing: -0.02em; }
  p.sub { color: var(--muted); margin: 0 0 32px; font-size: 14.5px; line-height: 1.5; }
  .card {
    background: var(--panel); border: 1px solid var(--border); border-radius: 14px;
    padding: 24px; margin-bottom: 20px;
  }
  label { display: block; font-size: 13.5px; color: var(--muted); margin-bottom: 8px; }
  input[type=text] {
    width: 100%; padding: 12px 14px; border-radius: 10px; border: 1px solid var(--border);
    background: var(--panel-2); color: var(--text); font-size: 15px; margin-bottom: 16px;
  }
  button {
    padding: 11px 20px; border-radius: 10px; border: none; font-weight: 600; font-size: 14px;
    background: linear-gradient(135deg, var(--accent), var(--accent-2)); color: #06110d; cursor: pointer;
  }
  .error { color: var(--danger); font-size: 14px; margin-bottom: 16px; }
  .warn {
    background: rgba(255,128,128,0.08); border: 1px solid rgba(255,128,128,0.3);
    border-radius: 10px; padding: 14px 16px; font-size: 13.5px; color: #ffb3b3; margin-bottom: 20px;
  }
  .key {
    font-family: ui-monospace, SFMono-Regular, monospace; background: var(--panel-2);
    border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; font-size: 13.5px;
    word-break: break-all; margin-bottom: 8px;
  }
  h2 { font-size: 15px; color: var(--muted); font-weight: 600; text-transform: uppercase;
       letter-spacing: 0.06em; margin: 28px 0 12px; }
  pre {
    background: var(--panel-2); border: 1px solid var(--border); border-radius: 10px;
    padding: 16px; overflow-x: auto; font-size: 13px; line-height: 1.6;
  }
  code { font-family: ui-monospace, SFMono-Regular, monospace; }
</style>
</head>
<body>
<div class="wrap">
  <a class="back" href="index.php">&larr; back to dashboard</a>
  <h1>Get an Omnigrid account</h1>
  <p class="sub">One name, one API key -- that's the whole account. No password, no email,
     no recovery if you lose the key, so save it somewhere real the moment you see it.</p>

  <?php if ($result === null): ?>
    <div class="card">
      <?php if ($error): ?><div class="error"><?= e($error) ?></div><?php endif; ?>
      <form method="post">
        <label for="name">Account name</label>
        <input type="text" id="name" name="name" placeholder="e.g. your name or handle"
               value="<?= e($_POST['name'] ?? '') ?>" required>
        <button type="submit">Create account</button>
      </form>
    </div>
  <?php else: ?>
    <div class="card">
      <div class="warn">
        This key is shown <strong>once</strong>. Copy it now -- there's no recovery flow.
        It authenticates every request you make as <strong><?= e($result['name']) ?></strong>.
      </div>
      <label>Account name</label>
      <div class="key"><?= e($result['name']) ?></div>
      <label>API key</label>
      <div class="key"><?= e($result['api_key']) ?></div>
    </div>

    <h2>Configure Omnigent</h2>
    <p class="sub" style="margin-bottom:12px;">
      Nothing to install -- add this to your agent's YAML under <code>tools:</code>
      and it points straight at the hosted MCP endpoint. See the
      <a href="https://github.com/mexmarv/omnigrid#use-the-network" style="color:var(--accent-2)">full walkthrough</a>
      for what to actually type into the chat once it's wired up.
    </p>
    <pre><code>tools:
  omnigrid:
    type: mcp
    url: "<?= e($hub) ?>/mcp.php"
    headers:
      Authorization: "Bearer <?= e($result['api_key']) ?>"</code></pre>

    <p class="sub" style="margin:16px 0 6px; font-size:13px;">
      Prefer running your own local MCP process instead of the hosted one (e.g. for a
      private setup)? Same three tools, no server round-trip:
    </p>
    <pre><code>tools:
  omnigrid:
    type: mcp
    command: python3
    args: ["/path/to/omnigrid/mcp_server/server.py"]
    env:
      OMNIGRID_ACCOUNT: "<?= e($result['name']) ?>"
      OMNIGRID_HUB: "<?= e($hub) ?>"</code></pre>

    <h2>Or share compute from the command line</h2>
    <pre><code>python3 agent.py --name "<?= e($result['name']) ?>" --cpu-cores 2 --ram-mb 2048 \
    --coordinator <?= e($hub) ?></code></pre>

    <h2>Or call it directly from Python</h2>
    <pre><code>import client_sdk as cc

text = cc.run_llm_infer("hello!", model_name="&lt;see dashboard for hosted models&gt;",
                         account_name="<?= e($result['name']) ?>", coordinator="<?= e($hub) ?>")</code></pre>
  <?php endif; ?>
</div>
</body>
</html>
