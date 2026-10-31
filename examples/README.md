# Deployment examples

A complete walk-through for one typical setup: the Windows 7 machine runs an
iroh serve node that accepts connections through a self-hosted
[iroh relay](https://github.com/n0-computer/iroh) and forwards each of them
into its local SSH server. Any other machine can then reach it with the
`stdio` mode of the same script as an ssh `ProxyCommand` — no tunneled ports,
no port forwarding, the relay is the only meeting point.

Everything below was exercised on Windows 7 SP1 x64.

## 0. Prerequisites on the Windows 7 machine

- An x64 CPython installed and on PATH (the wheel is `py3-none`, any version
  works; community Windows 7 builds of CPython 3.9–3.13 are fine).
- The SSH server listening on `127.0.0.1:22` (that is the forward target; any
  other local TCP service works too).
- The wheel built by [`build.py`](../build.py).

## 1. Deploy the wheel and the scripts

```
mkdir C:\iroh7\site
python -m zipfile -e dist\iroh-<v>-win7-yythunks-py3-none-win_amd64.whl C:\iroh7\site\
copy serve_node.py  C:\iroh7\
copy serve_launcher.py C:\iroh7\
```

## 2. Relay configuration

The node registers at your self-hosted relay and needs:

- the relay URL and QUIC port: `IROH_RELAY_URL`, `IROH_RELAY_QUIC_PORT`
  (defaults are placeholders — set them);
- an auth token in `C:\Users\<you>\.config\iroh-ssh\token` (or
  `IROH_RELAY_TOKEN`).

Node identity lives in `C:\Users\<you>\.config\iroh-ssh\secret.key`, minted on
first run. **The endpoint id derives from this file**: back it up, and never
copy it to a second machine — a duplicated id makes both instances race for
incoming connections.

## 3. First run (smoke test)

```
set PYTHONPATH=C:\iroh7\site
python C:\iroh7\serve_node.py serve 127.0.0.1 22
```

Expect on stderr:

```
endpoint id: <64 hex chars>
relay https://<your-relay> -> 127.0.0.1:22
```

From any machine with the official `iroh` wheel, test the round trip with the
same script's `stdio` mode:

```
ssh -o ProxyCommand="python examples\serve_node.py stdio <endpoint-id>" user@win7host ver
```

## 4. Autostart at boot (scheduled task, S4U)

1. Edit [`win7-task.xml`](win7-task.xml): replace `MACHINE\user`, the
   `pythonw.exe` path and the node directory.
2. From an elevated prompt:

```
schtasks /Create /TN "iroh-ssh serve" /XML win7-task.xml /F
schtasks /Run    /TN "iroh-ssh serve"
```

3. Verify: `C:\iroh7\serve.log` must show `endpoint id:` with the **same** id
   as in step 3. A different id means `USERPROFILE` drifted under the S4U
   logon — check that `serve_launcher.py` sits directly in the node directory
   so its `BASE.parents[0]` pin lands on `C:\Users\<you>`.

The S4U logon type ("run whether the user is logged on or not", no stored
password) is the whole point of the launcher: the sparse S4U environment is
exactly what `serve_launcher.py` defends against. If you ever delete the task
while the node is running, note that schtasks does not kill the live process —
stop it before removing the node directory.

## 5. Client side (any machine, official wheel)

Once the node is up, reach it with the `stdio` ProxyCommand (put it into
`~/.ssh/config` to make it a first-class host):

```
Host mywin7
    HostName mywin7                # placeholder; no DNS involved
    User you
    ProxyCommand python C:\path\to\serve_node.py stdio <endpoint-id>
    ServerAliveInterval 30
```

## 6. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Load error mentioning dependencies on `import iroh` | wheel not Win7-clean; run `tools/win7gap.py` against the machine's real DLLs |
| `endpoint id:` changes across restarts | `secret.key` not found under the task's environment — check the launcher's USERPROFILE pin |
| Two nodes fight for connections | the same `secret.key` was copied to a second instance; delete one and let it mint its own key |
| Relay connect fails | wrong `IROH_RELAY_URL`/token, or the relay is unreachable from the target network |
