# 自动部署（GitHub Actions）

改完代码 `git push` 到 GitHub 后，GitHub 会自动把文件同步到服务器并重启服务，**不用再手动拖文件**。

原理：GitHub 的服务器（在美国）通过 SSH 连到你的服务器，用 `rsync` 覆盖 `/opt/quicktransform` 的代码，然后执行 `systemctl restart quicktransform`。

> ⚠️ 这套只能同步代码 + 重启。如果以后 `deploy/requirements.txt` 新增了依赖，仍需要手动上服务器执行一次 `pip install -r deploy/requirements.txt`。

---

## 一次性准备（只需做一次）

### 第 1 步：服务器上生成部署密钥

用 FinalShell 连上服务器，在终端里依次执行：

```bash
# 1) 安装 rsync（文件同步用，已装会提示“已安装”，忽略即可）
dnf install -y rsync

# 2) 生成一把专用部署密钥（遇到提示一路回车即可）
ssh-keygen -t ed25519 -f ~/.ssh/deploy_github -N "" -C "github-actions"

# 3) 把公钥加入授权，允许 GitHub 用它登录
cat ~/.ssh/deploy_github.pub >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys

# 4) 打印私钥，整段复制出来（含 BEGIN / END 两行），下一步要用
cat ~/.ssh/deploy_github
```

第 4 步打印出的是一大段文字，长得像：

```
-----BEGIN OPENSSH PRIVATE KEY-----
（中间一堆字符）
-----END OPENSSH PRIVATE KEY-----
```

把**整段**（包括 `-----BEGIN...` 和 `-----END...` 两行）复制下来。

### 第 2 步：在 GitHub 仓库里加 3 个 Secret

浏览器打开仓库 → **Settings → Secrets and variables → Actions → New repository secret**，依次添加：

| Name | Secret（值） |
| --- | --- |
| `DEPLOY_HOST` | `115.29.149.87` |
| `DEPLOY_USER` | `root` |
| `DEPLOY_KEY` | 第 1 步第 4 小步复制的**整段私钥**（多行，直接粘贴进去） |

> 如果你以后换服务器 IP 或改用别的登录用户，改这里的 `DEPLOY_HOST` / `DEPLOY_USER` 即可。

### 第 3 步：安全组放行 22 端口给 GitHub

GitHub 的服务器在美国，必须能 SSH 到你的服务器。在**阿里云控制台 → 安全组**里确认：

- 22 端口（SSH）对 `0.0.0.0/0` 放行，**或者**至少对 GitHub Actions 的 IP 段放行。

如果你之前只对自己的 IP 放开了 22，那 GitHub 连不上，工作流会报 `Connection timed out`。最省事是 22 端口对 `0.0.0.0/0` 开放（SSH 靠密钥登录，安全性足够）。

> 如果服务器的 SSH 端口不是 22（宝塔有时会改端口），告诉我，我在工作流里加一个 `DEPLOY_PORT`。

---

## 以后怎么用

改完代码后，本地执行：

```bash
git add .
git commit -m "描述这次改了什么"
git push
```

push 完成后，GitHub 会自动部署。去仓库的 **Actions** 标签页能看到「Deploy to server」这条运行记录：

- 绿色 ✔ = 部署成功
- 红色 ✘ = 失败（点进去看日志）

也可以**手动触发**：**Actions → Deploy to server → Run workflow**，不用 push 代码。

---

## 常见问题

- **第一次 push 显示红色失败**：多半是第 1～3 步还没做完（缺密钥 / 缺 Secret / 安全组没放行）。做完后到 Actions 里那条失败的记录点 **Re-run jobs**，或直接 `git push` 一次。
- **日志里 `rsync: command not found`**：第 1 步第 1 小步的 `dnf install -y rsync` 没执行成功，重跑一次。
- **`Permission denied (publickey)`**：`DEPLOY_KEY` 没复制完整（缺了 BEGIN/END 行或漏字符），重新复制粘贴一遍。
- **部署成功了但网页没变化**：可能是浏览器缓存，强制刷新（Ctrl+F5）再看。
