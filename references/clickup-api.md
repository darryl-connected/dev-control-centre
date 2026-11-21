# ClickUp API boundary for selected-task intake

The fixed production origin is `https://api.clickup.com`. The only requests are:

| Request | Use |
| --- | --- |
| `GET /api/v2/task/{id}` | One selected native ID, or a parent ID reported by an observed task. The returned native ID must match. |
| `GET /api/v2/task/{id}?custom_task_ids=true&team_id={workspace}` | One explicit custom lookup. The returned `custom_id` and `team_id` must match; subsequent reads use native IDs. `team_id` means Workspace ID in API v2. |
| `GET /api/v2/task/{native_id}/comment` | Top-level task comments, newest first. Subsequent pages pass both `start` (last comment's `date`, in milliseconds) and `start_id` (last comment's `id`). A full page may have older history; fewer than 25 signals the end. |

Public provider references (not contacted by offline verification): `https://developer.clickup.com/reference/gettask`, `https://developer.clickup.com/reference/gettaskcomments`, `https://developer.clickup.com/docs/authentication`. ClickUp describes personal tokens for individual use and OAuth for apps used by others. This reader does not provision OAuth, narrow account permissions or establish vendor policy compliance. Each developer supplies their own credential locally. The token goes verbatim in `Authorization`, not into URLs, proxy configuration, request bodies or settings. Local validation checks for 1–512 printable ASCII characters without spaces; only the provider can establish authorization.

The reader uses Python's standard `http.client` and a verified TLS client context with hostname checks. It consumes neither proxy settings nor an API base override, follows no redirects, and never writes or retries. No error body, response headers or upstream exception details are emitted. The CLI redacts the exact configured token, not arbitrary secrets; other private task text is preserved in output.

One intake stops at four ancestors beyond the selected task, four comment pages of up to 25 per observed task, 25 total HTTP attempts, and 1 MiB per successful response body. The socket/I/O timeout is 10 seconds, not a wall-clock deadline for a trickling peer. A repeated parent or non-progressing cursor, failed source, outstanding parent, full final page or provider-advertised reply thread yields an unresolved source and a nonzero exit. No sibling, task dependency, thread expansion, attachment or external link is followed. The result is not exhaustive source review or permission to act. See the [reader guide](../docs/clickup.md).
