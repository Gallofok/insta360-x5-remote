# insta360-x5-remote

[English](README.md) · **中文**

把 **Insta360 X5** 当作一个可远程控制的网络节点来操作的逆向笔记与工具：唤醒它、
保持它不休眠、让它联网、拉它的实时预览——由一台常开的小网关（例如树莓派）完成，
而不是依赖手机 App。

> 针对自有硬件的互操作性独立研究，与影石 / Arashi Vision / Insta360 无任何关联。
> 风险自负。改动相机可能导致变砖或失去保修。

---

## 一句话：现在能做什么

| 能力 | 状态 | 方式 |
|---|---|---|
| 解包固件 | ✅ | UBI/UBIFS，**未加密** → 提取 rootfs |
| 识别平台 | ✅ | Ambarella CV5，Linux 5.10 aarch64，博通 BCM43456（双频）Wi-Fi |
| 相机 root shell | ✅ | SD 卡开机钩子（可逆——拔卡即原版） |
| 蓝牙控制（唤醒/状态/录制/关机/配网） | ✅ | [`insta360ctl`](https://github.com/xaionaro-go/insta360ctl) + [X5 蓝牙补丁](https://github.com/soul667/insta360-x5-toolkit) |
| **从待机远程唤醒** | ✅ | 相机“睡着”时仍在广播 BLE，一条蓝牙命令几秒内把它拉回 |
| **保活** | ✅ | 持续占一个蓝牙会话 + 心跳（模仿 App）→ 相机不休眠、不掉网 |
| 加入已有 Wi-Fi（STA 模式） | ✅ | 蓝牙 `SET_WIFI_CONNECTION_INFO`（要**明文**密码，不是 64 位十六进制密钥） |
| 本地控制接口（OSC） | ✅ | `:80` 上的 HTTP OSC（`/osc/info`、`/osc/state`、`camera.getOptions`、`camera.startCapture` 等） |
| 解码实时预览协议（6666 端口） | ✅ | `syNceNdinS` 帧格式、H.264 High 双鱼眼、`START_LIVE_STREAM` |
| 把流转发到 VPS 远程观看 | ✅ | VPN 叠加网络 + MediaMTX/go2rtc（现成成熟方案） |
| **无需热点客户端、局域网直出实时预览** | ✅ | 非关联 LAN 客户端经内存热补丁门禁直接拉到实时 H.264 —— 见下 |

6666 端口的实时预览默认只服务**真正关联到相机自身热点的 Wi-Fi 客户端**。这道门禁被
**在内存里打补丁**后，一个普通的（从未关联、也不需要 5GHz 电台的）局域网客户端即可直接
拉到实时 H.264 流——相机改为加入**你自己的 Wi-Fi**、经局域网被够到。已端到端逆向并验证
（解码出真实画面）。见 [docs/live-patch.md](docs/live-patch.md)。（不打补丁的原厂路径仍需一个真实的 5GHz 热点客户端。）

---

## 平台

- **SoC：** Ambarella CV5（ARM64 Cortex-A53 + CVflow NPU/DSP + RTOS 协处理核）
- **系统（Linux 侧）：** Linux 5.10.x aarch64（BusyBox，主机名 `buildroot`）
- **Wi-Fi/蓝牙：** 博通 BCM43456——双频，出厂镜像**默认加载并发 AP+STA（apsta）固件**
- **关键守护进程：** `instaAIP`（网络 / OSC / 6666 消息服务）、`instaAlg`（拼接）、
  `amba_camctrl`（到 RTOS 的 IPC 桥）、`instaMonitor`（进程看门狗）

固件容器未加密：`linux` 卷是标准 UBI 镜像。从第一个 `UBI#` 标记切出，用
`ubireader` 解 UBIFS。

---

## 相机如何判断“有客户端连上了”

理解这一点是一切的钥匙。相机**综合三个独立信号**判断，而非单一信号：

1. **蓝牙链路 + 会话** —— 一个 GATT 服务器（服务 `0xBE80`，特征 `0xBE81/0xBE82`）。
   链路建立是控制器事件；而一个*会话*还需要 `syNceNdinS` 握手和周期心跳
   （`InsApp_HeartBeat_Thread`）。
2. **802.11 关联** —— 当有设备关联到热点时，`hostapd` 触发事件
   （`hostapd_event.sh`），置位内部 `ap_monitor_running` 标志并记录该客户端。
   这是硬件级事件，非关联的主机在软件层**伪造不出来**。
3. **6666 端口会话** —— 一条 TCP 控制/预览通道，有自己的握手、记录的客户端 MAC、
   以及心跳（存在“首包超时 / 空闲超时”回收机制）。

由此观察到：

- **蓝牙会话结束 ~120 秒后，相机会自动离开已加入的 Wi-Fi** —— STA 连接绑定在
  App 会话上，所以保活必须持续占着蓝牙。
- **原厂固件里,预览（6666）只服务真正关联的热点客户端** —— 见门禁。这道门禁可用内存
  补丁绕过,从而改为服务一个非关联的局域网客户端（见 [docs/live-patch.md](docs/live-patch.md)）。

---

## 6666 端口访问门禁（反编译结论）

预览/控制服务位于 `instaAIP` 里的线程 `InsMDev_Wifi_Connect_Monitor`。三道检查把
非热点客户端挡在外面（地址取自某一特定固件版本，当作“地图”而非定论）：

- 外层 `ap_monitor_running == 0` 守卫：没有关联客户端时，**跳过整个 select/accept 块**；
- 内层 `ap_monitor_running == 0` 守卫（就在 `accept()` 前，日志
  `"Wifi ap_monitor_running is false, skip accept."`）；
- **客户端 MAC 检查**：`strncmp(client_mac, authorized_mac)`——不匹配则拒绝，
  日志 `"diff mac not allow connect"`。

这就解释了：从局域网、从 loopback、或源地址伪造成 `192.168.42.x` 去连 `:6666`，都是
**TCP 能连上、但握手永远没回应**——服务器查的是*真实关联*，不是对端 IP。

这些分支是**用 `ptrace` 在内存里**对*正在运行*的 `instaAIP` 打补丁的——不写 flash、不换
二进制、重启进程即还原。这取代了此前"需要串口（UART）"的结论:在这台闭源设备上替换磁盘上
的守护进程确实不现实（它会抢回 USB gadget、改回 `hostapd`、独占蓝牙栈,exFAT 日志又不刷盘），
但内存热补丁这条路避开了这一切。上面这几道只是 accept 侧的检查——`wifi_recv` 线程和**发送
路径**还各带自己的 `ap_monitor_running` 检查;完整可用的配方（以及那个点亮回包/视频路径的
关键数据标志）在 [**docs/live-patch.md**](docs/live-patch.md)。

---

## 逆向方法（可复现）

1. **固件：** 切出 UBI 卷，用 `ubireader` 解 UBIFS。
2. **初筛：** `strings` + 自写的 **AArch64 交叉引用工具**，它能解析
   `ADRP+ADD` / `ADRP+LDR`（字面量池）形式的引用（直接 `objdump | grep` 会漏掉字面量池
   那种）。把日志字符串映射到使用它的函数。
3. **顺系统调用：** 定位唯一的 `accept()` / `getpeername()` 调用点找到服务器循环。
4. **反编译：** Ghidra（无头）。在 **aarch64 主机**上公开版不带原生反编译器——从源码编：
   `make -C Ghidra/Features/Decompiler/src/decompile/cpp ghidra_opt ARCH_TYPE=`
   （需要 `bison`/`flex`；Makefile 默认的 `-m32` 对 arm64 是错的，所以置空 `ARCH_TYPE=`），
   再把 `ghidra_opt` 放到 `…/Decompiler/os/linux_arm_64/decompile`。Ghidra 12.x 需要 JDK 25。
5. **协议：** 在 root 手机上用 `tcpdump` 抓官方 App（经热点）的通信，重组 6666 端口的 TCP 流，
   解码带长度前缀的 `syNceNdinS` 帧 + 复用的 H.264 子流。

---

## 架构（参考）

**不再需要关联相机的 5GHz 热点。** 不是网关去连相机的 AP，而是让**相机加入你自己的
Wi-Fi**（STA 模式，经蓝牙配网），网关在普通局域网上就能够到它——然后在内存里给 6666
门禁打补丁、直接拉流：

```
      网关经蓝牙：唤醒 / 保活 / 让相机加入你的 Wi-Fi / 控制
   ┌──────────────────────────────────────────────────────────────────┐
   │                                                                    ▼
[网关]  ◀────────── 你家里的 Wi-Fi / LAN ──────────▶  [X5 作为 STA 接入你的 Wi-Fi]
 任何常开、带蓝牙的        （相机经蓝牙 SET_WIFI_                        │
 小盒子——不需要 5GHz        CONNECTION_INFO 加入）                       │ root shell
 电台、不需要关联热点              │                                     │ （SD 开机钩子）
   │                              │   内存 ptrace 热补丁                 ▼
   │                              │   instaAIP 的 6666 门禁  ──▶  H.264 双鱼眼
   │                              └──────── 经 LAN 拉 6666 ──────────────┘
   └── 上行 ──▶ [VPS：拼接 + MediaMTX] ──VPN──▶ 手机（远程观看）
```

网关是任何常开、带蓝牙的小盒子（例如树莓派——哪怕只有 2.4GHz 也行）。它**不需要 5GHz
电台，也从不关联相机热点**:经蓝牙唤醒相机、保活、让相机加入你已有的 Wi-Fi;然后在同一
局域网上打开 root shell（SD 开机钩子）、应用内存门禁补丁、直接经 LAN 拉 `6666`。旧的
"网关需要 5GHz 客户端去关联 AP"的限制已经没有了。

---

## 现状 / 局限

- **向非关联客户端的局域网直播：已解决。** 门禁补丁是**用 `ptrace` 在内存里打的**
  （不碰 flash、不换二进制、不需要串口——此前“需要串口”的结论已被取代），一个普通
  局域网客户端即可拉到实时 H.264——已端到端逆向并验证（解码出真实画面）。
  见 [docs/live-patch.md](docs/live-patch.md)。
- **仍开放：真正“完全独立”的直出（相机自己转发、无任何外部拉流端）。** 目前打完补丁的
  相机仍需要有东西去拉 `6666`（一个局域网客户端，例如网关，再转发到 VPS）。让相机自己
  经 loopback 拉自己的 `6666` 再转发，在原厂固件里是被额外挡住的；完整补丁集
  （含 `ap_monitor_running=1`）现在是否放行了设备自身的客户端，尚未测试。
- 这里的一切都是**版本相关**的。固件地址、门禁布局、乃至协议细节，都会随版本变化——
  自己重新推导，别盲信偏移量。
- 本仓库**不分发**任何固件镜像、提取的二进制或补丁后的文件——只有方法和结论。

## 文档与代码

- [**Agent 交接文档**](AGENT_HANDOFF.md) —— 项目现状 + 下一步该做什么，供后续接手
- [功能对照表](docs/capabilities.md) —— 已验证 / 部分 / 未解决，逐条
- [6666 访问门禁（深入）](docs/gate-re.md) —— 反编译逻辑 + 补丁定位
- [活进程内存 patch（ptrace）](docs/live-patch.md) —— 改运行中的守护进程，不刷 flash，重启即还原
- [复现指南](docs/reproduce.md) —— 从解包固件到抓协议到 Ghidra
- [`tools/`](tools/) —— 分析工具（AArch64 交叉引用、pcap/流解码、Ghidra 脚本、门禁探针）
- [`gateway/`](gateway/) —— 运行时：SD 卡 root 钩子、保活守护进程 + systemd 单元

## 致谢

- [`xaionaro-go/insta360ctl`](https://github.com/xaionaro-go/insta360ctl) —— 蓝牙/Wi-Fi 控制工具
- [`soul667/insta360-x5-toolkit`](https://github.com/soul667/insta360-x5-toolkit) —— X5 蓝牙协议补丁
- [`shack-32/Insta360-X5-FW-Mod`](https://github.com/shack-32/Insta360-X5-FW-Mod) —— X5 固件开机钩子 / 切包
- [`schlarpc/insta360-link-firmware-re`](https://github.com/schlarpc/insta360-link-firmware-re) —— 相关的 Insta360 固件逆向

## 许可

文档：CC BY 4.0。原创脚本：MIT。商标归各自所有者。
