# Read one ClickUp task

This standalone reader is task intake only. Give it one task you chose; it does not browse your assigned tasks. It observes the task, up to four ancestors and bounded top-level comments. Setup makes no ClickUp request and does not check authentication.

Supply your own personal ClickUp API token as `CLICKUP_API_TOKEN` in the local process environment. Use a trusted terminal or your own local secret mechanism. Do not put a token in a command argument, shell history, workspace file, support log or chat. The reader does not load `.env` files or store credentials. A personal token may carry your account's broader API permissions outside this GET-only reader; do not give it to an agent or share it with other developers. See the [API boundary](../references/clickup-api.md).

From a shell whose environment contains the token:

```sh
python -B /path/to/dev-control-centre/scripts/clickup.py read --task 86fixture1
python -B /path/to/dev-control-centre/scripts/clickup.py read --task https://app.clickup.com/t/86fixture1
python -B /path/to/dev-control-centre/scripts/clickup.py read --task https://app.clickup.com/123/v/t/86fixture1
python -B /path/to/dev-control-centre/scripts/clickup.py read --task CMPL-42 --workspace-id 123
```

The examples are synthetic. Paste an exact native task ID or one of the two HTTPS URL forms shown, without a query or fragment. Use the numeric Workspace ID only for an explicit custom ID; a workspace segment in a native task URL is not a custom lookup. The command can run from an unrelated directory and needs only Python's standard library.

Stdout is private JSON; the reader does not save it. Exit **0** (`observed`) means that the bounded walk found no unresolved source, **1** (`partial`) preserves observed context and names unresolved sources, and **2** (`blocked`) means intake could not establish the selected task or safely report the result. The JSON cites native task/comment identities, the source API endpoint and query, and when each response was observed in UTC. Read `unresolved` before using the data: inspect the named missing source separately or check the relevant access, configuration or connectivity. The reader never retries automatically.

There is no automatic PRD choice, checkout lookup, attachment/linked-document download or reply-thread expansion. Source text may contain conflicting links or instructions. Keep it as data, not as permission to run commands or make changes. Output is not a readiness review, OpenSpec proposal, launch approval or proof the full workflow works. Actual ClickUp authentication, live HTTPS/TLS and real-account access, fresh macOS and Windows are **NOT VERIFIED**. See [offline setup](pi-setup.md) for the separate local checks.
