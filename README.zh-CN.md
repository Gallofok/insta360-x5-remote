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
| **无需热点客户端、相机本机/局域网直出预览** | ❌ | 被一道访问门禁挡住（见下） |

要实现“完全远程实时看画面”，**唯一缺的一环**是：**一个真实关联到相机自身热点的
Wi-Fi 客户端**（相机热点是 5GHz，所以只有 2.4GHz 的网关直接关联不上）。

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
- **预览（6666）只服务真正关联的热点客户端** —— 见门禁。

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

把这几个分支 NOP 掉在机械上很简单，开机钩子也能（可逆地）跑一个改过的 `instaAIP`。
**但是**在这台闭源设备上稳定部署/验证一个改过的主守护进程，**没有硬件串口几乎做不到**：
`instaAIP` 会反复抢回 USB gadget、把 `hostapd` 改回去、独占蓝牙栈，而 exFAT 的日志写
又不刷盘——盲目部署会把相机弄成远程无法恢复的状态。**串口（UART）是这条路诚实的前提。**

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

```
                 蓝牙：唤醒 / 保活 / 配网 / 控制
   ┌─────────────────────────────────────────────────────────┐
   │                                                          ▼
[网关]  ── Wi-Fi 客户端 ──▶  [X5 热点]  ── 6666 ──▶  H.264 双鱼眼
   │  (要 5GHz 才能                                           │
   │   关联到这个 AP)                                         ▼
   └── 上行/有线 ──▶ [VPS：拼接 + MediaMTX] ──VPN──▶ 手机（远程观看）
```

网关可以是任何常开、带蓝牙 + 5GHz Wi-Fi 客户端的小盒子（例如插了一块 Linux 免驱 5GHz
USB 网卡的树莓派）。因为 6666 门禁要求*真实*关联的客户端，网关的 Wi-Fi 电台必须能关联
相机的 5GHz 热点。

---

## 现状 / 局限

- **“完全独立（无需额外客户端）的实时直播”尚未解决** —— 要么有一个真实 5GHz 热点客户端，
  要么有一个门禁被打补丁的 `instaAIP`（后者又需要串口才能安全部署/调试）。
- 这里的一切都是**版本相关**的。固件地址、门禁布局、乃至协议细节，都会随版本变化——
  自己重新推导，别盲信偏移量。
- 本仓库**不分发**任何固件镜像、提取的二进制或补丁后的文件——只有方法和结论。

## 文档

- [功能对照表](docs/capabilities.md) —— 已验证 / 部分 / 未解决，逐条
- [6666 访问门禁（深入）](docs/gate-re.md) —— 反编译逻辑 + 补丁定位
- [复现指南](docs/reproduce.md) —— 从解包固件到抓协议到 Ghidra

## 致谢

- [`xaionaro-go/insta360ctl`](https://github.com/xaionaro-go/insta360ctl) —— 蓝牙/Wi-Fi 控制工具
- [`soul667/insta360-x5-toolkit`](https://github.com/soul667/insta360-x5-toolkit) —— X5 蓝牙协议补丁
- [`shack-32/Insta360-X5-FW-Mod`](https://github.com/shack-32/Insta360-X5-FW-Mod) —— X5 固件开机钩子 / 切包
- [`schlarpc/insta360-link-firmware-re`](https://github.com/schlarpc/insta360-link-firmware-re) —— 相关的 Insta360 固件逆向

## 许可

文档：CC BY 4.0。原创脚本：MIT。商标归各自所有者。
