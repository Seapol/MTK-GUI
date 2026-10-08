# B2-YamlBuild 验收清单（Acceptance Checklist）

- 日期：2026-10-08
- 分支：`feature/p3-b2-core`（最新 `d5bf023`）
- 范围：P3-B2 Yaml Build 流水线（12 阶段 block-flow）+ 本轮 GUI 体验批次
- 状态图例：`[ ]` 待验收 / `[x]` 通过 / `[-]` 阻塞（注明原因）
- 规则：每项验收需在指定模式下实际操作；Virtual 项在 Mac/Windows 均过，
  Real 项必须在 Windows 实机架完成

## A. Virtual 模式全链路（无需硬件，可立即验收）

### A1 登录与账户
- [ ] Supervisor 密码登录成功；错误密码弹出 Login Failed
- [ ] Virtual 模式开关仅 Supervisor 可用；Operator 登录自动锁 Real
- [ ] File > Switch Account 重新认证后角色/权限即时生效
- [ ] 登录界面布局：表单卡片居中、无中部空洞、控件 8px 圆角统一（5 主题下检查 Light/Dark 至少各一次）

### A2 文件菜单（YAML 生命周期）
- [ ] Load Yaml：加载项目格式 YAML 全部页面还原（产品信息、ICT/FCT、Equipment、console、构建模型、rails）
- [ ] Load Yaml：加载 plan 格式（`plan`+`yaml_build`）路由到 Yaml Build 模型，无静默失败
- [ ] Apply and Save / Save as：保存后重新加载内容一致（round-trip）
- [ ] **Close Yaml**：确认弹窗 → 产品信息清空、stop 策略默认、ICT/FCT 单空行、rails/console 清空、Equipment 出厂、构建模型全新化、标题文件名 `(none)`
- [ ] 未加载 YAML 时 Run 被拦截（No Test Project 弹窗 + Event Log 记录）

### A3 Yaml Build 12 阶段流水线
- [ ] Design Input：SPF/NET 加载、产品元信息回填（core id / part / batch）
- [ ] Parse nets：三分类计数合理，Filtered 理由正确（gnd_ref / diff pair / 无引脚）
- [ ] Channel Allocation：下拉分配 Power（Impedance+Power rails+Voltage）/ Clock（SE Clock Hz）/ GPIO（DIO）
- [ ] **未分配通道的 net 不进入 ICT 序列构建器**（auto Do-Not-Test）
- [ ] Configure Instruments 面板：每行独立 Connect/Disconnect；Virtual 显示 virtual 结果；行状态 Error（红）路径可复现
- [ ] Rails / Clocks / GPIO 模块参数与 Channel Allocation 联动一致
- [ ] ICT Work Flow 序列：标准 op 包裹（impedance 在上电前）、Move/双击编辑/Auto 填充（power ±5%、clock 50ppm、精度 0.001V / 0.1Hz）
- [ ] 每块 OK 右上角打星 ★ → Validate Full Test Sequence 通过变勾 ✓，失败保持星
- [ ] Build 产出合规命名 YAML（`Plan_..._build_final_v.1.0.0.yaml`）+ archive 副本

### A4 Test Work Flow 运行行为
- [ ] **每次 Run 开始清空上次波形**；DAQ AI 执行后重新抓波重画（Long Run 第二循环同样先清后画）
- [ ] Overall Result 只显示 PASS/FAIL；仅"Stop 且无 FAIL 项"显示 IGNORE；有 FAIL 时 Stop 也显示 FAIL
- [ ] Overall Result 前缀 `Virtual`（Virtual 模式）
- [ ] stop 策略：stop-on-short 默认开（阻抗 FAIL 中止）、stop-on-fail 默认关
- [ ] Long Run 循环计数 / Interval 逻辑正常（Interval 仅 Long Run>1 可编辑）
- [ ] CSV 导出：virtual 文件名带 `virtual`；AI review 文件生成于 CSV 同目录
- [ ] FCT 前置 console 自动连接：失败 → Error + FAIL 弹窗；成功 → 继续运行
- [ ] 故障注入：fail ratio 100% 全 FAIL、error ratio 100% 全 Error、0/0 全 PASS

