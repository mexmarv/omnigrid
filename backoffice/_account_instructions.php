<?php
/**
 * Shared "how to wire this account up" block. Expects $apiKey and $hub
 * already set by the includer -- shown after both a fresh registration
 * and a key reissue via reset.php, so it stays a single source of truth
 * instead of drifting between two copies.
 */
?>
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
"Bearer <?= e($apiKey) ?>". It should be able to call
list_models, offload_llm_generate, and offload_tensor_op through that tool.</code></pre>

    <p class="sub" style="margin:16px 0 6px; font-size:13.5px;">
      Prefer clicking through it yourself? Omnigent also has a
      <b>Create custom agent</b> form -- fill in a name and model, then
      under <b>MCP Tools</b> click <b>+ Add server</b> and enter:
    </p>
    <pre class="copyable"><code>server-name:  omnigrid
command:      python3
args:         /path/to/omnigrid/mcp_server/server.py
env:          OMNIGRID_API_KEY=<?= e($apiKey) ?>
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

    <h2>Or add it with a CLI one-liner (Claude Code / Gemini CLI)</h2>
    <p class="sub" style="margin-bottom:12px;">Both CLIs share the same
      <code>mcp add</code> flags, so it's the same command either way:</p>
    <pre class="copyable"><code>claude mcp add --transport http omnigrid <?= e($hub) ?>/mcp.php \
  --header "Authorization: Bearer <?= e($apiKey) ?>"</code></pre>
    <pre class="copyable"><code>gemini mcp add --transport http omnigrid <?= e($hub) ?>/mcp.php \
  --header "Authorization: Bearer <?= e($apiKey) ?>"</code></pre>

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
      Authorization: "Bearer <?= e($apiKey) ?>"</code></pre>

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
      OMNIGRID_API_KEY: "<?= e($apiKey) ?>"
      OMNIGRID_HUB: "<?= e($hub) ?>"</code></pre>

    <h2>Or share compute from the command line</h2>
    <pre class="copyable"><code>python3 agent.py --api-key "<?= e($apiKey) ?>" --cpu-cores 2 --ram-mb 2048 \
    --coordinator <?= e($hub) ?></code></pre>
    <p class="sub" style="margin:10px 0 6px; font-size:13px;">
      Have a GGUF vision-language model (+ its mmproj vision projector file) sitting around?
      Host it for image recognition:
    </p>
    <pre class="copyable"><code>python3 agent.py --api-key "<?= e($apiKey) ?>" --cpu-cores 1 --ram-mb 512 \
    --coordinator <?= e($hub) ?> \
    --vlm-model-path /path/to/model.gguf --vlm-mmproj-path /path/to/mmproj.gguf \
    --vlm-model-name my-vision-model</code></pre>

    <h2>Or call it directly from Python</h2>
    <pre class="copyable"><code>import client_sdk as cc

text = cc.run_llm_infer("hello!", model_name="&lt;see dashboard for hosted models&gt;",
                         api_key="<?= e($apiKey) ?>", coordinator="<?= e($hub) ?>")

result = cc.run_tensor_op("matmul", [[1, 2], [3, 4]], [[5, 6], [7, 8]],
                           api_key="<?= e($apiKey) ?>", coordinator="<?= e($hub) ?>")</code></pre>
