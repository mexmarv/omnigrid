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
    --text: #e7ecf5; --muted: #9a94b3; --accent: #8b5cf6; --accent-2: #ec4899; --danger: #ff8080;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background-image: radial-gradient(circle at 15% 0%, rgba(236,72,153,0.12), transparent 40%),
                       radial-gradient(circle at 85% 20%, rgba(139,92,246,0.10), transparent 40%);
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

    <?php $apiKey = $result['api_key']; require __DIR__ . '/_account_instructions.php'; ?>
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
