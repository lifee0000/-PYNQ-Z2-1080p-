# 基于 PYNQ-Z2 的 1080p 自适应视频增强系统

在 PYNQ-Z2（Zynq-7020）开发板上实现的 1080p 视频增强系统，采用“电脑统计选参、FPGA 逐像素增强”的软硬件协同架构。

- **FPGA（PL）**：每时钟 1 像素的全定点图像增强核（孤立脉冲抑制、保边降噪、带拐点的色调映射、软核心细节增强、过冲限制、清晰度、色度降噪、色彩跟随、ROI 局部处理），3 路并行 Rice 近无损解码器，tANS 无损回传编码器，100 MHz 时序收敛。
- **开发板（PS）**：C++ 板端服务，接收压缩帧与 96 字节参数，调度 DMA 与各 IP。
- **电脑端**：视频解码与缩放、亮度/噪声/纹理统计、场景自适应选参、原片与结果同帧对照播放、逐帧参数曲线分析与编辑、H.264 导出。

| 指标 | 结果 |
|---|---|
| 处理分辨率 | 1920×1080，YUYV 4:2:2，BT.709 |
| 端到端速度 | 12.3～33.2 帧/秒（12 类实拍视频） |
| 压缩比（上行 / 回传） | 2.4～12.8 / 2.6～14.5 |
| FPGA 资源（XC7Z020） | LUT 88.7%，FF 46.6%，BRAM 85.4%，DSP 49.1% |
| 正确性 | 回传像素与位精确参考模型逐字节一致 |

## 目录结构

```
src/                电脑端程序、板端服务与通信协议
  native/           电脑端与板端的原生代码（C/C++）及协议
  board_runtime.zip 每次处理前上传到开发板的运行包（内容由 native_yuyv.experimental.json 校验）
hardware/
  hls/              HLS 源码（增强核、Rice 解码器、tANS 编码器）及测试语料
  rtl/  tcl/        顶层与 Vivado 工程脚本
  ip_repo/          已导出的 IP
  output/           比特流（.bit）与硬件描述（.hwh）
  board_files/      PYNQ-Z2 板级文件
```

## 运行环境

- PYNQ-Z2 开发板，PYNQ v3.1.1 系统镜像，网线直连电脑；电脑网口设为 `192.168.2.1/24`，开发板地址 `192.168.2.99`。
- 开发板上无需预先安装本系统文件，程序会自动上传运行包并启动板端服务。

## 从源码运行

```bash
cd src
pip install -r requirements.txt
python launcher.py
```

需要 Python 3.12 及以上。

## 打包为 Windows 程序

```bash
cd src
pip install pyinstaller
python build_app.py
```

结果位于 `src/Windows_App/PYNQVideoV4/`。

## 测试

```bash
cd src
python -m unittest discover -s . -p "test_*.py"
```

`src/native` 目录下同样执行上述命令。

## 硬件重建

`hardware/hls` 中各 IP 可用 Vitis HLS 重新综合并导出到 `hardware/ip_repo`，再用 `hardware/tcl` 中的脚本在 Vivado 中生成工程与比特流。修改板端代码或比特流后，需要重新生成 `src/board_runtime.zip` 及其校验清单。
