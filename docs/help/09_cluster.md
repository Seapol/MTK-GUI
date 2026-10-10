# Cluster & Multi-Station Management

The **ClusterPage** (route `cluster`) is a read-only overview board
over the cluster scheduler: it visualizes the current snapshot and
exposes a small set of actions that drive the scheduler API.  The
scheduler owns the state — the page only reads it and forwards your
clicks, so the board can never drift from the real queue.

Concepts used by the code:

- **hub** — the `ClusterScheduler` instance shared by all stations of
  one cluster; it holds the device pool, the task queue and the
  running map.
- **load balancer** — the idle-first, least-loaded pick inside
  `assign_next()`: an idle device always wins over a busy one, and
  among idle devices the lowest accumulated busy seconds wins.
- **task queue** — FIFO list of submitted tasks with a `kind` tag and
  an estimated effort `weight`; tasks wait in `QUEUED` until a
  matching device frees up.
- **resource hub** — the per-device lock tokens: each task holds one
  exclusive token for its whole run, so two tasks can never share a
  device (isolation, no preemption).

## Page layout

- Status line: `集群设备 N 台 | 排队 M | 运行中 K` — a one-glance
  health summary of the whole cluster.
- Device board (7 columns): 设备 / 类型 / 状态 / 活跃 / 完成 / 失败 /
  负载.
  - 负载 shows the accumulated busy time in seconds (`123.4s`), which
    is the balancing score: active tasks dominate, busy time breaks
    ties.
- Task board (4 columns): 任务 / 类型 / 状态 / 设备.
  - Statuses: `QUEUED` (waiting), `RUNNING` (holding a device token),
    `DONE`, `FAILED`, `MIGRATED` (re-queued after a device fault).
- Action bar:
  - `派发下一任务` — runs one dispatch sweep (`assign_next()`).
  - `摘除选中设备` — reports the selected device faulty; its running
    tasks migrate automatically.
  - `恢复选中设备` — returns a repaired device to the pool.
  - `刷新看板` — re-reads the snapshot and repaints both tables.

**Note:** the page emits `dispatched(running_count)` after every
dispatch sweep — dashboard widgets may subscribe; the scheduler never
polls the page back.

## Step-by-step: dispatch tasks across a cluster

1. Register your devices in the scheduler (they appear in the device
   board with 状态 `IDLE`).
2. Submit tasks; each shows up as `QUEUED` in the task board with its
   `kind` tag.
3. Press `派发下一任务` — the least-loaded idle device of the matching
   kind acquires the task and its status flips to `RUNNING`.
4. Repeat the sweep (or let your runner loop call it) until the queue
   drains; the status line updates 排队 / 运行中 after each sweep.
5. Finished tasks leave the running map; per-device 完成 counters
   increase, 失败 counters track failed completions.

### How the balancer picks a device

- Candidates are filtered by: matching `kind`, device state `IDLE`,
  and device acquireable.
- Idle devices (no active tasks) are preferred over busy ones.
- Among equals, the lowest load score wins:
  `score = active + busy_s / 3600.0`.
- A device that has an active task is only used when nothing idle
  remains — busy devices are avoided and the task stays queued.

**Warning:** tasks are never preempted.  A `RUNNING` task keeps its
device until it completes, fails, or the device is removed by an
operator — there is no live migration of a running task.

## Step-by-step: failover (摘除 / 恢复)

1. Select the faulty device row in the device board.
2. Press `摘除选中设备` — the scheduler force-releases the device,
   marks it `ERROR`, and every `RUNNING` task on it is re-queued as
   `MIGRATED` (its queue entry returns with the device cleared).
3. Press `刷新看板` — the migrated tasks reappear as `QUEUED` and are
   picked up on the remaining devices by the next dispatch sweep.
4. After repair, select the device again and press `恢复选中设备` —
   the error state clears and the device re-enters the idle pool.
5. Confirm the recovery in the board: 活跃 drops to 0, 状态 returns to
   `IDLE`, and the next sweep may assign work to it again.

**Note:** every failover action is recorded in the scheduler audit
trail (`[CLUSTER]` lines with action + detail), so the board state can
always be traced back to the operator action that caused it.

### Step-by-step: monitor load balance

1. Run a batch with several tasks of the same `kind`.
2. Watch the 负载 column: devices that ran more work accumulate more
   busy seconds.
3. Dispatch a new task — it should land on the device with the lowest
   活跃 first, then the lowest 负载.
4. If one device keeps winning, check for a `kind` mismatch: tasks
   whose kind only matches one device have no alternative.

### Snapshot data (for integrators)

`refresh()` renders exactly what `scheduler.snapshot()` returns:

```json
{
  "devices":  [{"name": "S1", "kind": "tester", "active": 1,
                "completed": 12, "failed": 0, "busy_s": 340.5}],
  "states":   {"S1": "RUNNING"},
  "queue":    [{"task_id": "T7", "kind": "tester", "weight": 2.0,
                "status": "QUEUED", "device": null}],
  "running":  [{"task_id": "T5", "device": "S1",
                "status": "RUNNING"}]
}
```

- The device board is fed from `devices` + `states`.
- The task board shows `queue` + `running` concatenated.
- The status line counts `len(devices)`, `len(queue)`,
  `len(running)`.

### Symptom → Cause → Fix

- **Symptom:** tasks stay `QUEUED` forever.
  - **Cause:** no idle device of the matching `kind` exists, or all
    matching devices are in `ERROR`.
  - **Fix:** check the 类型 column against the task kind; remove the
    kind filter mismatch, restore faulty devices, then sweep again.
- **Symptom:** `派发下一任务` does nothing.
  - **Cause:** the queue is empty, or every candidate device lost the
    acquisition race (busy).
  - **Fix:** submit a task first; press 刷新看板 to confirm 排队 > 0.
- **Symptom:** a device shows `ERROR` after 摘除.
  - **Cause:** that is the designed fault state — the device cannot be
    acquired until restored.
  - **Fix:** press `恢复选中设备` on that row.
- **Symptom:** a task vanished from the board.
  - **Cause:** it completed or failed — it left `queue` + `running`
    and lives only in the scheduler history.
  - **Fix:** check the per-device 完成/失败 counters; export the
    audit trail for the task timeline.
- **Symptom:** two tasks landed on the same device.
  - **Cause:** impossible by design — each task holds an exclusive
    token for the whole run.
  - **Fix:** verify you are looking at the live snapshot (press
    刷新看板) and not a stale render.

## Related pages

- `08_reports_logs.md` — the event log lines produced by dispatch and
  failover sweeps.
- `10_audit_security.md` — which roles may dispatch / remove devices.
- `12_faq.md` — quick answers for stuck queues and busy devices.
