# Connecting Cursor and This Repo to GitHub

Two separate things are useful to set up:

1. **Git repo → GitHub**  
   So the code is pushed to and pulled from a GitHub repository.

2. **Cursor → GitHub (issues, PRs, projects)**  
   So Cursor’s Agent can use GitHub (e.g. list issues, open PRs, search code) via the **GitHub MCP server**.

---

## 1. Link this repo to a GitHub repository

If the remote is already set (e.g. from a template), just fix the URL if needed:

```bash
git remote -v
git remote set-url origin https://github.com/<owner>/<repo>.git
git push -u origin HEAD
```

If there is no `origin`:

```bash
git remote add origin https://github.com/<owner>/<repo>.git
git push -u origin HEAD
```

Use your real GitHub org/user and repo name. After this, Cursor’s built-in Git support will work against that GitHub repo (branches, push, pull, etc.).

---

## 2. Connect Cursor to GitHub (issues, PRs, projects) via MCP

To let Cursor’s Agent **query issues, look at PRs, search the repo, and use project boards**, add the **GitHub MCP server** to Cursor.

### Prerequisites

- **GitHub Personal Access Token (PAT)** — see [PAT permissions (read-only vs write)](#pat-permissions-read-only-vs-write) below.
- **Cursor 0.48+** for the recommended “remote” setup.

### PAT permissions: read-only vs write

Use a **fine-grained** PAT (not classic). Classic tokens have no read-only repo scope; fine-grained lets you grant only **read** where you want.

**Broad read, no write (recommended to start):**

1. Go to [GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens](https://github.com/settings/personal-access-tokens?type=beta).
2. **Generate new token.** Pick a name (e.g. “Cursor MCP read-only”), set **Resource owner** (your user or org), and under **Repository access** choose “Only select repositories” and add the repos you care about (or “All repositories” if you want).
3. Under **Repository permissions**, set only **Read** for:
   - **Metadata** — required for most API calls (read-only).
   - **Contents** — read code, files, search.
   - **Issues** — list and read issues.
   - **Pull requests** — list and read PRs.
4. Optionally, for read-only access to more features:
   - **Actions** → Read (workflow runs, logs).
   - **Security events** → Read (code scanning).
   - **Dependabot alerts** → Read.
5. If the resource owner is an **organization** and you use **Projects**: under **Organization permissions**, set **Projects** → **Read**.
6. Do **not** grant any **Write** or **Admin** permissions. Save and copy the token once (it won’t be shown again).

**If you need write later** (e.g. create issues, comment on PRs): create a second fine-grained token and add **Write** only for the specific permissions you need (e.g. Issues, Pull requests), or switch this token to include those write permissions.

### Option A: Remote GitHub MCP (recommended)

Uses GitHub’s hosted MCP; no Docker. Cursor talks to `https://api.githubcopilot.com/mcp/`.

1. Open Cursor **Settings** → **Tools & MCP** (or create/edit the config file below).
2. Add the GitHub MCP server.

**If you use a global config** (PAT stays only on your machine):

- Edit **`~/.cursor/mcp.json`** (create it if needed). Use this shape (Cursor uses the key `mcpServers`):

```json
{
  "mcpServers": {
    "github": {
      "url": "https://api.githubcopilot.com/mcp/",
      "headers": {
        "Authorization": "Bearer YOUR_GITHUB_PAT"
      }
    }
  }
}
```

- Replace `YOUR_GITHUB_PAT` with your real token. **Do not commit this file or your PAT to the repo.**

**If you use a project config** (so everyone on the team gets the same MCP in this workspace):

- Edit **`.cursor/mcp.json`** in this repo with the same JSON.
- Replace `YOUR_GITHUB_PAT` with your token only in your **local** copy.  
  Add a note in this doc or in the file that teammates must substitute their own PAT and must **never** commit a real token.

3. Save, then **restart Cursor**.
4. In **Settings → Tools & MCP**, confirm the **github** server is listed and enabled (e.g. green / connected).
5. In chat, use **Agent** mode and try: *“List my GitHub repositories”* or *“Show open issues for this repo.”*

### Option B: Local GitHub MCP (Docker)

Runs the MCP server in Docker on your machine. Use this if the remote server is not an option.

1. Install and run [Docker](https://www.docker.com/).
2. In **`~/.cursor/mcp.json`** (or project **`.cursor/mcp.json`**), add:

```json
{
  "mcpServers": {
    "github": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "-e",
        "GITHUB_PERSONAL_ACCESS_TOKEN",
        "ghcr.io/github/github-mcp-server"
      ],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "YOUR_GITHUB_PAT"
      }
    }
  }
}
```

3. Replace `YOUR_GITHUB_PAT` with your token. Do not commit the real token.
4. Save and restart Cursor.

### What the GitHub MCP gives you

With the server connected, Cursor’s Agent can use GitHub to:

- **Issues** – list, create, update, comment.
- **Pull requests** – list, open, review, comment.
- **Repositories** – search files, inspect commits, browse code.
- **Projects** – see below.

So you get both: **this repo** linked to GitHub via Git, and **Cursor** linked to GitHub (issues, PRs, projects) via the GitHub MCP server.

### Enabling GitHub Projects (boards / tables)

The same GitHub MCP server can work with **GitHub Projects** (the project boards/tables where you track issues and PRs). The `projects` toolset is **not** in the default set; you have to enable it.

**Option 1 – Add projects to your existing remote config (recommended)**  
Keep your current `github` entry and add the `X-MCP-Toolsets` and (optional) `X-MCP-Readonly` headers so the default toolsets plus `projects` are enabled:

```json
{
  "mcpServers": {
    "github": {
      "url": "https://api.githubcopilot.com/mcp/",
      "headers": {
        "Authorization": "Bearer YOUR_GITHUB_PAT",
        "X-MCP-Toolsets": "repos,issues,pull_requests,users,context,projects",
        "X-MCP-Readonly": "true"
      }
    }
  }
}
```

**Option 2 – Projects-only (read-only)**  
If you only want Projects and no repos/issues/PRs, point the URL at the projects toolset:

```json
"github-projects": {
  "url": "https://api.githubcopilot.com/mcp/x/projects/readonly",
  "headers": {
    "Authorization": "Bearer YOUR_GITHUB_PAT"
  }
}
```

**PAT for Projects**  
- **User-owned projects**: repo (or fine-grained Contents/Metadata, etc.) is enough.  
- **Organization projects**: your fine-grained PAT must have **Organization permissions → Projects → Read** (and the token’s resource owner must be that org).

Reference: [Remote GitHub MCP Server – toolsets](https://github.com/github/github-mcp-server/blob/main/docs/remote-server.md) (includes `projects` and optional headers).

### Troubleshooting

- **Not connecting**: Restart Cursor after changing `mcp.json`. Check **Settings → Tools & MCP** and MCP logs (Output panel → MCP).
- **Auth errors**: Regenerate the PAT with the scopes above; ensure no extra spaces in the `Authorization` header.
- **Remote server**: Needs Cursor 0.48+ and network access to `https://api.githubcopilot.com`.

Reference: [GitHub MCP Server – Install in Cursor](https://github.com/github/github-mcp-server/blob/main/docs/installation-guides/install-cursor.md).
