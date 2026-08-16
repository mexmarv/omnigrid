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
    $email = trim($_POST['email'] ?? '');
    if ($name === '') {
        $error = 'Enter a name.';
    } elseif ($email === '') {
        $error = 'Enter an email -- only used if you ever need to reissue your API key or delete this account.';
    } else {
        try {
            $result = register_account($pdo, $name, $email);
            $result['name'] = $name;
        } catch (RuntimeException $ex) {
            $error = $ex->getMessage() . ' Pick a different name, or if it\'s yours, use ' .
                '<a href="reset.php" style="color:inherit">reset.php</a> to recover access.';
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
    --text: #e7ecf5; --muted: #9a94b3; --accent: #c084fc; --accent-2: #e879f9; --danger: #ff8080;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background-image: radial-gradient(circle at 15% 0%, rgba(232,121,249,0.12), transparent 40%),
                       radial-gradient(circle at 85% 20%, rgba(192,132,252,0.10), transparent 40%);
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
  input[type=text], input[type=email] {
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
  .copyable {
    position: relative; font-family: ui-monospace, SFMono-Regular, monospace;
    background: var(--panel-2); border: 1px solid var(--border); border-radius: 10px;
    padding: 14px 16px; font-size: 13.5px; word-break: break-all; margin-bottom: 8px;
  }
  h2 { font-size: 15px; color: var(--muted); font-weight: 600; text-transform: uppercase;
       letter-spacing: 0.06em; margin: 28px 0 12px; }
  pre.copyable { white-space: pre-wrap; word-break: normal; overflow-x: auto; line-height: 1.6; }
  code { font-family: ui-monospace, SFMono-Regular, monospace; }
  .copy-btn {
    position: absolute; top: 8px; right: 8px; padding: 5px 10px; font-size: 11.5px;
    font-weight: 600; border-radius: 6px; border: 1px solid var(--border);
    background: var(--panel); color: var(--muted); cursor: pointer;
  }
  .copy-btn:hover { color: var(--text); border-color: var(--accent-2); }
</style>
</head>
<body>
<div class="wrap">
  <a class="back" href="index.php">&larr; back to dashboard</a>
  <h1>Get an Omnigrid account</h1>
  <p class="sub">One name, one API key -- that's the whole account. No password, ever.
     Your email is only ever used for <a href="reset.php" style="color:var(--accent-2)">reset.php</a>
     -- reissuing a lost API key or deleting your account -- never for anything else.</p>

  <?php if ($result === null): ?>
    <div class="card">
      <?php if ($error): ?><div class="error"><?= e($error) ?></div><?php endif; ?>
      <form method="post">
        <label for="name">Account name</label>
        <input type="text" id="name" name="name" placeholder="e.g. your name or handle"
               value="<?= e($_POST['name'] ?? '') ?>" required>
        <label for="email">Email</label>
        <input type="email" id="email" name="email" placeholder="only used to recover this account"
               value="<?= e($_POST['email'] ?? '') ?>" required>
        <button type="submit">Create account</button>
      </form>
    </div>
  <?php else: ?>
    <div class="card">
      <div class="warn">
        This key is shown <strong>once</strong>. Copy it now. If you ever lose it, use
        <a href="reset.php" style="color:inherit">reset.php</a> to get a new one via email --
        it authenticates every request you make as <strong><?= e($result['name']) ?></strong>.
      </div>
      <label>Account name</label>
      <div class="copyable"><?= e($result['name']) ?></div>
      <label>API key</label>
      <div class="copyable"><?= e($result['api_key']) ?></div>
    </div>

    <h2><img src="assets/omnigent-icon.svg" width="16" height="16" style="vertical-align:-3px;margin-right:6px;">Configure Omnigent</h2>
    <div class="warn" style="margin-bottom:16px;">
      <strong>Connect a host first</strong> -- Omnigent sessions execute on
      a "host" (your own machine or a Databricks-managed sandbox), not the
      chat UI itself. A blank host menu or a "Connect a host" prompt when
      starting a session means nothing below will run yet:
      <pre class="copyable" style="margin-top:10px;"><code>curl -fsSL https://omnigent.ai/install.sh | sh -s -- --extra "databricks"
omni setup
omni login &lt;your-workspace-url&gt;
omni host --server &lt;your-workspace-url&gt;</code></pre>
      Keep that running and pick the host it registers before continuing.
    </div>
    <p class="sub" style="margin-bottom:12px;">
      <b>Pick a harness</b> (Claude SDK, Codex, Cursor, Antigravity, etc. --
      omnigrid is just an MCP tool, it works the same under any of them;
      confirmed end-to-end on Antigravity specifically). <b>Expect an
      approval prompt</b> the first time each tool (<code>list_models</code>,
      <code>offload_llm_generate</code>, <code>offload_tensor_op</code>) is
      actually called -- that's Omnigent's policy system pausing on a new
      tool's first use, not a sign anything is broken. If every call keeps
      re-asking instead of just the first, the harness likely isn't
      persisting the tool registration (e.g. a sandbox blocking a global
      config write outside your project folder) -- that's a harness-side
      permissions issue, not an omnigrid one.
    </p>
    <p class="sub" style="margin-bottom:12px;">
      Easiest: paste this into Omnigent's "Describe a task to start a new
      session..." box and it writes the agent + MCP config for you:
    </p>
    <pre class="copyable"><code>Set up a new agent with an MCP tool called "omnigrid" over HTTP, pointing
at <?= e($hub) ?>/mcp.php, with an Authorization header set to
"Bearer <?= e($result['api_key']) ?>". It should be able to call
list_models, offload_llm_generate, and offload_tensor_op through that tool.</code></pre>

    <p class="sub" style="margin:16px 0 6px; font-size:13.5px;">
      Prefer clicking through it yourself? Omnigent also has a
      <b>Create custom agent</b> form -- fill in a name and model, then
      under <b>MCP Tools</b> click <b>+ Add server</b> and enter:
    </p>
    <pre class="copyable"><code>server-name:  omnigrid
command:      python3
args:         /path/to/omnigrid/mcp_server/server.py
env:          OMNIGRID_API_KEY=<?= e($result['api_key']) ?>
              OMNIGRID_HUB=<?= e($hub) ?></code></pre>
    <p class="sub" style="margin:6px 0 0; font-size:12.5px;">
      (Requires Python and this repo checked out wherever Omnigent runs.
      If that form's transport dropdown offers an HTTP option instead of
      stdio, use the URL + header from the YAML below there instead.)
    </p>

    <p class="sub" style="margin:16px 0 6px; font-size:13.5px;">
      Then, once it's wired up, just ask for it in plain language -- for example:
    </p>
    <pre class="copyable"><code>List the models available on Omnigrid, then use whichever one is
hosted to write a two-sentence summary of why octopuses are
considered intelligent.</code></pre>
    <pre class="copyable"><code>Use the omnigrid tool to compute the matrix product of
[[1, 2], [3, 4]] and [[5, 6], [7, 8]].</code></pre>

    <p class="sub" style="margin:20px 0 6px; font-size:13px;">
      Prefer hand-editing an agent file yourself, or using a client with an
      actual config file (Claude Code, Cursor, Codex CLI -- see the
      <a href="https://github.com/mexmarv/omnigrid#use-it-right-now" style="color:var(--accent-2)">full walkthrough</a>
      for each)? Here's the equivalent YAML:
    </p>
    <pre class="copyable"><code>tools:
  omnigrid:
    type: mcp
    url: "<?= e($hub) ?>/mcp.php"
    headers:
      Authorization: "Bearer <?= e($result['api_key']) ?>"</code></pre>

    <p class="sub" style="margin:16px 0 6px; font-size:13px;">
      Prefer running your own local MCP process instead of the hosted one (e.g. for a
      private setup)? Same tools, no server round-trip:
    </p>
    <pre class="copyable"><code>tools:
  omnigrid:
    type: mcp
    command: python3
    args: ["/path/to/omnigrid/mcp_server/server.py"]
    env:
      OMNIGRID_API_KEY: "<?= e($result['api_key']) ?>"
      OMNIGRID_HUB: "<?= e($hub) ?>"</code></pre>

    <h2>Or share compute from the command line</h2>
    <pre class="copyable"><code>python3 agent.py --api-key "<?= e($result['api_key']) ?>" --cpu-cores 2 --ram-mb 2048 \
    --coordinator <?= e($hub) ?></code></pre>
    <p class="sub" style="margin:10px 0 6px; font-size:13px;">
      Have a free <a href="https://build.nvidia.com" style="color:var(--accent-2)">build.nvidia.com</a>
      API key instead of a local model? No GPU needed -- the inference runs on NVIDIA's side:
    </p>
    <pre class="copyable"><code>python3 agent.py --api-key "<?= e($result['api_key']) ?>" --cpu-cores 1 --ram-mb 512 \
    --coordinator <?= e($hub) ?> \
    --nvidia-api-key "nvapi-your-own-key" --nvidia-model-name my-vision-model</code></pre>

    <h2>Or call it directly from Python</h2>
    <pre class="copyable"><code>import client_sdk as cc

text = cc.run_llm_infer("hello!", model_name="&lt;see dashboard for hosted models&gt;",
                         api_key="<?= e($result['api_key']) ?>", coordinator="<?= e($hub) ?>")

result = cc.run_tensor_op("matmul", [[1, 2], [3, 4]], [[5, 6], [7, 8]],
                           api_key="<?= e($result['api_key']) ?>", coordinator="<?= e($hub) ?>")</code></pre>
  <?php endif; ?>
</div>
<script>
// Every .copyable block gets a copy button automatically -- add a new one
// anywhere in this page and it just works, nothing to wire up by hand.
document.querySelectorAll('.copyable').forEach(function (el) {
  const originalText = el.innerText; // captured before the button becomes part of it
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'copy-btn';
  btn.textContent = 'Copy';
  btn.addEventListener('click', function () {
    navigator.clipboard.writeText(originalText).then(function () {
      btn.textContent = 'Copied!';
      setTimeout(function () { btn.textContent = 'Copy'; }, 1500);
    });
  });
  el.appendChild(btn);
});
</script>
</body>
</html>
