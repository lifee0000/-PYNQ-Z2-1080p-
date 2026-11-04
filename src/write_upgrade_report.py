from pathlib import Path
import hashlib,json,statistics
ROOT=Path(__file__).resolve().parent;WS=ROOT.parents[1];dest=WS/'P4_UP'
full=json.loads((ROOT/'evidence/full_videos.json').read_text());assert full['status']=='PASS'
soak=json.loads((ROOT/'evidence/soak_300s/soak.json').read_text());assert soak['status']=='PASS'
pixels=json.loads((ROOT/'evidence/pixels_v3_lz4.json').read_text())
wire=json.loads((ROOT/'evidence/wire_benchmark.json').read_text())
identity=json.loads((ROOT/'board_runtime.json').read_text())['identity']
previous={'camera':11.048976601511468,'particles':12.1711007,'FourPeople':11.881698,'Johnny':11.692938,'KristenAndSara':11.664555}
labels={'camera':'实拍竖屏（完整720p黑边适配）','particles':'粒子视频','FourPeople':'FourPeople 人物','Johnny':'Johnny 人物','KristenAndSara':'KristenAndSara 人物'}
rows=[]
for item in full['cases']:
    fps=item['processing_fps'];old=previous[item['name']];t=item['transport']
    rows.append(f"| {labels[item['name']]} | {item['frames']} | {old:.2f} | {fps:.2f} | {fps/old:.2f}× | {t['compressed_input_frames']} / {item['frames']} |")
bench=[]
for name in ('people','camera','particles'):
    values={}
    for codec,window in (('raw',1),('lz4',1),('lz4',3)):
        samples=[r['fps'] for r in wire['rows'] if (r['name'],r['codec'],r['window'])==(name,codec,window)]
        values[(codec,window)]=f"{statistics.median(samples):.2f} [{min(samples):.2f}, {max(samples):.2f}]"
    bench.append(f"| {name} | {values[('raw',1)]} | {values[('lz4',1)]} | {values[('lz4',3)]} |")
