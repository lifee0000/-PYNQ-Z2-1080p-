# 独立 YUYV 原生数据面：当前保存状态

2026-10-23：用户要求保存进度并停止上板；本目录没有上传、加载 Overlay 或启动板端程序。

当前只有 **Windows 主机编译与 mock 传输回归**。ARM 编译、真实 DMA、缓存一致性、六模式逐像素和实际 720p50 吞吐均未验证。没有生成可宣称通过实板验收的 native 发布版。

## 已写内容

- `y50_native.h/.cpp`：C ABI 1；三对独立 input/output CMA 缓冲区；reader、单 DMA worker、sender 三线程；直接 `recv` 至输入 CMA、直接 `send` 输出 CMA。输出全部发送前不回收其槽位。原生 MMIO 后端没有 CPU 图像处理。
- `binding.py`：Python ctypes ABI 与引用保活。
- `protocol.py`：独立 `PZYUYV1` v1 协议和 Python host client；有界 3 帧窗口；独占连接；frame ID/PTS 严格有序、同会话固定 time base；保留完整返回字节。
- `board_bootstrap.py`：先验证实验清单、BIT/HWH、源文件与库哈希，再检查现有 RGB 服务所有者，然后由 PYNQ 加载、分配 CMA 和取得真实 MMIO 指针。默认 uncached；显式 `--cacheable` 使用 Python callback 真正执行输入 flush、输出前后 invalidate。
- `make_manifest.py`：只记录 `EXPERIMENTAL_UNQUALIFIED` 身份，不生成 PASS、不修改旧工程身份、不代替上板回归。
- `build_native.py`：Linux/Windows 构建入口；`test_native_mock.py`：本机传输测试。

## 硬件接口

`video_enhance_yuyv422_v3_core`，`YUYV422_BT709_FULL_Y_V3`；内存是 `Y0 U0 Y1 V0`，AXIS16 每像素一拍，低 8 位 Y、高 8 位交替 U/V。所有参数按 `protocol.PARAMETER_ORDER` 排列，20 个 uint32 网络大端字；brightness 是 int32 补码。不会自动将有限范围视频解释成全范围。

实际寄存器偏移来自兄弟目录 `output/yuyv422_v3.registers.json`，由真实 HLS 驱动头提取。Bootstrap 不写死偏移。frame_count 当前 0xb0、stream_errors 0xc0，但只有与未来 BIT/HWH 哈希绑定后才可以用于板端。

默认外设名：`axi_vdma_file_process`、`video_processing_slot`、`axi_gpio_processing_reset`。GPIO 低电平断言 core reset；断言期间绝不读取 core AXI-Lite。有限一帧 DMA：S2MM → core ap_start → MM2S；两路 halted、ap_done、frame_count==1、stream_errors==0 才返回帧。每帧结束停止 DMA 并保持 core reset。

## 协议与生命周期

64 字节头格式 `!8sHHIQqIIIIIIQ`，依次 magic/version/op/flags/frame_id/PTS/time_base_num/time_base_den/payload_bytes/parameter_bytes/width/height/reserved。flags/reserved 必须为零。HELLO=1、FRAME=2、FIN=3、STATUS=4、CANCEL=5；应答 op 加 0x8000，ERROR=0xffff。独立端口 **5010**。

FRAME request：头 + 80 字节参数 + width×height×2 字节 YUYV。

FRAME response：头 + `!IIIIQQ` 的 32 字节元数据（frame_count、stream_errors、MM2S status、S2MM status、DMA elapsed ns、reserved）+ 原生输出字节。

所有单次收发都有绝对 deadline；单硬件所有者、三槽上限、第一硬件故障锁存。运输取消会结束该连接并等待 DMA 停止；硬件错误之后必须重启服务。若 DMA 无法 halted，返回 `UNSAFE_DMA`，bootstrap **保持 CMA/MMIO 引用，不释放缓冲**，等待开发板断电重启。没有自动杀死其他程序、自动重启板子或忽略错误。

mock 仅做 memcpy，绑定 127.0.0.1，CAPS 明示 `MOCK_TRANSPORT_ONLY`；正常 FPGA client 默认拒绝 mock。mock 测试不证明曝光/去噪算法，不证明 DMA，不证明板端性能。

## 本机复现

```powershell
python build_native.py --compiler C:/msys64/mingw64/bin/g++.exe
python test_native_mock.py
```

编译使用 C++17、`-O3 -Wall -Wextra -Wpedantic`。Windows DLL 可能需要编译器目录中的 libwinpthread DLL；测试脚本为现有 C:/msys64 环境显式加入该路径。DLL 不是 ARM 板端程序。

## 后续上板入口（本轮未执行）

仅在用户恢复上板授权、已有匹配的新 YUYV BIT/HWH、停止现有 RGB 服务后：

```bash
python3 native/build_native.py
python3 native/make_manifest.py --root . --bit output/file_process_yuyv.bit --registers output/yuyv422_v3.registers.json --library native/liby50_native.so
python3 native/board_bootstrap.py --manifest native_yuyv.experimental.json
```

先做小尺寸和纯色字节序、六模式和 ROI 完整逐像素对照、取消和慢客户端回归，再做唯一帧号/不同像素的持续 1280×720 吞吐。必须从实际返回帧数、墙钟耗时、丢帧/错序/硬件计数验收；HLS II=1 或 50fps 播放时间戳不能代替文件通路吞吐。

YUYV422 每帧 1,843,200 字节，50fps 每向净载荷 92.16MB/s；降低 1/3 带宽并不保证实际 50fps。当前服务原型仍每帧重置 DMA/core，是否达标须实测；不达标后才据真实阶段计时评估持续 DMA 或更进一步传输方案。
