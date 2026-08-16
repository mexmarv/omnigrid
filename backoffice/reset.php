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

$hub = hub_base_url();
$token = $_GET['token'] ?? $_POST['token'] ?? null;
$emailSent = false;
$newApiKey = null;
$deleted = false;
$error = null;
$tokenAccount = $token !== null ? find_account_by_reset_token($pdo, $token) : null;

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $action = $_POST['action'] ?? '';

    if ($action === 'request') {
        $name = trim($_POST['name'] ?? '');
        $email = trim($_POST['email'] ?? '');
        if ($name !== '' && $email !== '') {
            request_password_reset($pdo, $name, $email, $hub);
        }
        $emailSent = true; // shown regardless of match -- don't leak which accounts exist
    } elseif ($action === 'reissue' && $tokenAccount !== null) {
        $newApiKey = reissue_api_key($pdo, (int)$tokenAccount['id']);
    } elseif ($action === 'delete' && $tokenAccount !== null) {
        delete_account($pdo, (int)$tokenAccount['id']);
        $deleted = true;
        $tokenAccount = null;
    } else {
        $error = 'That link is invalid or has expired -- request a new one below.';
    }
}
?>
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Reset your Omnigrid account</title>
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
  .wrap { max-width: 640px; margin: 0 auto; padding: 56px 24px 80px; }
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
  button.danger { background: var(--danger); color: #2a0505; }
  .actions { display: flex; gap: 12px; flex-wrap: wrap; }
  .error { color: var(--danger); font-size: 14px; margin-bottom: 16px; }
  .notice {
    background: rgba(139,92,246,0.08); border: 1px solid rgba(139,92,246,0.3);
    border-radius: 10px; padding: 14px 16px; font-size: 13.5px; color: var(--accent);
  }
  .warn {
    background: rgba(255,128,128,0.08); border: 1px solid rgba(255,128,128,0.3);
    border-radius: 10px; padding: 14px 16px; font-size: 13.5px; color: #ffb3b3; margin-bottom: 20px;
  }
  .copyable {
    position: relative; font-family: ui-monospace, SFMono-Regular, monospace;
    background: var(--panel-2); border: 1px solid var(--border); border-radius: 10px;
    padding: 14px 16px; font-size: 13.5px; word-break: break-all;
  }
  .copy-btn {
    position: absolute; top: 8px; right: 8px; padding: 5px 10px; font-size: 11.5px;
    font-weight: 600; border-radius: 6px; border: 1px solid var(--border);
    background: var(--panel); color: var(--muted); cursor: pointer;
  }
  .copy-btn:hover { color: var(--text); border-color: var(--accent-2); }
  h2 { font-size: 15px; color: var(--muted); font-weight: 600; text-transform: uppercase;
       letter-spacing: 0.06em; margin: 28px 0 12px; }
  pre.copyable { white-space: pre-wrap; word-break: normal; overflow-x: auto; line-height: 1.6; }
  code { font-family: ui-monospace, SFMono-Regular, monospace; }
</style>
</head>
<body>
<div class="wrap">
  <a class="back" href="index.php">&larr; back to dashboard</a>
  <h1>Reset your Omnigrid account</h1>

  <?php if ($newApiKey !== null): ?>
    <p class="sub">Your new API key. The old one stopped working the moment this was issued.</p>
    <div class="card">
      <div class="warn">Shown <strong>once</strong> -- copy it now.</div>
      <label>API key</label>
      <div class="copyable"><?= e($newApiKey) ?></div>
    </div>
    <?php $apiKey = $newApiKey; require __DIR__ . '/_account_instructions.php'; ?>

  <?php elseif ($deleted): ?>
    <p class="sub">Done. The account and any providers it registered are gone.
       Anything it was hosting will just drop offline on its next missed heartbeat.</p>

  <?php elseif ($tokenAccount !== null): ?>
    <p class="sub">Confirmed: this link is for <strong><?= e($tokenAccount['name']) ?></strong>.
       Pick one -- both invalidate the link after use.</p>
    <div class="card">
      <div class="actions">
        <form method="post">
          <input type="hidden" name="token" value="<?= e($token) ?>">
          <input type="hidden" name="action" value="reissue">
          <button type="submit">Issue a new API key</button>
        </form>
        <form method="post" onsubmit="return confirm('Delete this account permanently? This cannot be undone.');">
          <input type="hidden" name="token" value="<?= e($token) ?>">
          <input type="hidden" name="action" value="delete">
          <button type="submit" class="danger">Delete my account</button>
        </form>
      </div>
    </div>

  <?php elseif ($emailSent): ?>
    <div class="card">
      <div class="notice">If that name and email match an account, a link just went out to it.
        Check your inbox -- it's valid for one hour.</div>
    </div>

  <?php else: ?>
    <p class="sub">No password to reset -- enter the name and email you registered with and
       we'll email you a link to reissue your API key or delete the account.</p>
    <div class="card">
      <?php if ($error): ?><div class="error"><?= e($error) ?></div><?php endif; ?>
      <form method="post">
        <input type="hidden" name="action" value="request">
        <label for="name">Account name</label>
        <input type="text" id="name" name="name" required>
        <label for="email">Email you registered with</label>
        <input type="email" id="email" name="email" required>
        <button type="submit">Send reset link</button>
      </form>
    </div>
  <?php endif; ?>
</div>
<script>
document.querySelectorAll('.copyable').forEach(function (el) {
  const originalText = el.innerText;
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