text='''# V4 网线通路升级：实际验收与改进报告

日期：2026-10-24。开发板 PYNQ-Z2，保持现有网线方案。此次是传输与软件升级，**720p、端到端50帧/秒仍未通过**，比赛作品整体也未标为完成。

## 实际完成

新增双向 LZ4 无损传输、原始像素 XXH32 校验、压缩收益估计和自适应在途窗口。软件默认允许最多三帧压缩流水；遇到难压缩帧，提前准备下一帧，同时把大块原始数据按单帧发送。两端都保留完整像素，没有降低分辨率、删掉算法帧、插帧或用播放帧率代替处理速度。

增强像素仍由原有 V4 FPGA 核计算；电脑/ARM 的新增工作是无损传输编解码、校验和调度。PC 自动曝光/噪声统计的计算归属仍为 PC。FPGA 曝光、高光和 Y/UV 空间去噪公式保持原版，本轮没有新增时域去噪或语义识别。完整视频的所有回传哈希都与上一版对应帧相同，因此本轮应称为**保持画质的传输提速**。

## 五段完整视频

以下为包含解码、固定颜色转换、自动参数分析、网线、真实 FPGA、预览回调和编码导出的处理速度；自动临时部署/停止另外统计。与上次结果的比较属于两次完整工程运行，后台负载可能有差异，不是隔离硬件上限测试。

| 素材 | 完整帧数 | 上版 fps | 新版 fps | 观察比值 | 输入压缩帧 / 总帧 |
| --- | --- | --- | --- | --- | --- |
'''+ '\n'.join(rows)+'''

五段共 **3015 帧**，每一帧的 FPGA 输出 SHA256、帧号、PTS、处理参数均通过独立参考验收，并与上一版逐帧相同；完成计数为1、流错误为0。源片有音轨时，音频压缩包负载及时间戳核对一致。原始无损采样帧、完整逐帧记录和 H.264 观看对照都已保存。

实拍有大面积黑边、粒子有大面积低变化背景，压缩收益较大。三段人物画面的细节较多，默认估计决定使用原始帧，保持约12fps。因此不能把32.15fps推广为所有视频速度，也不能称50fps实时达标。输出文件保留源片时序；MP4播放属性60fps不代表每秒处理了60帧。

人物素材来自 Xiph 官方公开序列 [FourPeople / Johnny / KristenAndSara](https://media.xiph.org/video/derf/)，保留上次下载的来源、版本、哈希和网页存档；使用的是有损WebM预览，而非原始未压缩真值。没有把这三段室内人物素材当作自然暗光、室外或全场景画质证明。

新结果在 `results/upgrade_20261024`。每个 `*_FPGA_前后对照.mp4` 左为输入、右为实际 FPGA 输出。观看副本经过H.264编码，数值验收使用回传YUYV哈希和无损样本。

## 帧通路三轮重复测速

三轮交替测量；每项20个不同时间帧，固定相同参数，均逐帧核对参考。包含网络、校验和FPGA，不含视频解码/编码；表中为中位数及最小/最大值，单位fps。部分测速期间电脑也在重建EXE，数据不作为空载隔离上限；上面的完整视频测试在EXE重建完成后运行。

| 20帧基准素材 | 原始帧、窗口1 | 自适应压缩、窗口1 | 自适应压缩、最多窗口3 |
| --- | --- | --- | --- |
'''+ '\n'.join(bench)+'''

共36次、720帧实板基准全部一致。原始模式的固定窗口3也有记录，保留了较慢样本，没有筛掉不利结果。默认策略依据估计压缩收益切换，文件名不参与选择；这只决定传输表示与调度，不干预图像内容。

## 取舍和失败试验

1. 初始全帧压缩候选使人物样本下降到约6–9fps；已被替代，原始结果和对应源码/库保存在 `V4/experiments/v3_full_compress`。
2. 现版先取分散的三个4KB样本，估计至少2倍压缩收益才尝试完整压缩。实际压缩后还要求节省至少12.5%，否则仍发送完整原始帧。PC压缩加速参数为1，ARM为4；两端均无损、无跨帧字典。
3. ARM按实际检测到的Cortex-A9指令目标编译，没有改变时钟或电压。额外的手写NEON校验试验在2192个大小/偏移案例上正确，但约6.12ms慢于标量约3.65ms，已取消默认启用；记录在 `arm_hash_neon_trial.json`。当前标量库另外完成2192次实板对照。
4. 静态三帧窗口会让难压缩画面变慢；现版只对可压缩帧保持最多三帧，大块原始回退时限制一个在途帧。静态窗口历史记录保存在 `V4/experiments/static_window_v3`。

## 正确性、边界与停止

- 71项算法/像素/软件测试 + 37项无损编解码/传输测试，共108项通过。
- 当前身份的161组实际FPGA回归通过，最大字节误差0；其中含六模式、720p、Y/UV滤波和ROI边界。
- 实板验证忙碌拒绝、半帧断线、原始校验错误、压缩校验错误、非法压缩块、最大不可压缩帧、在途取消和慢接收。坏输入未增加DMA处理计数。
- HELLO协商必须匹配，协议版本3与旧版本2整套更新；校验值为原始像素XXH32，用于意外损坏检测，不是密码学认证。参数和长度受限，解码目标为已独占的输入CMA；校验完成后才能排入DMA。发送结束后才允许复用输出CMA。
- Windows EXE已重建；在新交付目录的移位自检通过，五段全视频由该EXE的CLI真实完成。GUI同帧预览逻辑沿用既有实现，新增无损开关和默认调度；本轮没有进行人工点选界面目视验收。
'''+f"- 新传输混合稳定性子测试连续 **{soak['seconds']:.3f}秒、{soak['frames']}帧**，每帧唯一标记和哈希全部一致，{soak['fps']:.2f}fps。交替难压缩/易压缩场景以覆盖原始回退及三帧窗口切换。包含网线与FPGA，**不含视频编解码**。\n"+'''
此前版本的30分钟24686帧长稳保留在历史证据；它不能代替本次新传输的最终30分钟完整视频测试。当前五分钟子测试也没有降低或满足最终30分钟要求。

每次完整视频及最终子测试结束都协作停止本次拥有的服务，确认双向DMA halted、运行位0、处理GPIO0、临时目录已移除。最终进程/端口快照见 `evidence/upgrade_20261024/final_board_state.json`。Linux/Jupyter继续运行，FPGA配置可以保留但处理复位，不能说FPGA已清空。没有添加开机自启、杀掉其他用户进程或改电脑VPN/网卡。

## 构建匹配

BIT/HWH和寄存器表与上一版相同；ARM库、协议、Windows EXE、板端ZIP须使用本次配套版本。

'''+ '\n'.join(f"- {k}: `{identity[k]}`" for k in ('bit_sha256','hwh_sha256','native_sha256','manifest_sha256'))+'''

身份中的EXPERIMENTAL_UNQUALIFIED保留生成时原文，验收写在独立证据中，没有改状态或哈希跳过检查。旧HP回退与HDMI V3在各自目录保持原配套；V4 HDMI没有在本轮重新验收。

## 运行与继续改进

解压到 `C:\\P4` 等短路径，打开 `P4_UP`，双击 `START.cmd`。开发板上电、网线连接，默认IP192.168.2.99、Jupyter端口9090；在软件选择真实FPGA、导入视频并开始。默认无损传输开启；需要对照时可勾选串行或关闭无损传输。处理结束会停止本次临时服务。

源码命令（在V4目录）：`python launcher.py --input 输入.mp4 --output 新输出.mp4 --managed`。仅预览加`--preview-only`；原始帧对照加`--wire-codec raw --serial`。软件不会覆盖输入或已有输出。

后续优先：

1. 复杂人物/纹理画面是当前瓶颈。先分解网口内核、CMA、校验成本；在ARM实测可逆Y/U/V平面化或预测变换的收益，再决定是否加入协议。以复杂素材完整视频FPS为门槛，不能仅看稀疏背景峰值。
2. 若评估有损编码，必须同步预算两端编解码与质量误差，再确定方案。当前1280×720、YUYV422、50fps仍需每方向92.16MB/s原始有效负载；新压缩不保证所有场景达到该吞吐。
3. 画质下一阶段建立自然暗光、背光、肤色、细字/头发、快速运动、切镜素材集。先冻结可量化参考，再增加运动门控时域去噪、色度处理或硬件统计，验证拖影/闪烁后才移植HLS。
4. 对最终软件/库执行30分钟含编解码长视频、恢复/冷启动及HDMI独立验收，补官方评分表和提交要求。11月4日截止由用户提供，正式规则尚未归档。

原上传包和20261023密封交付保持不变。新的完整工程另存P4_UP；可在它的V4源码继续开发，保留旧包回退。报告、源文件、实际视频、逐帧证据、硬件匹配文件和校验清单均随包交付。
'''
(dest/'REPORT_CN.md').write_text(text,encoding='utf-8')
(dest/'README_CN.md').write_text('''# PYNQ V4 网线视频增强升级版（2026-10-24）

1. 解压到短路径，例如 `C:\\P4`，进入 `P4_UP`。
2. 开发板上电并接网线，电脑能打开 `http://192.168.2.99:9090/lab`。
3. 双击本目录 `START.cmd`，导入视频、选择输出位置，保持“FPGA实板”和“无损传输”开启，点开始。
4. 左右为同一帧输入与FPGA回传；默认同时导出视频。完成后自动停止并清理本次临时程序。

已实板完整验证五段3015帧。实拍约20.61fps、粒子约32.15fps、复杂人物约11.8–11.9fps；720p50目标尚未达到。所有增强像素仍由FPGA计算，传输保持无损。

处理后视频和同帧对照在 `results/upgrade_20261024`；完整说明见 `REPORT_CN.md`。`history_20261023` 与旧证据属于历史版本，不能当作新库的验收。

- `V4`：当前软件源码、EXE、BIT/HWH、ARM库、配套板端包、测试与证据。
- `fallback_HP`：保留旧HP配套回退；不能与主版本混用。
- `HDMI_V3`：历史HDMI演示；本轮没有重新认证V4 HDMI。
- `public_sources`：三段公开人物视频及来源/哈希。
- `00_control` 等目录：要求与证据的追溯表；竞赛总验收仍为HOLD。

请保留整个Windows_App目录，不能只复制EXE。初始板端密码默认xilinx；若已改密码，在软件填写自己的板端密码。只临时运行，不安装自启或更改频率/电压。

可用Python运行根目录 `verify_package.py` 复核所有交付文件；该校验不连接开发板。继续优化请复制V4后修改，旧压缩包用于回退。
''',encoding='utf-8')
(dest/'V4/README.md').write_text('''# V4 当前入口

运行完整软件：上一层 START.cmd。源码：安装 requirements.txt 后执行 `python launcher.py`。
默认真实FPGA、自动参数、双向自适应无损传输，压缩帧最多三帧在途，原始回退按单帧发送。
CLI示例：`python launcher.py --input 输入.mp4 --output 新输出.mp4 --managed`。
FPGA公式保持V4；端到端720p50尚未达到。具体测量与限制见上一层 REPORT_CN.md。

重建PC：`python native/build_codec.py --compiler <g++路径>`、`python build_app.py`。
修改板端原生代码后：`python compile_board_native.py` → `python verify_arm_hash.py` →
`python native/make_manifest.py --root . --bit output/file_process_yuyv422.bit --registers output/yuyv422_v4.registers.json --library native/liby50_native.so` →
`python package_board_runtime.py` → `python qualify_upgrade.py`。
之后重新打Windows程序并执行全视频验证；新清单不等于验收通过。
修改HLS/RTL则另需Vivado重建配套BIT/HWH与寄存器表，再完整回归。

`experiments` 为被替代候选。`evidence` 里历史记录按构建身份区分，当前结果见根目录升级报告。
所有测试和构建辅助脚本均有限时/所有权检查；生产入口不需要用户在板上长期安装程序。
''',encoding='utf-8')
qualification=dict(schema=1,release='PYNQ_V4_UPGRADED_20261024',whole_contest_complete=False,
    target_720p50='NOT_ACHIEVED',pixel_tests=pixels['cases_passed'],maximum_byte_error=pixels['max_absolute_error'],
    complete_video_frames=sum(r['frames'] for r in full['cases']),
    all_frames_exact_to_prior_release=True,identity=identity,scope='Lossless transport and scheduling upgrade; image formula unchanged',
    current_soak_seconds=soak['seconds'],final_thirty_minute_full_video='NOT_VERIFIED',official_scoring='NOT_PROVIDED',
    gui_manual_observation_this_revision='NOT_PERFORMED',software_tests=108)
(dest/'QUALIFICATION.json').write_text(json.dumps(qualification,indent=2),encoding='utf-8')
print('Wrote current report, operating guide and scoped qualification')
