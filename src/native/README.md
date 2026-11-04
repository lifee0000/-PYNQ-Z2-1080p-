# V4 ARM 原生数据通路：2026-10-24 无损传输升级

当前匹配身份已完成161组实板回归、五段3015帧完整视频及五分钟混合传输子测试。
实际速度与范围以工程根目录 REPORT_CN.md、QUALIFICATION.json 为准；720p50仍未通过。
下方“升级前”段落与 README_BEFORE_INTEGRATION.md 为历史信息。

`liby50_native.so` 在 PYNQ-Z2 ARMv7l 实际编译；`y50_native.dll` 在 Windows 编译，仅供 mock 传输测试，两者用途不同。

## 匹配接口

- 原生配置 ABI **2**，21 个参数偏移。
- 协议 **PZYUV4S / 3**，64 字节包头、84 字节参数；32 字节返回元数据。与旧 v2 客户端不兼容，须成套更新 PC/板端程序。
- 格式 **YUYV422_BT709_FULL_YUV_V4_SPLIT**。
- IP **video_enhance_yuyv422_v4_split_core**。
- `noise_floor_uv=0xB0`、`frame_count=0xB8`、`stream_errors=0xC8`；实际偏移以生成表和匹配 HWH 为准。
- 服务端口 5010，三组独占输入/输出 CMA，单个有限帧 DMA 所有者；网络收、算、发可重叠。

板端 CPU 只执行传输编解码和校验，曝光、去噪等图像算法仍由 FPGA 执行。DMA 每帧结束确认双向 halted、ap_done、frame_count=1、stream_errors=0；停稳后断言处理复位。断言期间不读取 HLS 核 AXI-Lite。

当前主版本是 ACP C：AxCACHE=15、AxUSER=31，双向 DMA 地址段显式纳入 512M 映射。使用 `--coherent-acp`，通过 ACP 访问缓存一致内存。HP 回退才使用 `--cacheable` 显式维护缓存，两者不可互换。当前 ACP C 通过 161 组像素回归及实际取消/断线测试；完整视频约 11–12 帧/秒，仍不是 50 帧/秒。

上述数值属于升级前 v2 传输的历史验收。本目录 v3 改动必须重新编译 ARM 原生库、生成匹配清单、完成像素/传输/完整视频回归后才能另行验收；旧数据不等同于新程序通过。

## v3 无损线协议

- HELLO 的 flags=0 请求 raw；flags=1 请求 LZ4。响应 `selected_codec` 必须等于请求，客户端不能静默切换到另一模式。
- FRAME 的 flags=0 表示原始 YUYV，长度必须等于 `width*height*2`；flags=1 表示 LZ4 独立块，仅可用于已经协商 LZ4 的会话，长度必须小于原始帧字节数。
- 包头最后 8 字节的高 32 位必须为 0，低 32 位为解码后原始帧的 XXH32(seed=0)。原始和压缩两种形式均校验。XXH32 用于检测意外数据损坏，不是身份认证或密码学完整性保护。
- 所有控制包 checksum=0。除 HELLO 的协商位外，控制包 flags=0；未知标志、超长包、解码长度不等、校验失败均终止该会话，错误输入不会送入 DMA。
- 两端仅在 LZ4 至少节省 12.5% 字节时发送压缩块，否则发送带校验的原始帧。每块独立、无跨帧字典，不做图像压缩损失或丢帧。
- 当前先用分散的三个4KB样本估计2倍收益，再尝试完整压缩。压缩帧最多三帧在途，原始回退按单帧发送；这只改变传输表示和节奏。
- 板端收/发线程各有一个按已验证分辨率分配的有界压缩缓冲区。解码直接写到当前线程持有的输入 CMA；接收和校验完成后才交给 DMA。输出 CMA 在压缩和发送全部完成前保持独占。
- `transport_profile` 记录原始/线上字节数、压缩帧数、压缩/解压和双向校验耗时。`receive_ns`/`send_ns` 只包含网络操作；不能用压缩比代替实际完整视频帧率。

依赖来自官方 LZ4 v1.10.0；固定源码和许可证位于 `vendor/lz4`，来源与哈希见 `UPSTREAM.json`。`python native/build_native.py` 会编译该固定版本，无需系统安装压缩库。C/Python 配置 ABI 仍为 2，BIT/HWH 和算法参数未改变。

检测已有硬件所有者后才加载，严格校验构建文件哈希。若 DMA 无法停止，保留 CMA/MMIO 而不释放活动缓冲，等待人工恢复。不会自动杀死其他硬件程序或添加开机自启。

推荐由电脑软件自动启停临时服务。板端手动启动当前 ACP C：`python3 -u native/board_bootstrap.py --manifest native_yuyv.experimental.json --coherent-acp`。结束：等待客户端退出后 Ctrl+C，看到 STOPPED。部署 ZIP 和完整命令见根目录说明。

构建身份保留 EXPERIMENTAL_UNQUALIFIED；实际验收写独立证据，不能编辑哈希或状态字符串跳过测试。`README_BEFORE_INTEGRATION.md` 是集成前历史记录。
