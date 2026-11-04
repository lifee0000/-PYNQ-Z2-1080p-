# 交付副本依赖与接口说明

本目录是独立实验原型，不是完整工程默认运行的 RGB24 板端服务。

- Windows `y50_native.dll` 旁已附带同架构 `libwinpthread-1.dll`；现有许可证原文保存在 `licenses/`。交付副本的 mock 测试只从本目录加入 DLL 搜索路径，不依赖原开发电脑的 `C:/msys64` 运行目录。重新编译仍需要自行安装/指定 C++ 编译器。
- `native/evidence/host_checks.json` 是交付副本实际重新编译、8 项本地 loopback mock 测试所得的指纹。mock 仅复制数据验证所有权、顺序、取消和有界缓冲，不能证明 FPGA 图像算法、DMA 或 50fps。
- 原生服务和 YUV-v3 top 的参数为 **20 项**，格式 `YUYV422_BT709_FULL_Y_V3`；`algorithms/v4_split` 新接口是 **21 项**，额外包含 `noise_floor_uv`，top/格式身份也不同。二者禁止互换 BIT、寄存器表、worker 或客户端协议。它们同样不能与 RGB24 的 `board.zip`/worker 混用。
- 该实验仍没有新 YUV BIT/HWH、ARM `.so` 或板端验收清单；没有利用其他工程文件拼补这些缺项。Windows DLL 不能用于 ARM 板端。
- 为保留可核查证据，仅选择性保存 HLS `syn/report` 的 rpt/xml、`sim/report` 的 cosim.rpt、`csim/report` 的 csim.log，并保持原相对路径。没有复制整个 HLS 构建树或启动新的 HLS/Vivado/板端操作。

正式启动板端仍需后续单独获得匹配的 YUV BIT/HWH、ARM 原生库和实验身份清单，完成独立硬件回归后再启用。当前交付不包含此实验的上板结果。