### A5 状态栏与 Equipment
- [ ] Instruments LED 跟随 Equipment 页连接状态（不再恒绿）
- [ ] Tools 批量 Connect/Disconnect/Reset/Test：Virtual 模式报 virtual 结果（**不再弹 no 'Address' 错误**）；Real 模式走 RealGateway
- [ ] **Console: 标签**在第一个 console LED 前；通道增删/重同步后标签保留
- [ ] 状态栏布局完整：Version / Role / Mode / User / 进度条 / Instruments / Console / 日期

### A6 自动化
- [ ] `pytest tests/` 全绿（已知唯一偶发：`test_full_sequence_passes` "power rail CSV log missing"，见 D 节）
- [ ] `python smoke_test.py` → ALL SMOKE TESTS PASSED（默认工程 96317）
- [ ] 8 个范例项目 `scripts/build_project_yaml.py projects` 全部 OK（Windows 上先跑，smoke 依赖其产物）

## B. Real 模式实机（Windows + 真机架，发布 gate）

### B1 部署
- [ ] Windows `git pull` + venv + 依赖安装（PySide6 6.10.3）
- [ ] PyInstaller 按 `MTK_GUI_windows.spec` 打包：`_internal/config`（permissions.json + 2 xlsx）、`_internal/yaml_plan/examples`、`_internal/resources` 在位；**用户运行产物不入包**
- [ ] exe 启动正常；高 DPI 缩放显示复核（字体、布局无截断）
- [ ] SmartScreen / 防病毒误报评估

### B2 仪器驱动（[验收人] 签字）
- [ ] DAQ973A 主机 + DAQM908A#1/#2 + DAQM907A：VISA 连接、Test Connection、Init Instruments op
- [ ] U2355A：AI 采集（rails CSV 落盘、采样率/触发设置生效）、计数器、DIO
- [ ] N5747A：PSU 上/下电、4 线 sense、hardware inhibit（E-Stop）
- [ ] 地址只来自 YAML（equipment 节 Address 字段）；断线重连路径

### B3 实机 ICT 序列（96317 或等价项目）
- [ ] 阻抗（上电前）→ 上电 → rails 采集 → 电压 → 时钟 → GPIO 全序列跑通
- [ ] 失败路径：SCPI 超时 / 错误 → 行 Error、Overall FAIL、弹窗与 Event Log 一致
- [ ] Long Run 连续 N 循环无泄漏（线程/会话/文件句柄）
- [ ] 实机数据合理性抽查：CSV 电压 vs 万用表、时钟频率 vs 信号源

## C. 回归红线（每次合并前必过）
- [ ] `pytest tests/` 无新增失败
- [ ] `smoke_test.py` 全过
- [ ] 界面契约变更已先更新 `docs/interface_spec.md`（SOLO 规则）
- [ ] 未触碰非本任务 worktree 目录

## D. 已知遗留（不阻塞 B2 验收，但需跟踪）
- [ ] engine 偶发 `test_full_sequence_passes` "power rail CSV log missing"（隔离必过、套件中偶发）——专项排查
- [ ] Virtual AI review 对 96317 的 10 rails 仅 4/10 pass：错峰上电 vs AI review 采集窗口参数不匹配——调整 review 窗口或 capture 时长
- [ ] `docs/tasks.md` 遗留决策 D1（RF 范围）/ D2（Flash FAT/OOBE 自动化 vs 手动）/ D4（Supervisor 密码存储）——B3 启动前拍板

## E. 签核
| 项 | 人 | 日期 | 结论 |
|---|---|---|---|
| A Virtual 全链路 | | | |
| B Real 实机 | | | |
| C 回归红线 | | | |
| B2 验收通过（gate to B3） | | | |
